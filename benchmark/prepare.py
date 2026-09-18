"""Unify three public sets into benchmark/data/items.jsonl with jevmod category labels.

- OpenAI moderation eval (samples-1680): S→nsfw, S3→minors, H/HR/V→harassment, V2→nsfw, SH→selfharm.
- Civil Comments (Jigsaw): toxicity>=0.7 → harassment; toxicity<=0.1 → clean.
- YouTube Spam Collection (UCI): CLASS=1 → spam.

Labels are the sets the sources give; a message can carry several. `clean` means no label from that source.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

DATA = Path(__file__).parent / "data"
OPENAI_MAP = {
    "S": "nsfw",
    "S3": "minors",
    "H": "harassment",
    "HR": "harassment",
    "V": "harassment",
    "V2": "nsfw",
    "SH": "selfharm",
}


def openai_items() -> list[dict]:
    out = []
    for i, line in enumerate((DATA / "openai_moderation.jsonl").open(encoding="utf-8")):
        r = json.loads(line)
        labels = sorted({OPENAI_MAP[k] for k, v in r.items() if k in OPENAI_MAP and v == 1})
        out.append({"id": f"oai{i}", "source": "openai_moderation", "text": r["prompt"], "labels": labels})
    return out


def civil_items() -> list[dict]:
    out = []
    for i, line in enumerate((DATA / "civil_comments.jsonl").open(encoding="utf-8")):
        r = json.loads(line)
        labels = ["harassment"] if r["toxicity"] >= 0.7 else []
        out.append({"id": f"cc{i}", "source": "civil_comments", "text": r["text"], "labels": labels})
    return out


def youtube_items(n_per_class: int = 250) -> list[dict]:
    rows = []
    for f in sorted((DATA / "youtube_spam").glob("Youtube*.csv")):
        with f.open(encoding="utf-8", errors="replace") as fh:
            rows += list(csv.DictReader(fh))
    random.Random(0).shuffle(rows)
    spam = [r for r in rows if r["CLASS"] == "1"][:n_per_class]
    ham = [r for r in rows if r["CLASS"] == "0"][:n_per_class]
    return [
        {
            "id": f"yt{i}",
            "source": "youtube_spam",
            "text": r["CONTENT"],
            "labels": ["spam"] if r["CLASS"] == "1" else [],
        }
        for i, r in enumerate(spam + ham)
    ]


def main() -> None:
    items = openai_items() + civil_items() + youtube_items()
    with (DATA / "items.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    from collections import Counter

    c = Counter((it["source"], lab) for it in items for lab in (it["labels"] or ["clean"]))
    for k, v in sorted(c.items()):
        print(f"{k[0]:<18} {k[1]:<11} {v}")
    print(len(items), "items")


if __name__ == "__main__":
    main()
