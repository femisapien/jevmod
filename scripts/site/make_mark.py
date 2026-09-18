"""Draw the jevmod mark without any image library: signed distance fields, then a hand-written PNG.

The mark is a lowercase j, the wordmark's first letter, with its dot in the flag red the site uses for a
message that crossed its line. Geometry only, so it stays sharp at any size and needs no font file.
"""

import math
import struct
import zlib
from pathlib import Path

BG = (0xFA, 0xFA, 0xFA)
INK = (0x11, 0x11, 0x13)
FLAG = (0xDC, 0x26, 0x26)

STROKE = 50.0
DOT_R = 27.0
DOT = (290.0, 126.0)
STEM_TOP = (290.0, 196.0)
STEM_BOT = (290.0, 300.0)
ARC_C = (232.0, 300.0)
ARC_R = 58.0  # == STEM x - ARC_C x, so the stem flows into the hook with no step
ARC_A0, ARC_A1 = 0.0, 128.0


def d_circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


def d_segment(px, py, ax, ay, bx, by, half):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    t = 0.0 if (vx * vx + vy * vy) == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy)))
    return math.hypot(wx - t * vx, wy - t * vy) - half


def d_arc(px, py, cx, cy, r, a0, a1, half):
    ang = math.degrees(math.atan2(py - cy, px - cx)) % 360.0
    if a0 <= ang <= a1:
        return abs(math.hypot(px - cx, py - cy) - r) - half
    e0 = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
    e1 = (cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1)))
    return min(math.hypot(px - e0[0], py - e0[1]), math.hypot(px - e1[0], py - e1[1])) - half


def coverage(d, aa):
    """1 inside, 0 outside, a smooth ramp of one pixel across the edge."""
    return min(1.0, max(0.0, 0.5 - d / aa))


def render(size: int, fit: tuple[float, float, float]) -> bytes:
    """`fit` is (scale, tx, ty): model coordinates are scaled about the origin, then translated."""
    k, tx, ty = fit
    s = 512.0 / size / k
    aa = 1.4 * s
    ox, oy = tx / k, ty / k
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter: none
        py = (y + 0.5) * s - oy
        for x in range(size):
            px = (x + 0.5) * s - ox
            ink = max(
                coverage(d_segment(px, py, *STEM_TOP, *STEM_BOT, STROKE / 2), aa),
                coverage(d_arc(px, py, *ARC_C, ARC_R, ARC_A0, ARC_A1, STROKE / 2), aa),
            )
            red = coverage(d_circle(px, py, *DOT, DOT_R), aa)
            r, g, b = BG
            r = r + (INK[0] - r) * ink
            g = g + (INK[1] - g) * ink
            b = b + (INK[2] - b) * ink
            r = r + (FLAG[0] - r) * red
            g = g + (FLAG[1] - g) * red
            b = b + (FLAG[2] - b) * red
            rows += bytes((round(r), round(g), round(b)))
    return bytes(rows)


def png(path: Path, size: int, raw: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    )


def fit_to_circle(diameter: float = 372.0) -> tuple[float, float, float]:
    """Scale the mark so its bounding box fits a circle of that diameter, then centre it in the square."""
    xs = [DOT[0] - DOT_R, STEM_TOP[0] - STROKE / 2]
    ys = [DOT[1] - DOT_R, STEM_TOP[1] - STROKE / 2]
    for a in range(int(ARC_A0), int(ARC_A1) + 1):
        xs.append(ARC_C[0] + ARC_R * math.cos(math.radians(a)))
        ys.append(ARC_C[1] + ARC_R * math.sin(math.radians(a)))
    lo_x, hi_x = min(xs) - STROKE / 2, max(xs) + STROKE / 2
    lo_y, hi_y = min(ys) - STROKE / 2, max(ys) + STROKE / 2
    w, h = hi_x - lo_x, hi_y - lo_y
    k = diameter / math.hypot(w, h)
    cx, cy = (lo_x + hi_x) / 2, (lo_y + hi_y) / 2
    return k, 256.0 - cx * k, 256.0 - cy * k


off = fit_to_circle()
out = Path(r"C:\Projects\jev-mod\brand")
out.mkdir(exist_ok=True)
for n in (512, 256, 128, 64, 32):
    png(out / f"jevmod-icon-{n}.png", n, render(n, off))
    print("wrote", n)


def ico(path: Path, sizes: tuple[int, ...] = (16, 32, 48, 64)) -> None:
    """A .ico whose entries are whole PNGs, which every browser since IE 11 reads."""
    fit = fit_to_circle()
    blobs = []
    for n in sizes:
        tmp = path.with_suffix(f".{n}.png")
        png(tmp, n, render(n, fit))
        blobs.append(tmp.read_bytes())
        tmp.unlink()
    offset = 6 + 16 * len(sizes)
    head = struct.pack("<HHH", 0, 1, len(sizes))
    entries = b""
    for n, blob in zip(sizes, blobs, strict=True):
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(head + entries + b"".join(blobs))
    print("wrote ico")


def svg(path: Path) -> None:
    """The same geometry as vector, so the mark can be resized without re-rendering."""
    k, tx, ty = fit_to_circle()
    a1 = math.radians(ARC_A1)
    end = (ARC_C[0] + ARC_R * math.cos(a1), ARC_C[1] + ARC_R * math.sin(a1))
    ink, flag, bg = (f"#{r:02X}{g:02X}{b:02X}" for r, g, b in (INK, FLAG, BG))
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="jevmod">\n'
        f'  <rect width="512" height="512" fill="{bg}"/>\n'
        f'  <g transform="translate({tx:.2f} {ty:.2f}) scale({k:.4f})">\n'
        f'    <path d="M {STEM_TOP[0]:.1f} {STEM_TOP[1]:.1f} L {STEM_BOT[0]:.1f} {STEM_BOT[1]:.1f} '
        f'A {ARC_R:.1f} {ARC_R:.1f} 0 0 1 {end[0]:.2f} {end[1]:.2f}" fill="none" stroke="{ink}" '
        f'stroke-width="{STROKE:.1f}" stroke-linecap="round"/>\n'
        f'    <circle cx="{DOT[0]:.1f}" cy="{DOT[1]:.1f}" r="{DOT_R:.1f}" fill="{flag}"/>\n'
        f"  </g>\n</svg>\n",
        encoding="utf-8",
    )
    print("wrote svg")


svg(out / "jevmod-mark.svg")

# The site uses the same mark, so the tab icon and the Discord avatar are one thing.
docs = Path(__file__).resolve().parents[2] / "docs"
if docs.is_dir():
    svg(docs / "favicon.svg")
    ico(docs / "favicon.ico")
