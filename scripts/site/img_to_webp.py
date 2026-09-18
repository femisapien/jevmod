"""PNG -> WebP under a size budget, dimensions untouched.

    python scripts/site/img_to_webp.py docs/img/log-flag.png            # writes docs/img/log-flag.webp
    python scripts/site/img_to_webp.py in.png --out out.webp --max-kb 200

Lowers the WebP quality in steps until the file fits (default 200 KB). Never resizes: the pages reference each
image at an exact pixel size (1600x1000, 1600x1200, 1600x600, 2400x1400), so a mismatch there is a bug, not a
compression job. Requires Pillow (`pip install pillow`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

QUALITIES = (92, 88, 84, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30)


def to_webp(src: Path, dst: Path | None = None, max_kb: int = 200) -> tuple[Path, int, int]:
    """Convert `src` to WebP at `dst` (default: same name, .webp). Returns (path, bytes, quality used)."""
    from PIL import Image

    dst = dst or src.with_suffix(".webp")
    with Image.open(src) as im:
        size = im.size
        rgb = im.convert("RGB")  # the captures are opaque; dropping alpha shaves bytes and avoids a grey fringe
    limit = max_kb * 1024
    used = QUALITIES[-1]
    for q in QUALITIES:
        rgb.save(dst, "WEBP", quality=q, method=6)
        used = q
        if dst.stat().st_size <= limit:
            break
    with Image.open(dst) as out:
        if out.size != size:
            raise RuntimeError(f"{dst}: size changed {size} -> {out.size}")
    return dst, dst.stat().st_size, used


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max-kb", type=int, default=200)
    a = ap.parse_args(argv)
    dst, n, q = to_webp(a.src, a.out, a.max_kb)
    ok = n <= a.max_kb * 1024
    print(f"{dst}  {n / 1024:.1f} KB  quality={q}  {'ok' if ok else 'STILL OVER BUDGET'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
