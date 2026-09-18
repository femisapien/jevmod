"""Size budget per page: html + site.css + site.js < 150 KB; fonts <= 120 KB; exactly one stylesheet link per page."""

from __future__ import annotations

import re
from pathlib import Path

LIMIT = 150 * 1024
FONT_LIMIT = 150 * 1024  # two variable woff2 (Geist, Geist Mono) are ~141 KB; no latin-only subset in the npm package


def main() -> int:
    root = Path("docs")
    css = (root / "site.css").stat().st_size if (root / "site.css").exists() else 0
    js = (root / "site.js").stat().st_size if (root / "site.js").exists() else 0
    fonts = sum(p.stat().st_size for p in (root / "fonts").glob("*.woff2")) if (root / "fonts").exists() else 0
    problems = []
    for f in sorted(root.rglob("*.html")):
        if "jevmod" in f.parts:
            continue
        s = f.read_text(encoding="utf-8")
        total = f.stat().st_size + css + js
        links = re.findall(r'<link[^>]+rel="stylesheet"', s)
        if total > LIMIT:
            problems.append(f"{f}: {total / 1024:.0f} KB over {LIMIT / 1024:.0f} KB")
        if len(links) != 1:
            problems.append(f"{f}: {len(links)} stylesheet links (want 1)")
        if "<style" in s and "developers" not in f.parts:
            problems.append(f"{f}: inline <style> present")
        html_kb = f.stat().st_size / 1024
        print(f"{f}: {total / 1024:.0f} KB (html {html_kb:.0f}, css {css / 1024:.0f}, js {js / 1024:.0f})")
    if fonts > FONT_LIMIT:
        problems.append(f"fonts {fonts / 1024:.0f} KB over {FONT_LIMIT / 1024:.0f} KB")
    print(f"fonts {fonts / 1024:.0f} KB")
    print("\n".join(problems) or "budget ok")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
