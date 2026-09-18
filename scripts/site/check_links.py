"""Every internal href/src in docs/**/*.html resolves to a file or an anchor; external links answer < 400.
Usage: python scripts/site/check_links.py [docs] [--external]"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "docs")
    external = "--external" in sys.argv
    problems: list[str] = []
    checked: dict[str, int | str] = {}
    for f in sorted(root.rglob("*.html")):
        s = f.read_text(encoding="utf-8")
        ids = set(re.findall(r'\sid="([^"]+)"', s))
        for m in re.finditer(r'(?:href|src)="([^"#]*)(#[^"]*)?"', s):
            url, frag = m.group(1), m.group(2)
            if url.startswith(("mailto:", "data:", "javascript:")):
                continue
            if url.startswith("http"):
                if external and url not in checked:
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "jevmod-linkcheck"}, method="HEAD")
                        checked[url] = urllib.request.urlopen(req, timeout=15).status
                    except Exception as exc:  # noqa: BLE001
                        checked[url] = str(exc)[:60]
                    if not isinstance(checked[url], int) or checked[url] >= 400:
                        problems.append(f"{f}: external {url} -> {checked[url]}")
                continue
            if url == "":
                if frag and frag[1:] and frag[1:] not in ids:
                    problems.append(f"{f}: anchor {frag} not found")
                continue
            target = (root / url.lstrip("/")) if url.startswith("/") else (f.parent / url)
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                problems.append(f"{f}: missing {url}")
    print("\n".join(problems) or "links ok")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
