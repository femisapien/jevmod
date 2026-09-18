"""Fail on AI tells in the site copy: em/en dashes, emoji outside <code>, marketing adjectives, Inter as a font.
Usage: python scripts/site/check_text.py [docs]"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED_WORDS = re.compile(
    r"\b(seamless(ly)?|elevate|unleash|next-gen|revolutioni[sz]e|cutting-edge|powerful|robust|effortless(ly)?|"
    r"supercharge|game-changing|world-class|blazing(ly)? fast)\b",
    re.I,
)
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿⭐✅❌]")
ALLOWED_EMOJI_IN_CODE = {"❌", "✅"}


def check(path: Path) -> list[str]:
    s = path.read_text(encoding="utf-8")
    problems = []
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    for i, line in enumerate(text.splitlines(), 1):
        if "—" in line or "–" in line:
            problems.append(f"{path}:{i}: em/en dash")
        if BANNED_WORDS.search(line):
            problems.append(f"{path}:{i}: marketing word: {BANNED_WORDS.search(line).group(0)}")
        no_code = re.sub(r"<code[^>]*>.*?</code>", "", line)
        for m in EMOJI.finditer(no_code):
            problems.append(f"{path}:{i}: emoji outside <code>: {m.group(0)!r}")
    if re.search(r"font-family:[^;]*\bInter\b", s):
        problems.append(f"{path}: Inter used as a font")
    return problems


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
    files = [p for p in root.rglob("*") if p.suffix in (".html", ".css") and "jevmod" not in p.parts[-2:-1]]
    problems = [p for f in files for p in check(f)]
    print("\n".join(problems) or f"text ok: {len(files)} files")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
