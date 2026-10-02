"""Next-character prediction, one model per mode.

English (EnglishModel): a word list with frequencies. For the word being typed,
every word that starts with what's typed so far votes for its next character,
weighted by how common it is; a complete word votes for space and punctuation.
When nothing matches (a name, a typo), a character trigram model built from
the same list takes over.

Coding and terminal modes (CodeModel): a character n-gram model trained on
source files / shell scripts (tools/build_modes.py), blended with completion
of the identifier or command being typed from the mode's vocabulary.

Every model also learns from what you type (in memory; saved to disk only if
"remember" is on): words and word pairs in English, character contexts and
identifiers in code.
"""

import bisect
import gzip
import heapq
import json
import re
import threading
from collections import Counter, defaultdict
from pathlib import Path

ENGLISH = "english"
CANDIDATES = 8           # ranked candidates returned; the caller maps them to keys

# ------------------------------------------------------------------ English

WORD_CHARS = set("abcdefghijklmnopqrstuvwxyz'")
SENTENCE_END = set(".?!")
# What follows a complete word, as a share of its weight.
WORD_END = {" ": 0.86, ",": 0.06, ".": 0.05}
# How fast learning takes over. Your typing is blended in by confidence: with
# n matching observations it gets a share of n / (n + HALF) * MAX of the vote.
USER_WORDS_HALF, USER_WORDS_MAX = 3.0, 0.7    # words you use
USER_PAIRS_HALF, USER_PAIRS_MAX = 1.0, 0.85   # which word you type after which
MAX_LEARNED = 20_000

_TOKEN = re.compile(r"([a-z']*)$")
_PREV = re.compile(r"([a-z']+) +$")


def _top(dist, n=CANDIDATES):
    return [ch for ch, w in heapq.nlargest(n, dist.items(), key=lambda kv: kv[1]) if w > 0]


def _normalized(dist):
    total = sum(dist.values())
    return Counter({k: v / total for k, v in dist.items()}) if total else Counter()


def _mix(base, learned, observations, half, cap):
    """Blends a learned distribution into `base`, more strongly the more
    observations back it. Both are normalized first."""
    learned = _normalized(learned)
    if not learned:
        return base
    if not base:
        return learned
    w = observations / (observations + half) * cap
    out = Counter({k: v * (1 - w) for k, v in base.items()})
    for k, v in learned.items():
        out[k] += v * w
    return out


class EnglishModel:
    id = ENGLISH
    name = "English"

    def __init__(self, words_path):
        self.words, self.freqs = [], []
        for line in Path(words_path).read_text(encoding="utf-8").splitlines():
            w, _, f = line.partition("\t")
            if w:
                self.words.append(w)
                self.freqs.append(int(f))
        order = sorted(range(len(self.words)), key=self.words.__getitem__)
        self.words = [self.words[i] for i in order]
        self.freqs = [self.freqs[i] for i in order]
        self._cache = {}
        self._trigrams = self._build_trigrams()
        self.user_words = Counter()
        self.user_pairs = defaultdict(Counter)

    def predict(self, text):
        """Ranked likely next characters after `text` (lowercase), best first."""
        if not text or text[-1] == "\n":
            return _top(self._word_dist("", None))
        last = text[-1]
        if last in SENTENCE_END or last in ",;:":
            return [" "]
        if last.isdigit():
            return []

        token = _TOKEN.search(text).group(1).lstrip("'")
        before = text[:len(text) - len(token)]
        prev = None
        if before.endswith(" ") and not before.rstrip().endswith(tuple(SENTENCE_END)):
            m = _PREV.search(before)
            prev = m.group(1) if m else None
        if before and not before.endswith((" ", "\n", '"', "(", "'")) and token:
            # glued to non-word text (e.g. "x2ab"): only the character model applies
            return _top(self._char_dist(token))

        return _top(self._word_dist(token, prev) or self._char_dist(token))

    def observe(self, text):
        """Called after every typed character; learns each finished word."""
        if text[-1] in WORD_CHARS:
            return
        words = text[:-1].split()
        if not words or text[-2:-1] in ("", " ", "\n"):
            return
        prev = words[-2] if len(words) > 1 and words[-2].isalpha() else None
        self._learn(words[-1].strip("'"), prev)

    def _learn(self, word, prev):
        if not word or not set(word) <= WORD_CHARS or len(word) > 30:
            return
        if len(word) == 1 and word not in ("a", "i"):
            return
        self.user_words[word] += 1
        if prev:
            self.user_pairs[prev][word] += 1
        if len(self.user_words) > MAX_LEARNED:
            for w, _ in self.user_words.most_common()[MAX_LEARNED // 2:]:
                del self.user_words[w]

    def _word_dist(self, prefix, prev):
        dist = _normalized(self._base_dist(prefix))
        mine, n = Counter(), 0
        for w, c in self.user_words.items():
            if w.startswith(prefix):
                self._vote(mine, w, prefix, c)
                n += c
        dist = _mix(dist, mine, n, USER_WORDS_HALF, USER_WORDS_MAX)
        if prev and prev in self.user_pairs:
            mine, n = Counter(), 0
            for w, c in self.user_pairs[prev].items():
                if w.startswith(prefix):
                    self._vote(mine, w, prefix, c)
                    n += c
            dist = _mix(dist, mine, n, USER_PAIRS_HALF, USER_PAIRS_MAX)
        return dist

    def _base_dist(self, prefix):
        dist = self._cache.get(prefix)
        if dist is None:
            dist = Counter()
            lo = bisect.bisect_left(self.words, prefix)
            hi = bisect.bisect_left(self.words, prefix + "\x7f")
            for i in range(lo, hi):
                self._vote(dist, self.words[i], prefix, self.freqs[i])
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[prefix] = dist
        return dist

    @staticmethod
    def _vote(dist, word, prefix, weight):
        k = len(prefix)
        if len(word) > k:
            dist[word[k]] += weight
        elif k:  # the word is complete
            for ch, share in WORD_END.items():
                dist[ch] += weight * share

    def _build_trigrams(self):
        tri = defaultdict(Counter)
        for w, f in zip(self.words, self.freqs):
            s = "^^" + w + "$"
            for i in range(2, len(s)):
                tri[s[i - 2:i]][s[i]] += f
        return tri

    def _char_dist(self, token):
        dist = Counter()
        for ch, f in self._trigrams.get(("^^" + token)[-2:], {}).items():
            if ch == "$":
                for end, share in WORD_END.items():
                    dist[end] += f * share
            else:
                dist[ch] += f
        return dist

    def stats(self):
        pairs = sum(len(b) for b in self.user_pairs.values())
        if not self.user_words:
            return ""
        return (f"{len(self.user_words):,} word{'s' * (len(self.user_words) != 1)}, "
                f"{pairs:,} word pair{'s' * (pairs != 1)}")

    def export_learned(self):
        return {"words": self.user_words,
                "pairs": {a: dict(b) for a, b in self.user_pairs.items()}}

    def import_learned(self, data):
        self.user_words.update(data.get("words", {}))
        for a, b in data.get("pairs", {}).items():
            self.user_pairs[a].update(b)

    def forget(self):
        self.user_words.clear()
        self.user_pairs.clear()


# ---------------------------------------------------------- code / terminals

USER_CTX_HALF, USER_CTX_MAX = 2.0, 0.9        # your character patterns
USER_TOKENS_HALF, USER_TOKENS_MAX = 2.0, 0.8  # your identifiers / commands
TOKEN_SHARE = 0.5         # blend of identifier completion vs. character model
MAX_USER_CONTEXTS = 200_000
_RUN_OF_SPACES = re.compile(r" {2,}")
_INDENT = re.compile(r"\n +")


def code_context(text):
    """Normalizes typed text the way the training corpus was: lowercase, no
    indentation, single spaces; the start of the context counts as a line start."""
    text = "\n" + text[-60:].replace("\t", " ")
    return _INDENT.sub("\n", _RUN_OF_SPACES.sub(" ", text))


class CodeModel:
    def __init__(self, path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        self.id, self.name = data["id"], data["name"]
        self.order = data["order"]
        self.ngram = data["ngram"]          # ctx -> [total, ch, count, ch, count, ...]
        self.token_re = re.compile(f"(?:{data['token']})$")
        vocab = sorted(data["vocab"].items())
        self.tokens = [t for t, _ in vocab]
        self.counts = [v[0] for _, v in vocab]
        self.followers = {t: v[1] for t, v in vocab}
        self._cache = {}
        self.user_ngram = defaultdict(Counter)
        self.user_tokens = Counter()
        self.user_followers = defaultdict(Counter)
        self.observed = 0

    def predict(self, text):
        ctx = code_context(text)
        dist = self._ngram_dist(ctx)
        m = self.token_re.search(ctx)
        token = m.group(0) if m else ""
        if token:
            tdist = self._token_dist(token)
            total = sum(tdist.values())
            if total:
                for ch in dist:
                    dist[ch] *= 1 - TOKEN_SHARE
                for ch, w in tdist.items():
                    dist[ch] += TOKEN_SHARE * w / total
        return _top(dist)

    def _ngram_dist(self, ctx):
        dist = Counter()
        weight_sum = 0.0
        for k in range(min(self.order - 1, len(ctx)), -1, -1):
            c = ctx[len(ctx) - k:]
            entry, user = self.ngram.get(c), self.user_ngram.get(c)
            if not entry and not user:
                continue
            corpus = Counter()
            if entry:
                for i in range(1, len(entry), 2):
                    corpus[entry[i]] += entry[i + 1] / entry[0]
            p = _mix(corpus, user or {}, sum(user.values()) if user else 0,
                     USER_CTX_HALF, USER_CTX_MAX)
            w = 6.0 ** k  # longer contexts dominate when they exist
            for ch, v in p.items():
                dist[ch] += w * v
            weight_sum += w
        if weight_sum:
            for ch in dist:
                dist[ch] /= weight_sum
        return dist

    def _token_dist(self, prefix):
        dist = self._cache.get(prefix)
        if dist is None:
            dist = Counter()
            lo = bisect.bisect_left(self.tokens, prefix)
            hi = bisect.bisect_left(self.tokens, prefix + "\x7f")
            for i in range(lo, hi):
                self._vote(dist, self.tokens[i], prefix, self.counts[i], self.followers)
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[prefix] = dist
        mine, n = Counter(), 0
        for t, c in self.user_tokens.items():
            if t.startswith(prefix):
                self._vote(mine, t, prefix, c, self.user_followers)
                n += c
        return _mix(_normalized(dist), mine, n, USER_TOKENS_HALF, USER_TOKENS_MAX)

    @staticmethod
    def _vote(dist, token, prefix, weight, followers):
        k = len(prefix)
        if len(token) > k:
            dist[token[k]] += weight
            return
        nexts = followers.get(token)
        total = sum(nexts.values()) if nexts else 0
        for ch, n in (nexts or {}).items():
            dist[ch] += weight * n / total

    def observe(self, text):
        ctx = code_context(text)
        ch, before = ctx[-1], ctx[:-1]
        if ch == " " and before.endswith((" ", "\n")):
            return  # indentation / double space: not in the training text either
        self.observed += 1
        for k in range(min(self.order - 1, len(before)) + 1):
            self.user_ngram[before[len(before) - k:]][ch] += 1
        if len(self.user_ngram) > MAX_USER_CONTEXTS:
            self.user_ngram.clear()
        m = self.token_re.search(before)
        if m and not self.token_re.search(ctx) and len(m.group(0)) >= 2:
            self.user_tokens[m.group(0)] += 1
            self.user_followers[m.group(0)][ch] += 1

    def stats(self):
        if not self.observed and not self.user_tokens:
            return ""
        names = len(self.user_tokens)
        return f"{self.observed:,} keystrokes, {names:,} name{'s' * (names != 1)}"

    def export_learned(self):
        return {"observed": self.observed,
                "ngram": {c: dict(n) for c, n in self.user_ngram.items()},
                "tokens": self.user_tokens,
                "followers": {t: dict(n) for t, n in self.user_followers.items()}}

    def import_learned(self, data):
        self.observed += data.get("observed", 0)
        for c, n in data.get("ngram", {}).items():
            self.user_ngram[c].update(n)
        self.user_tokens.update(data.get("tokens", {}))
        for t, n in data.get("followers", {}).items():
            self.user_followers[t].update(n)

    def forget(self):
        self.user_ngram.clear()
        self.user_tokens.clear()
        self.user_followers.clear()
        self.observed = 0
        self._cache.clear()


# ------------------------------------------------------------------ library

class Models:
    """All modes: English plus every model in modes/ (loaded on first use)."""

    def __init__(self, app_dir, learned_path=None):
        self.app_dir = Path(app_dir)
        self.learned_path = Path(learned_path) if learned_path else None
        self.loaded = {}
        self.lock = threading.Lock()
        try:
            index = json.loads((self.app_dir / "modes" / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = {}
        self.index = {ENGLISH: {"name": "English", "exts": []}}
        self.index.update({m: info for m, info in index.items()
                           if (self.app_dir / "modes" / f"{m}.json.gz").exists()})
        self._learned = self._read_learned()

    def names(self):
        return {m: info["name"] for m, info in self.index.items()}

    def get(self, mode):
        if mode not in self.index:
            mode = ENGLISH
        model = self.loaded.get(mode)
        if model is None:
            with self.lock:  # loading takes a moment; don't load twice
                model = self.loaded.get(mode)
                if model is None:
                    if mode == ENGLISH:
                        model = EnglishModel(self.app_dir / "words_en.txt")
                    else:
                        model = CodeModel(self.app_dir / "modes" / f"{mode}.json.gz")
                    model.import_learned(self._learned.get(mode, {}))
                    self.loaded[mode] = model
        return model

    def preload(self):
        for mode in self.index:
            self.get(mode)

    def _read_learned(self):
        if not self.learned_path or not self.learned_path.exists():
            return {}
        try:
            return json.loads(self.learned_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def stats(self):
        """[(mode name, what it has learned)] for modes that learned something."""
        out = []
        for mode, model in list(self.loaded.items()):
            s = model.stats()
            if s:
                out.append((self.index[mode]["name"], s))
        return out

    def save(self):
        if not self.learned_path:
            return
        data = dict(self._learned)
        data.update({m: model.export_learned() for m, model in self.loaded.items()})
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.learned_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.learned_path)

    def forget(self):
        self._learned = {}
        for model in self.loaded.values():
            model.forget()
        if self.learned_path and self.learned_path.exists():
            self.learned_path.unlink()
