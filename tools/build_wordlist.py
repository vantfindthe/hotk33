"""Builds app/words_en.txt (word<TAB>frequency per billion words) from wordfreq.

Only needed to regenerate the list: python tools/build_wordlist.py [count]
"""

import re
import sys
from pathlib import Path

from wordfreq import top_n_list, word_frequency

WORD = re.compile(r"^[a-z]+(?:'[a-z]+)?$")
SINGLE_LETTER_WORDS = {"a", "i"}


def main(count=60000):
    out = Path(__file__).resolve().parent.parent / "app" / "words_en.txt"
    lines = []
    for w in top_n_list("en", count):
        if not WORD.match(w) or (len(w) == 1 and w not in SINGLE_LETTER_WORDS):
            continue
        per_billion = round(word_frequency(w, "en") * 1e9)
        if per_billion > 0:
            lines.append(f"{w}\t{per_billion}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines)} words -> {out}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60000)
