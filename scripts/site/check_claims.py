#!/usr/bin/env python3
"""Check that every `data-claim` on the site has a row in docs/CLAIMS.md, that every row has a sentence on a page,
and that every source can be verified. Standard library only.

    python scripts/site/check_claims.py                 # every docs/**/*.html
    python scripts/site/check_claims.py docs/privacy/index.html docs/terms/index.html

Sources:
  path:line                       the line exists and contains the `token` column, or, when it is empty, at least
                                  one word of 4+ characters from the sentence (case-insensitive substring match)
  tests/test_x.py::test_y         the file exists and defines `def test_y`
  docs/img/name.webp (any file)   the file exists

Exit 1 on any failure, with one line per problem.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAIMS = ROOT / "docs" / "CLAIMS.md"
CLAIM_RE = re.compile(r'data-claim="([^"]+)"')
ID_RE = re.compile(r"^C\d{2,3}$")
LINE_RE = re.compile(r"^(?P<path>[^:\s]+):(?P<line>\d+)$")
TEST_RE = re.compile(r"^(?P<path>[^:\s]+\.py)::(?P<name>\w+)$")


def parse_claims(md: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Rows of every table whose header starts with `id |`. Returns {id: row} and problems."""
    rows: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    header: list[str] | None = None
    for n, raw in enumerate(md.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[0] == "id":
            header = cells
            continue
        if header is None or all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) != len(header):
            problems.append(f"CLAIMS.md:{n}: {len(cells)} cells, header has {len(header)}")
            continue
        row = dict(zip(header, cells, strict=True))
        cid = row["id"].strip("`")
        if not ID_RE.match(cid):
            problems.append(f"CLAIMS.md:{n}: bad id {cid!r}")
            continue
        if cid in rows:
            problems.append(f"CLAIMS.md:{n}: duplicate id {cid}")
            continue
        row["_line"] = str(n)
        rows[cid] = row
    return rows, problems


def tokens_of(sentence: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_$.]+", sentence) if len(t) >= 4]


def check_source(cid: str, row: dict[str, str]) -> str | None:
    src = row.get("source", "").strip().strip("`")
    if not src:
        return f"{cid}: empty source"
    m = TEST_RE.match(src)
    if m:
        f = ROOT / m["path"]
        if not f.is_file():
            return f"{cid}: test file {m['path']} not found"
        if not re.search(rf"^\s*(async\s+)?def {re.escape(m['name'])}\b", f.read_text(encoding="utf-8"), re.M):
            return f"{cid}: {m['path']} has no test {m['name']}"
        return None
    m = LINE_RE.match(src)
    if m:
        f = ROOT / m["path"]
        if not f.is_file():
            return f"{cid}: file {m['path']} not found"
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        n = int(m["line"])
        if n < 1 or n > len(lines):
            return f"{cid}: {m['path']} has {len(lines)} lines, no line {n}"
        text = lines[n - 1].lower()
        token = row.get("token", "").strip().strip("`")
        wanted = [token] if token else tokens_of(row.get("sentence", ""))
        if not any(t.lower() in text for t in wanted):
            what = f"token {token!r}" if token else "any 4+ character word of the sentence"
            return f"{cid}: {src} does not contain {what}: {lines[n - 1].strip()[:80]!r}"
        return None
    f = ROOT / src
    if f.is_file():
        return None
    return f"{cid}: source {src!r} is not path:line, a test id or an existing file"


def main(argv: list[str]) -> int:
    pages = [Path(p) for p in argv] if argv else sorted((ROOT / "docs").rglob("*.html"))
    pages = [p if p.is_absolute() else ROOT / p for p in pages]
    problems: list[str] = []
    if not CLAIMS.is_file():
        print(f"missing {CLAIMS}")
        return 1
    rows, problems = parse_claims(CLAIMS.read_text(encoding="utf-8"))

    on_pages: dict[str, str] = {}
    for page in pages:
        rel = page.relative_to(ROOT).as_posix()
        for cid in CLAIM_RE.findall(page.read_text(encoding="utf-8")):
            if cid in on_pages:
                problems.append(f"{cid}: used twice ({on_pages[cid]} and {rel})")
            on_pages[cid] = rel

    for cid, rel in sorted(on_pages.items(), key=lambda kv: int(kv[0][1:])):
        if cid not in rows:
            problems.append(f"{cid}: on {rel} but not in CLAIMS.md")

    checked_pages = {p.relative_to(ROOT).as_posix() for p in pages}
    for cid, row in rows.items():
        url = row.get("page", "").strip()
        page_file = ("docs" + (url if url.endswith("/") else url + "/") + "index.html") if url.startswith("/") else url
        if (not argv or page_file in checked_pages) and cid not in on_pages:
            problems.append(f"{cid}: in CLAIMS.md (line {row['_line']}) but on no page")
        if cid in on_pages or not argv:
            err = check_source(cid, row)
            if err:
                problems.append(err)
            if row.get("verified", "").strip().lower() != "yes":
                problems.append(f"{cid}: verified column is {row.get('verified', '')!r}, expected 'yes'")

    n_checked = len(on_pages)
    if problems:
        print(f"check_claims: {len(problems)} problem(s) across {n_checked} claim(s)")
        for p in problems:
            print("  " + p)
        return 1
    print(f"check_claims: ok, {n_checked} claim(s) on {len(pages)} page(s), every source verified")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
