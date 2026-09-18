"""Regenerate docs/og.png, the 1200x630 card that Discord, Slack and X show when the link is pasted.

Needs three packages that are not runtime dependencies: `pip install Pillow fonttools brotli`. fonttools converts
the shipped Geist variable woff2 to a ttf that Pillow can open, so the card uses the same face as the site.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
W, H = 1200, 630
BG, INK, BODY, LINE, MUTED = "#FAFAFA", "#111113", "#3F3F46", "#E4E4E7", "#71717A"
TITLE = "jevmod"
SUBTITLE = "Content moderation with a probability per category."


def geist(size: int, weight: int) -> ImageFont.FreeTypeFont:
    src = ROOT / "docs" / "fonts" / "Geist-Variable.woff2"
    f = TTFont(src, fontNumber=0)
    buf = io.BytesIO()
    f.flavor = None  # drop the woff2 wrapper; Pillow reads plain ttf
    f.save(buf)
    buf.seek(0)
    font = ImageFont.truetype(buf, size)
    with contextlib.suppress(OSError):  # a static build of the face has no axes
        font.set_variation_by_axes([weight])
    return font


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=LINE)

    d.text((100, 190), TITLE, font=geist(112, 700), fill=INK)
    d.text((100, 334), SUBTITLE, font=geist(34, 400), fill=BODY)
    small = geist(24, 400)
    d.text((100, 536), "jevmod.dev", font=small, fill=MUTED)
    right = "MIT"
    d.text((W - 100 - d.textlength(right, font=small), 536), right, font=small, fill=MUTED)

    mark = Image.open(ROOT / "brand" / "jevmod-icon-128.png").convert("RGB")
    img.paste(mark, (W - 100 - mark.width, 96))

    out = ROOT / "docs" / "og.png"
    img.save(out, optimize=True)
    print(f"wrote {out.relative_to(ROOT)}, {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
