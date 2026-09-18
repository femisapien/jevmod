"""Quality and cost table: jevmod vs Llama Guard 3 8B vs ShieldGemma 2B vs toxic-bert on the same items.

Per (source, category): AUROC (threshold-free) and F1 at the system's own default threshold. For Llama Guard, the
category is what the model named (a hard label) plus p(unsafe) for the AUROC of "flagged at all".
Cost: Jev at list price from measured tokens; local models at an RTX 5080's electricity + amortisation
(~0.30 $/h → per-message from measured latency); Claude Haiku from list price on the same token counts (not run).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

R = Path(__file__).parent / "results"
DATA = Path(__file__).parent / "data" / "items.jsonl"
JEV_USD_PER_M = 0.042
GPU_USD_PER_H = 0.30
DEFAULT = {"spam": 0.85, "harassment": 0.75, "nsfw": 0.8, "selfharm": 0.8, "doxxing": 0.8, "minors": 0.7, "scam": 0.75}


def load(name: str) -> dict[str, dict]:
    p = R / f"{name}.jsonl"
    return {json.loads(line)["id"]: json.loads(line) for line in p.open(encoding="utf-8")} if p.exists() else {}


def auroc(pairs: list[tuple[float, int]]) -> float | None:
    pos = [s for s, y in pairs if y]
    neg = [s for s, y in pairs if not y]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def f1(pairs: list[tuple[float, int]], th: float) -> tuple[float, float, float]:
    tp = sum(1 for s, y in pairs if y and s >= th)
    fp = sum(1 for s, y in pairs if not y and s >= th)
    fn = sum(1 for s, y in pairs if y and s < th)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return (2 * prec * rec / (prec + rec) if prec + rec else 0.0, prec, rec)


def best_f1(pairs: list[tuple[float, int]]) -> tuple[float, float]:
    best = (0.0, 0.5)
    for th in [i / 100 for i in range(5, 100, 5)]:
        f = f1(pairs, th)[0]
        if f > best[0]:
            best = (f, th)
    return best


def main() -> None:
    items = {json.loads(line)["id"]: json.loads(line) for line in DATA.open(encoding="utf-8")}
    jev, lg, sg, tb = load("jevmod"), load("llamaguard"), load("shieldgemma"), load("toxicbert")
    systems: dict[str, dict[str, dict[str, float]]] = {
        "jevmod": {},
        "llamaguard": {},
        "shieldgemma": {},
        "toxicbert": {},
    }
    for i, r in jev.items():
        systems["jevmod"][i] = r["scores"] if r["judged"] else {c: 0.0 for c in DEFAULT}
    for i, r in lg.items():
        s = {c: 0.0 for c in DEFAULT}
        for c in r["labels"]:
            s[c] = r["p_unsafe"]
        s["any"] = r["p_unsafe"]
        systems["llamaguard"][i] = s
    for i, r in sg.items():
        systems["shieldgemma"][i] = {
            "harassment": max(r["scores"]["harassment"], r["scores"]["hate"]),
            "nsfw": r["scores"]["sexual"],
            "any": max(r["scores"].values()),
        }
    for i, r in tb.items():
        s = r["scores"]
        systems["toxicbert"][i] = {
            "harassment": max(s.get("toxic", 0), s.get("insult", 0), s.get("threat", 0), s.get("identity_hate", 0)),
            "nsfw": s.get("obscene", 0),
            "any": s.get("toxic", 0),
        }
    for i, r in jev.items():
        systems["jevmod"][i]["any"] = max(systems["jevmod"][i].values()) if systems["jevmod"][i] else 0.0

    rows = []
    for source in ("openai_moderation", "civil_comments", "youtube_spam"):
        ids = [i for i, it in items.items() if it["source"] == source]
        cats = sorted({lab for i in ids for lab in items[i]["labels"]}) + ["any"]
        for cat in cats:
            for name, sc in systems.items():
                have = [i for i in ids if i in sc and cat in sc[i]]
                if len(have) < len(ids) * 0.9:
                    continue
                pairs = [
                    (sc[i][cat], int(cat in items[i]["labels"] or (cat == "any" and bool(items[i]["labels"]))))
                    for i in have
                ]
                a = auroc(pairs)
                th = DEFAULT.get(cat, 0.5) if name == "jevmod" else 0.5
                f, p, rcl = f1(pairs, th)
                bf, bth = best_f1(pairs)
                rows.append((source, cat, name, len(have), a, f, p, rcl, bf, bth))

    print("| set | category | system | n | AUROC | F1@default | P | R | best F1 (th) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for source, cat, name, n, a, f, p, rcl, bf, bth in rows:
        print(
            f"| {source} | {cat} | {name} | {n} | {a:.3f} | {f:.3f} | {p:.2f} | {rcl:.2f} | {bf:.3f} ({bth:.2f}) |"
            if a is not None
            else f"| {source} | {cat} | {name} | {n} | n/a | | | | |"
        )

    # cost and latency
    print("\n| system | messages | measured | cost / 1,000 msgs | latency / msg |")
    print("|---|---|---|---|---|")
    if jev:
        toks = sum(r["batch_tokens"] / r["batch_n"] for r in jev.values() if r["judged"])
        judged = sum(1 for r in jev.values() if r["judged"])
        ms = sum(r["batch_ms"] / r["batch_n"] for r in jev.values() if r["judged"]) / max(judged, 1)
        print(
            f"| jevmod (Jev, 7 categories) | {judged} | {toks:,.0f} input tokens | ${toks / judged * 1000 * JEV_USD_PER_M / 1e6:.4f} | {ms:.0f} ms (batched 25) |"
        )
    for name, label in (
        ("llamaguard", "Llama Guard 3 8B Q4_K_M (RTX 5080)"),
        ("shieldgemma", "ShieldGemma 2B Q8, 4 policies (RTX 5080)"),
        ("toxicbert", "toxic-bert (RTX 5080)"),
    ):
        d = load(name)
        if d:
            ms = sum(r["ms"] for r in d.values()) / len(d)
            print(
                f"| {label} | {len(d)} | {ms:.0f} ms/msg | ${ms / 3600e3 * GPU_USD_PER_H * 1000:.4f} (GPU time at $0.30/h) | {ms:.0f} ms |"
            )
    if jev:
        print(
            f"| Claude Haiku 4.5 as judge (list price, not run) | | same text + prompt ~{toks / judged * 1.2:,.0f} tokens | ${toks / judged * 1.2 * 1000 * 1.0 / 1e6 + 0.02:.4f} | ~1,500 ms |"
        )


if __name__ == "__main__":
    main()
