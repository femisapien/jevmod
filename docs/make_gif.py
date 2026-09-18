"""Render docs/jevmod.gif: a terminal recording of `jevmod check` and the HTTP API, drawn frame by frame with Pillow.

python docs/make_gif.py            # needs Pillow (pip install pillow); writes docs/jevmod.gif

Every output line below was pasted from a real run on 2026-09-18 (jevmod 0.2, default thresholds, TYPESAFE_API_KEY
in the environment). Jev's probabilities move about +-0.03 between runs, so a re-run will not match to the digit.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "jevmod.gif"
W, H = 920, 590
BG = (17, 19, 24)
BAR = (30, 33, 40)
FG = (220, 223, 228)
DIM = (120, 126, 140)
GREEN = (47, 191, 131)
RED = (240, 110, 110)
YELLOW = (240, 196, 84)
FONT = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 22)
LINE_H = 30
PAD = 18
MAX_COLS = 70  # readable when the GIF is shown 570 px wide

Line = tuple[str, tuple[int, int, int]]

# --- real output, verbatim -------------------------------------------------------------------------------------
CMD1 = 'jevmod check "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"'
OUT1 = "scam 0.99                    'FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro'  [scam 0.99, spam 0.98, harassment 0.02]"
CMD2 = "jevmod check - < comments.txt"
OUT2 = [
    ("skipped (too short)          'gg wp'  []", DIM),
    ("ok                           'Sub to my channel visuelgamingzNL I sub back'  [spam 0.80, scam 0.09, doxxing 0.03]", FG),
    ("harassment 0.98              'The world would be better off without immigrants like you.'  [harassment 0.98, spam 0.03, nsfw 0.02]", RED),
    ("ok                           'Anyone know if the patch fixed the inventory bug?'  [spam 0.01, scam 0.01, harassment 0.01]", FG),
]
CMD3 = 'curl -s localhost:8080/v1/moderate -H "Authorization: Bearer $JEVMOD_KEY" -d @batch.json'
# the two decision objects from the real response (request_id and usage lines left out for space)
OUT3 = [
    ('{"message_id":"a","action":"flag","category":"scam","probability":0.99,"scores":{"spam":0.97,"scam":0.99,"harassment":0.02,"nsfw":0.01,"selfharm":0.01,"doxxing":0.02,"minors":0.01},"judged":true,"reason":"jev"}', RED),
    ('{"message_id":"b","action":"none","category":null,"probability":0.0,"scores":{"spam":0.02,"scam":0.02,"harassment":0.01,"nsfw":0.01,"selfharm":0.01,"doxxing":0.01,"minors":0.01},"judged":true,"reason":"jev"}', GREEN),
]


def wrap(text: str, color: tuple[int, int, int]) -> list[Line]:
    out: list[Line] = []
    while len(text) > MAX_COLS:
        cut = max(text.rfind(" ", 0, MAX_COLS), text.rfind(",", 0, MAX_COLS) + 1)
        cut = cut if cut > 30 else MAX_COLS
        out.append((text[:cut], color))
        text = "    " + text[cut:].lstrip()
    out.append((text, color))
    return out


def frame(lines: list[Line]) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 34), fill=BAR)
    d.text((PAD, 4), "jevmod", fill=DIM, font=FONT)
    y = 34 + PAD
    for text, color in lines[-((H - 34 - 2 * PAD) // LINE_H) :]:
        d.text((PAD, y), text, fill=color, font=FONT)
        y += LINE_H
    return img


def build() -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    lines: list[Line] = []

    def add(ls: list[Line], ms: int) -> None:
        frames.append(frame(list(ls)))
        durations.append(ms)

    def type_cmd(cmd: str) -> None:
        nonlocal lines
        for k in range(1, len(cmd) + 1):
            add(lines + wrap("$ " + cmd[:k], FG), 14)
        lines = lines + wrap("$ " + cmd, FG)
        add(lines, 500)

    def output(ls: list[Line], per_line_ms: int = 220, hold_ms: int = 1600) -> None:
        nonlocal lines
        for text, color in ls:
            lines = lines + wrap(text, color)
            add(lines, per_line_ms)
        add(lines, hold_ms)

    add([("$ ", FG)], 400)

    type_cmd(CMD1)
    output([(OUT1, RED)], hold_ms=1200)
    type_cmd("echo $?")
    output([("1", DIM), ("", FG)], hold_ms=700)

    type_cmd(CMD2)
    output(OUT2, hold_ms=1500)
    lines = lines + [("", FG)]

    type_cmd(CMD3)
    output(OUT3, per_line_ms=300, hold_ms=1800)
    lines = lines + [("", FG), ("one Jev request per batch. probabilities, not prose.", GREEN)]
    add(lines, 2400)

    # open on the finished screen so the first frame already shows results, then replay from the start
    frames.insert(0, frames[-1])
    durations.insert(0, 1200)

    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(OUT, f"{OUT.stat().st_size / 1e6:.2f} MB", len(frames), "frames", f"{sum(durations) / 1000:.1f} s")


if __name__ == "__main__":
    build()
