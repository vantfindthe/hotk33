"""Builds the coding / terminal prediction models in app/predictive/modes/.

Each mode is trained on source files found on this PC (plus, for terminals,
the hand-written command lists in tools/seeds/). Run from the project folder:

    .venv\\Scripts\\python tools\\build_modes.py                  # all modes
    .venv\\Scripts\\python tools\\build_modes.py python bash      # some modes
    .venv\\Scripts\\python tools\\build_modes.py python --extra D:\\src\\my-project
        (also learn from your own code - repeatable)
    .venv\\Scripts\\python tools\\build_modes.py powershell bash cmd --history
        (also learn from your PowerShell / bash command history; the model
         keeps fragments of it, so don't share the .json.gz afterwards)

A new language can be added with --new:
    tools\\build_modes.py rust --new "Rust" .rs D:\\src\\my-rust-repo
"""

import argparse
import gzip
import json
import os
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "predictive" / "modes"
SEEDS = Path(__file__).resolve().parent / "seeds"

ORDER = 7            # predict from up to 6 previous characters
MAX_CHARS = 8_000_000
MIN_CONTEXT = 5      # drop contexts seen fewer times (orders >= 3)
KEEP_NEXT = 6        # next-character candidates kept per context
MAX_VOCAB = 40_000
SEED_REPEAT = 25     # weight of the hand-written command lists

PY_LIB = Path(sys.base_prefix) / "Lib"
GIT = Path(r"C:\Program Files\Git")
HOME = Path(os.environ.get("USERPROFILE", "~"))
_node = shutil.which("node")
NODE = Path(_node).parent if _node else Path(r"C:\Program Files\nodejs")
APPDATA = Path(os.environ.get("APPDATA", "~"))

MODES = {
    "python": {
        "name": "Python", "exts": [".py", ".pyw"], "token": r"[a-z_][a-z0-9_]*",
        "comment": "#", "dirs": [PY_LIB, NODE],
    },
    "javascript": {
        "name": "JavaScript / TypeScript", "exts": [".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"],
        "token": r"[a-z_$][a-z0-9_$]*", "comment": "//",
        "dirs": [NODE, GIT, PY_LIB],
    },
    "powershell": {
        "name": "PowerShell", "exts": [".ps1", ".psm1"], "token": r"[a-z_$][a-z0-9_-]*",
        "comment": "#", "seed": "powershell.txt",
        "dirs": [Path(r"C:\Windows\System32\WindowsPowerShell\v1.0"),
                 Path(r"C:\Program Files\WindowsPowerShell\Modules"),
                 Path(r"C:\Program Files\PowerShell"), NODE, GIT, PY_LIB],
        "history": [APPDATA / r"Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt"],
    },
    "cmd": {
        "name": "Command Prompt (cmd)", "exts": [".bat", ".cmd"], "token": r"[a-z_%][a-z0-9_-]*",
        "comment": "rem ", "seed": "cmd.txt",
        "dirs": [NODE, GIT, PY_LIB, Path(r"C:\Program Files\WindowsPowerShell")],
    },
    "bash": {
        "name": "Bash / Git Bash / WSL", "exts": [".sh", ".bash"], "shebang": True,
        "token": r"[a-z_$][a-z0-9_-]*", "comment": "#", "seed": "bash.txt",
        "dirs": [GIT / r"mingw64\libexec\git-core", GIT / r"usr\bin", GIT / "etc",
                 GIT / r"usr\share", NODE, PY_LIB],
        "history": [HOME / ".bash_history"],
    },
}

SKIP_DIRS = {"__pycache__", ".git", "test", "tests", "dist", "min", "locale"}
_SPACES = re.compile(r"[ \t]+")
_SHEBANG = re.compile(rb"^#!.*\b(ba)?sh\b")
_PRINTABLE = re.compile(r"^[ -~]+$")


def read_text(path):
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="ignore")
    return data.decode("utf-8", errors="ignore")


def normalize(text, comment):
    """Lowercase, no indentation (editors insert it), single spaces, no
    comment-only lines, no blank lines."""
    out = []
    for line in text.lower().splitlines():
        line = _SPACES.sub(" ", line).strip()
        if not line or not _PRINTABLE.match(line) or (comment and line.startswith(comment.strip())):
            continue
        if len(line) > 200:  # minified code / data blobs
            continue
        out.append(line)
    return "\n".join(out)


def find_files(cfg, dirs):
    exts = set(cfg["exts"])
    files = []
    for d in dirs:
        if not d.exists():
            continue
        for root, subdirs, names in os.walk(d):
            subdirs[:] = [s for s in subdirs if s.lower() not in SKIP_DIRS]
            for name in names:
                p = Path(root) / name
                ext = p.suffix.lower()
                if ext in exts:
                    files.append(p)
                elif cfg.get("shebang") and not ext and p.stat().st_size < 500_000:
                    try:
                        with open(p, "rb") as f:
                            if _SHEBANG.match(f.read(64)):
                                files.append(p)
                    except OSError:
                        pass
    return files


def corpus(mode, cfg, extra_dirs, history):
    parts, size = [], 0
    seed = cfg.get("seed")
    if seed and (SEEDS / seed).exists():
        text = normalize((SEEDS / seed).read_text(encoding="utf-8"), cfg["comment"])
        parts += [text] * SEED_REPEAT
        size += len(text) * SEED_REPEAT
    if history:
        for h in cfg.get("history", []):
            if h.exists():
                text = normalize(read_text(h), None)
                parts += [text] * 5
                size += len(text) * 5
                print(f"  + history {h} ({len(text):,} chars x5)")
    # your own code first, so the size cap never cuts it
    files = find_files(cfg, extra_dirs)
    stock = find_files(cfg, cfg["dirs"])
    random.Random(1).shuffle(stock)
    for p in files + stock:
        if size >= MAX_CHARS:
            break
        try:
            text = normalize(read_text(p), cfg["comment"])
        except OSError:
            continue
        parts.append(text)
        size += len(text) + 1
    print(f"  {len(files) + len(stock)} files found, {size:,} chars used")
    return "\n" + "\n".join(parts) + "\n"


def build(mode, cfg, extra_dirs, history):
    print(f"{mode}:")
    text = corpus(mode, cfg, extra_dirs, history)

    counts = [defaultdict(Counter) for _ in range(ORDER)]
    for i in range(1, len(text)):
        nxt = text[i]
        for k in range(min(ORDER - 1, i) + 1):
            counts[k][text[i - k:i]][nxt] += 1
    ngram = {}
    for k, table in enumerate(counts):
        for ctx, nexts in table.items():
            total = sum(nexts.values())
            if k >= 3 and total < MIN_CONTEXT:
                continue
            ngram[ctx] = [total] + [x for ch, c in nexts.most_common(KEEP_NEXT) for x in (ch, c)]

    token_re = re.compile(cfg["token"])
    vocab = Counter()
    followers = defaultdict(Counter)
    for m in token_re.finditer(text):
        tok = m.group(0)
        if len(tok) < 2:
            continue
        vocab[tok] += 1
        if m.end() < len(text):
            followers[tok][text[m.end()]] += 1
    vocab_out = {t: [c, dict(followers[t].most_common(5))]
                 for t, c in vocab.most_common(MAX_VOCAB) if c >= 3}

    OUT.mkdir(parents=True, exist_ok=True)
    data = {"id": mode, "name": cfg["name"], "order": ORDER, "token": cfg["token"],
            "exts": cfg["exts"], "ngram": ngram, "vocab": vocab_out}
    path = OUT / f"{mode}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"  {len(ngram):,} contexts, {len(vocab_out):,} tokens -> {path} "
          f"({path.stat().st_size / 1e6:.1f} MB)")

    index_path = OUT / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    index[mode] = {"name": cfg["name"], "exts": cfg["exts"]}
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("modes", nargs="*", help=f"modes to build (default: {' '.join(MODES)})")
    ap.add_argument("--extra", action="append", default=[], type=Path,
                    help="also learn from the code in this folder")
    ap.add_argument("--history", action="store_true",
                    help="also learn from your shell command history")
    ap.add_argument("--new", nargs="+", metavar=("NAME", "EXT_OR_DIR"),
                    help='define a new mode: "Display name" .ext [.ext ...] folder [folder ...]')
    args = ap.parse_args()

    if args.new:
        if len(args.modes) != 1:
            ap.error("--new needs exactly one mode id, e.g. rust")
        name, *rest = args.new
        MODES[args.modes[0]] = {
            "name": name, "exts": [x.lower() for x in rest if x.startswith(".")],
            "dirs": [Path(x) for x in rest if not x.startswith(".")],
            "token": r"[a-z_][a-z0-9_]*", "comment": "//",
        }
    for mode in args.modes or list(MODES):
        if mode not in MODES:
            ap.error(f"unknown mode {mode!r} (known: {', '.join(MODES)}; or use --new)")
        build(mode, MODES[mode], args.extra, args.history)


if __name__ == "__main__":
    main()
