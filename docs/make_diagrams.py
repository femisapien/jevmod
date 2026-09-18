"""Write the four SVG diagrams in docs/diagrams/ (light background, monochrome, readable at 800 px wide).

python docs/make_diagrams.py     # no dependencies: the SVG is written as text

architecture.svg  channels -> ModerationService -> Judge -> Jev, store on the side
flow.svg          one message through prefilter, cache, batch, Jev, policy, action, audit log; fail-open branch
coverage.svg      categories and custom rules x surfaces
failure.svg       what happens when Jev is down or the optional monthly quota is reached
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "diagrams"
BG, BG2, LINE, LINE2 = "#FAFAFA", "#FFFFFF", "#E5E5E5", "#D4D4D8"
FG, FG2, FG3, ACCENT, ACCENT_DIM = "#0A0A0A", "#3F3F46", "#71717A", "#0A0A0A", "#A1A1AA"
SANS = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'IBM Plex Mono', Consolas, 'SF Mono', Menlo, monospace"


class Svg:
    def __init__(self, w: int, h: int, title: str) -> None:
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="{SANS}" role="img" aria-label="{title}">',
            f"<title>{title}</title>",
            "<defs>"
            f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{FG3}"/></marker>'
            f'<marker id="arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{ACCENT}"/></marker>'
            "</defs>",
            f'<rect width="{w}" height="{h}" fill="{BG}"/>',
        ]

    def text(
        self,
        x: float,
        y: float,
        s: str,
        size: int = 15,
        fill: str = FG,
        mono: bool = False,
        weight: str = "400",
        anchor: str = "start",
    ) -> None:
        fam = MONO if mono else SANS
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{s}</text>'
        )

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        sub: str = "",
        lines: list[str] | None = None,
        hot: bool = False,
        mono_title: bool = False,
        dashed: bool = False,
    ) -> None:
        stroke = ACCENT if hot else LINE2
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="0" fill="{BG2}" stroke="{stroke}" stroke-width="{2 if hot else 1}"{dash}/>'
        )
        ty = y + 24
        if sub:
            self.text(x + 16, ty, sub, 12, FG3, mono=True)
            ty += 22
        self.text(x + 16, ty, title, 16, FG, mono=mono_title, weight="600")
        ty += 24
        for ln in lines or []:
            self.text(x + 16, ty, ln, 13, FG2)
            ty += 19

    def pill(self, x: float, y: float, w: float, label: str, hot: bool = False) -> None:
        stroke = ACCENT if hot else LINE2
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="34" rx="0" fill="{BG2}" stroke="{stroke}" stroke-width="{2 if hot else 1}"/>'
        )
        self.text(x + w / 2, y + 22, label, 14, FG, mono=True, anchor="middle")

    def arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        accent: bool = False,
        dashed: bool = False,
        label: str = "",
        label_dy: float = -8,
    ) -> None:
        col = ACCENT if accent else FG3
        m = "arrow-accent" if accent else "arrow"
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="1.5" marker-end="url(#{m})"{dash}/>'
        )
        if label:
            self.text((x1 + x2) / 2, (y1 + y2) / 2 + label_dy, label, 12, FG3, mono=True, anchor="middle")

    def path(self, d: str, accent: bool = False, dashed: bool = False, arrow: bool = True) -> None:
        col = ACCENT if accent else FG3
        m = "arrow-accent" if accent else "arrow"
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        end = f' marker-end="url(#{m})"' if arrow else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.5"{dash}{end}/>')

    def hline(self, x1: float, x2: float, y: float) -> None:
        self.parts.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{LINE}" stroke-width="1"/>')

    def write(self, name: str) -> None:
        self.parts.append("</svg>")
        p = OUT / name
        p.write_text("\n".join(self.parts) + "\n", encoding="utf-8")
        print(p, f"{p.stat().st_size / 1e3:.1f} KB")


def architecture() -> None:
    s = Svg(1000, 560, "jevmod architecture: channels, ModerationService, Judge, Jev, and the local store")
    s.text(32, 40, "architecture", 13, FG3, mono=True)
    s.text(
        32, 68, "Every surface is an adapter over one service. Only the text and the channel topic reach Jev.", 15, FG2
    )

    # channels, two columns of four
    s.text(32, 118, "channels", 12, FG3, mono=True)
    chans = [
        ("Discord", "bot"),
        ("Telegram", "bot"),
        ("Reddit", "bot"),
        ("CLI", "jevmod check"),
        ("Python", "Moderator"),
        ("npm", "check()"),
        ("HTTP", "POST /v1/moderate"),
        ("MCP", "moderate, categories"),
    ]
    for i, (name, how) in enumerate(chans):
        col, row = i // 4, i % 4
        x, y = 32 + col * 150, 132 + row * 62
        s.parts.append(
            f'<rect x="{x}" y="{y}" width="136" height="50" rx="0" fill="{BG2}" stroke="{LINE2}" stroke-width="1.5"/>'
        )
        s.text(x + 12, y + 21, name, 14, FG, weight="600")
        s.text(x + 12, y + 39, how, 11, FG3, mono=True)
    # arrows from channel block to service
    s.arrow(322, 254, 376, 254)

    s.box(
        380,
        176,
        230,
        156,
        "ModerationService",
        "jevmod.core",
        [
            "policy per server or tenant",
            "thresholds, actions, rules",
            "trusted roles, channel topic",
            "usage and quota",
        ],
        hot=True,
    )
    s.arrow(614, 254, 668, 254)
    s.box(
        672,
        176,
        150,
        156,
        "Judge",
        "jevmod.judge",
        [
            "normalise text",
            "prefilter, cache",
            "batch of messages",
            "one request",
        ],
    )
    s.arrow(826, 254, 880, 254)
    s.box(884, 200, 92, 108, "Jev", "TypeSafe", ["System One", "model, HTTP"], hot=True)

    # store on the side
    s.path("M495,336 L495,372", arrow=True)
    s.box(
        380,
        376,
        230,
        96,
        "Store",
        "SQLite on a volume",
        [
            "policy, usage, audit log",
            "300 chars of text, 30 days",
        ],
    )
    s.text(
        32,
        520,
        "categories.json holds the questions asked of Jev, so Python, npm and MCP ask exactly the same thing.",
        13,
        FG3,
    )
    s.write("architecture.svg")


def flow() -> None:
    s = Svg(
        1000,
        500,
        "jevmod request flow: prefilter, cache, batch, one Jev request, probabilities, policy, action, audit log",
    )
    s.text(32, 40, "request flow", 13, FG3, mono=True)
    s.text(
        32,
        68,
        "What happens to one message. Anything the prefilter or the cache answers never leaves the machine.",
        15,
        FG2,
    )

    def node(x: float, y: float, w: float, title: str, sub: str, hot: bool = False, dashed: bool = False) -> None:
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        fill = BG if dashed else BG2
        s.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="64" rx="0" fill="{fill}" stroke="{ACCENT if hot else LINE2}" stroke-width="{2 if hot else 1}"{dash}/>'
        )
        s.text(x + 14, y + 26, title, 15, FG, weight="600")
        s.text(x + 14, y + 47, sub, 11.5, FG3, mono=True)

    # row 1, left to right
    y1 = 104
    row1 = [
        (32, 140, "message", "text, topic"),
        (194, 176, "prefilter", "8+ letters, untrusted"),
        (392, 150, "cache", "same text, reuse"),
        (564, 160, "batch", "2 s, up to 50 msgs"),
        (746, 190, "one Jev request", "all enabled categories"),
    ]
    for i, (x, w, t, sub) in enumerate(row1):
        node(x, y1, w, t, sub, hot=(t == "one Jev request"))
        if i < len(row1) - 1:
            s.arrow(x + w + 4, y1 + 32, row1[i + 1][0] - 4, y1 + 32)

    # row 2, the two branches
    y2 = 230
    s.path(f"M282,{y1 + 64} L282,{y2 - 4}", dashed=True)
    s.path(f"M467,{y1 + 64} L467,{y2 - 4}", dashed=True)
    node(32, y2, 440, "not sent to Jev", "under 8 letters and no link, trusted author, repeat", dashed=True)
    s.path(f"M841,{y1 + 64} L841,{y2 - 4}", dashed=True, accent=True)
    s.parts.append(
        f'<rect x="500" y="{y2}" width="436" height="64" rx="0" fill="{BG}" stroke="{ACCENT}" stroke-width="1.5" stroke-dasharray="6 5"/>'
    )
    s.text(514, y2 + 26, "Jev unreachable: fail open", 15, FG, weight="600")
    s.text(514, y2 + 47, 'action none, reason "error_open", one warning per batch', 11.5, FG3, mono=True)

    # row 3, right to left (the answer comes back down the right edge)
    y3 = 356
    row3 = [
        (746, 190, "probabilities", "one per category"),
        (554, 170, "policy", "thresholds, rules"),
        (342, 190, "action", "flag, delete, timeout"),
        (140, 180, "audit log", "probabilities + action"),
    ]
    s.path(f"M936,{y1 + 32} L968,{y1 + 32} L968,{y3 + 32} L940,{y3 + 32}", arrow=True)
    for i, (x, w, t, sub) in enumerate(row3):
        node(x, y3, w, t, sub, hot=(t == "probabilities"))
        if i < len(row3) - 1:
            nx, nw = row3[i + 1][0], row3[i + 1][1]
            s.arrow(x - 4, y3 + 32, nx + nw + 4, y3 + 32)

    s.text(
        32,
        462,
        "Measured on the benchmark: about 1,005 input tokens per judged message, $0.042 per 1,000 judged messages, 22 ms per message in batches of 25.",
        13,
        FG3,
    )
    s.write("flow.svg")


def coverage() -> None:
    surfaces = ["Discord", "Telegram", "Reddit", "CLI", "Python", "npm", "HTTP", "MCP"]
    cats = [
        ("spam", "flag 0.85"),
        ("scam", "flag 0.75"),
        ("harassment", "flag 0.75"),
        ("nsfw", "flag 0.80"),
        ("offtopic", "off, needs topic"),
        ("selfharm", "flag 0.80, never punish"),
        ("doxxing", "flag 0.80"),
        ("minors", "flag 0.70"),
        ("rule:<name>", "flag 0.80, up to 5"),
    ]
    x0, y0, cw, rh = 262, 132, 88, 34
    w = x0 + cw * len(surfaces) + 32
    h = y0 + rh * len(cats) + 70
    s = Svg(w, h, "jevmod coverage: eight categories and custom rules on every surface")
    s.text(32, 40, "coverage", 13, FG3, mono=True)
    s.text(
        32,
        68,
        "One set of questions (categories.json) on every surface. Default action and threshold in the second column.",
        15,
        FG2,
    )
    for j, name in enumerate(surfaces):
        s.text(x0 + j * cw + cw / 2, y0 - 12, name, 13, FG2, mono=True, anchor="middle")
    for i, (cat, default) in enumerate(cats):
        y = y0 + i * rh
        s.hline(32, w - 32, y)
        s.text(32, y + 22, cat, 14, FG, mono=True, weight="500")
        s.text(126, y + 22, default, 11.5, FG3, mono=True)
        for j in range(len(surfaces)):
            cx = x0 + j * cw + cw / 2
            if cat == "offtopic":
                s.parts.append(
                    f'<rect x="{cx - 6}" y="{y + 11}" width="12" height="12" rx="0" fill="none" stroke="{ACCENT}" stroke-width="1.5"/>'
                )
            else:
                s.parts.append(f'<rect x="{cx - 6}" y="{y + 11}" width="12" height="12" rx="0" fill="{ACCENT}"/>')
    s.hline(32, w - 32, y0 + rh * len(cats))
    ly = y0 + rh * len(cats) + 34
    s.parts.append(f'<rect x="32" y="{ly - 10}" width="12" height="12" rx="0" fill="{ACCENT}"/>')
    s.text(52, ly, "on by default", 12, FG3)
    s.parts.append(
        f'<rect x="160" y="{ly - 10}" width="12" height="12" rx="0" fill="none" stroke="{ACCENT}" stroke-width="1.5"/>'
    )
    s.text(180, ly, "available, off until a channel topic is set", 12, FG3)
    s.write("coverage.svg")


def failure() -> None:
    s = Svg(
        1000, 330, "jevmod failure policy: Jev down means fail open; optional quota reached means pause and notify once"
    )
    s.text(32, 40, "failure policy", 13, FG3, mono=True)
    s.text(32, 68, "Two things can go wrong. In neither case is a message deleted.", 15, FG2)

    def lane(y: int, trigger: str, tsub: str, steps: list[tuple[str, str]]) -> None:
        s.parts.append(
            f'<rect x="32" y="{y}" width="200" height="64" rx="0" fill="{BG2}" stroke="{ACCENT}" stroke-width="1.5"/>'
        )
        s.text(46, y + 26, trigger, 15, FG, weight="600")
        s.text(46, y + 47, tsub, 11.5, FG3, mono=True)
        x = 232
        for title, sub in steps:
            s.arrow(x + 4, y + 32, x + 36, y + 32)
            x += 40
            s.parts.append(
                f'<rect x="{x}" y="{y}" width="200" height="64" rx="0" fill="{BG2}" stroke="{LINE2}" stroke-width="1.5"/>'
            )
            s.text(x + 14, y + 26, title, 15, FG, weight="600")
            s.text(x + 14, y + 47, sub, 11.5, FG3, mono=True)
            x += 200

    lane(
        104,
        "Jev unreachable",
        "timeout, 5xx, network",
        [
            ("fail open", 'reason "error_open"'),
            ("nothing acted on", "action none"),
            ("one warning per batch", "log channel or stderr"),
        ],
    )
    lane(
        208,
        "monthly quota reached",
        "JEVMOD_MONTHLY_QUOTA",
        [
            ("judging pauses", "messages pass untouched"),
            ("owner told once", "not on every message"),
            ("off by default", "0 = unlimited"),
        ],
    )
    s.text(
        32,
        306,
        "Retries: 429 and 529 from Jev are retried with exponential backoff and Retry-After before a batch is declared failed.",
        13,
        FG3,
    )
    s.write("failure.svg")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    architecture()
    flow()
    coverage()
    failure()
