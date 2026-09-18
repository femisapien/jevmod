"""Re-point every `path:line` citation in docs/CLAIMS.md at the line that still contains its token.

Line numbers drift whenever a cited file is edited or reformatted; the token is the stable part of a citation.
This only moves a citation within the file it already names, and it refuses to guess when the token is gone,
so it cannot turn a stale claim into a false one. Run it after touching code, then run check_claims.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAIMS = ROOT / "docs" / "CLAIMS.md"
ROW = re.compile(r"\| (C\d{2,3}[a-z]?) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|\s*$")
SRC = re.compile(r"^(?P<path>[\w./-]+):(?P<line>\d+)$")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def repoint(src: str, token: str) -> tuple[str, bool, str | None]:
    """Return (citation, moved, problem). A citation whose token still matches is returned unchanged."""
    m = SRC.match(src)
    if not m or not token:
        return src, False, None
    f = ROOT / m["path"]
    if not f.is_file():
        return src, False, f"{m['path']} does not exist"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    n = int(m["line"])
    if 1 <= n <= len(lines) and token.lower() in lines[n - 1].lower():
        return src, False, None
    hits = [i + 1 for i, t in enumerate(lines) if token.lower() in t.lower()]
    if not hits:
        return src, False, f"token {token!r} no longer appears in {m['path']}"
    best = min(hits, key=lambda h: abs(h - n))  # the nearest match, so a shifted block follows its own lines
    return f"{m['path']}:{best}", True, None


def main() -> int:
    out: list[str] = []
    moved = 0
    problems: list[str] = []
    for raw in CLAIMS.read_text(encoding="utf-8").splitlines(keepends=True):
        m = ROW.match(raw)
        if not m:
            out.append(raw)
            continue
        cid, page, sentence, sources, tokens, verified = m.groups()
        srcs = [s.strip() for s in sources.split(";")]
        toks = [t.strip() for t in tokens.split(";")]
        if len(toks) != len(srcs):  # one token for every source in the row
            toks = [tokens.strip()] * len(srcs)
        new: list[str] = []
        for src, token in zip(srcs, toks, strict=True):
            citation, did, problem = repoint(src, token)
            new.append(citation)
            moved += did
            if problem:
                problems.append(f"{cid}: {problem}")
        out.append(f"| {cid} | {page} | {sentence} | {'; '.join(new)} | {tokens} | {verified} |\n")
    CLAIMS.write_text("".join(out), encoding="utf-8")
    print(f"fix_claim_lines: re-pointed {moved} citation(s)")
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
