"""Does the slop rule survive an adversarial rewrite? RAID answers it without us building a corpus.

REPORT3 shipped `D >= 0.85` on a corpus whose AI side is 2022-era ChatGPT, and left two holes it could not
fill: modern models, and text deliberately rewritten to evade detection. RAID (Dugan et al., 2024,
<https://arxiv.org/abs/2405.07940>) has both: 6.2M generations across 11 models and 8 domains, each one also
published under 11 adversarial attacks, `paraphrase` and `synonym` among them.

RAID labels authorship, not slop, so it cannot say whether the rule is right. It can say the one thing we
need: **how much of the rule survives when the same text is rewritten.** The same generation appears three
times under the same `source_id`, once clean and once per attack, so recall on the clean version and recall
on the attacked version are measured on identical content.

Sampling is pinned to the two domains that read like chat, `reddit` and `reviews`, and to greedy decoding
without a repetition penalty, so each prompt contributes one generation per model rather than four.

    python -m benchmark.ai_detect.raid fetch    # pulls matched triples through the HF datasets server
    python -m benchmark.ai_detect.raid ask      # the only command that spends money
    python -m benchmark.ai_detect.raid report

Nothing here touches `jevmod/` beyond `normalize`, which is how every other text in this benchmark is clipped.
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .features import extract
from .slop import REGISTER, STAGING, questions_d

HERE = Path(__file__).parent
RESULTS = HERE / "results"
CORPUS = RESULTS / "raid.jsonl"
RAW = RESULTS / "raw_D_raid.jsonl"
API = "https://datasets-server.huggingface.co/filter"
DOMAINS = ("reddit", "reviews")
MODELS = ("chatgpt", "gpt4", "human")
ATTACKS = ("none", "paraphrase", "synonym")
PER_CELL = 120  # rows pulled per (attack, model) cell before matching on source_id
MAX_CHARS = 400
BATCH = 25
USD_PER_M = 0.042


def _clip(text: str) -> str:
    """Same treatment every other text in this benchmark gets: normalise, then cut to a chat-sized message."""
    from jevmod.judge import normalize

    t = normalize(text)
    if len(t) <= MAX_CHARS:
        return t
    cut = t[:MAX_CHARS]
    return cut[: cut.rfind(" ")] if " " in cut[300:] else cut


def _get(where: str, limit: int, offset: int) -> dict[str, Any]:
    """One page of the datasets server's filter endpoint, retrying while its index warms up."""
    qs = urllib.parse.urlencode(
        {
            "dataset": "liamdugan/raid",
            "config": "raid",
            "split": "train",
            "where": where,
            "limit": limit,
            "offset": offset,
        }
    )
    # The server answers 500 or a JSON error while it builds the index for a filter it has not seen, and
    # a filter it has never been asked can take several minutes the first time.
    last = ""
    for attempt in range(24):
        try:
            with urllib.request.urlopen(f"{API}?{qs}", timeout=180) as r:
                body = json.load(r)
            if "error" not in body:
                return body
            last = str(body)
        except urllib.error.HTTPError as e:
            if e.code not in (500, 502, 503, 504):
                raise
            last = f"HTTP {e.code}"
        print(f"  index warming up ({last}), retry {attempt + 1}")
        time.sleep(30)
    raise RuntimeError(f"datasets server kept failing: {last}")


def fetch() -> None:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for attack in ATTACKS:
        for model in MODELS:
            where = (
                f"\"attack\"='{attack}' AND \"model\"='{model}' AND \"decoding\"='greedy' "
                f"AND \"repetition_penalty\"='no' "
                f"AND (\"domain\"='{DOMAINS[0]}' OR \"domain\"='{DOMAINS[1]}')"  # the API has no IN
            )
            got = 0
            for offset in range(0, PER_CELL, 100):
                body = _get(where, min(100, PER_CELL - offset), offset)
                for r in body["rows"]:
                    row = r["row"]
                    rows[(row["source_id"], attack)] = row
                    got += 1
                if len(body["rows"]) < 100:
                    break
            print(f"{attack:<12} {model:<8} {got:>4} rows")

    # Keep only sources that exist under all three attacks, so recall is compared on identical content.
    sources = {s for (s, _) in rows}
    complete = [s for s in sources if all((s, a) in rows for a in ATTACKS)]
    complete.sort()
    random.Random(20260919).shuffle(complete)
    print(f"\n{len(complete)} sources present under all of {ATTACKS}")

    out = []
    for s in complete:
        for attack in ATTACKS:
            row = rows[(s, attack)]
            text = _clip(row["generation"])
            if len(text) < 40:  # a stub carries no register either way
                break
            out.append(
                {
                    "id": f"{s[:8]}_{attack}",
                    "source": s,
                    "attack": attack,
                    "model": row["model"],
                    "side": "human" if row["model"] == "human" else "ai",
                    "domain": row["domain"],
                    "text": text,
                }
            )
    CORPUS.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out), encoding="utf-8")
    sides = {s: sum(1 for r in out if r["side"] == s) for s in ("ai", "human")}
    print(f"wrote {len(out)} texts to {CORPUS.name}: {sides}")


def load() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


def regex_fires(text: str) -> bool:
    f = extract(text)
    return sum(f[k] for k in REGISTER) >= 1 or sum(f[k] for k in STAGING) >= 1


def ask() -> None:
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    from jevmod.keys import get_api_key

    items = load()
    # Shuffled, so no batch is all-AI or all-human: REPORT2 measured what sorted batches do to the score.
    random.Random(20260919).shuffle(items)
    done = {json.loads(line)["id"] for line in RAW.open(encoding="utf-8")} if RAW.exists() else set()
    todo = [it for it in items if it["id"] not in done]
    print(f"[raid] {len(todo)} to ask, {len(done)} already done")

    client = TypeSafeClient(
        api_key=get_api_key(),
        retry=RetryPolicy(
            max_retries=3, backoff_initial=0.5, backoff_max=8.0, http_statuses={429, 500, 502, 503, 504, 529}
        ),
        timeout=90.0,
    )
    total = 0
    with RAW.open("a", encoding="utf-8") as fh:
        for start in range(0, len(todo), BATCH):
            chunk = todo[start : start + BATCH]
            state = {"messages": {f"m{i}": {"text": it["text"]} for i, it in enumerate(chunk)}}
            questions = {f"d_{i}": questions_d(f"messages.m{i}")["d"] for i in range(len(chunk))}
            t0 = time.time()
            resp = client.system_one(state=state, questions=questions)
            ms = (time.time() - t0) * 1000
            toks = getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0
            total += toks
            for i, it in enumerate(chunk):
                fh.write(
                    json.dumps({"id": it["id"], "p": float(resp.answers[f"d_{i}"].noul)}, ensure_ascii=False) + "\n"
                )
            fh.flush()
            print(
                f"[raid] {start + len(chunk)}/{len(todo)}  {toks:,} tok  {ms:.0f} ms  "
                f"running {total:,} tok  ${total * USD_PER_M / 1e6:.4f}"
            )


def report() -> None:
    items = load()
    p = {json.loads(line)["id"]: json.loads(line)["p"] for line in RAW.open(encoding="utf-8")}
    items = [it for it in items if it["id"] in p]
    for it in items:
        it["rx"] = regex_fires(it["text"])

    print(f"\n## RAID: does the slop rule survive a rewrite? n={len(items)}\n")
    n_src = len({it["source"] for it in items})
    print(f"{n_src} RAID sources, each under {', '.join(ATTACKS)}, domains {' and '.join(DOMAINS)}, models chatgpt/gpt4.\n")

    print("| side | attack | n | regex fires | D >= 0.7 | D >= 0.85 | D >= 0.9 | mean p |")
    print("|---|---|---|---|---|---|---|---|")
    for side in ("ai", "human"):
        for attack in ATTACKS:
            sub = [it for it in items if it["side"] == side and it["attack"] == attack]
            if not sub:
                continue
            rx = sum(1 for it in sub if it["rx"]) / len(sub)
            cells = " | ".join(f"{sum(1 for it in sub if p[it['id']] >= t) / len(sub):.3f}" for t in (0.7, 0.85, 0.9))
            mean = sum(p[it["id"]] for it in sub) / len(sub)
            print(f"| {side} | {attack} | {len(sub)} | {rx:.3f} | {cells} | {mean:.3f} |")

    # The question: on the SAME source, does the attack move the verdict?
    print("\n### What an attack costs, on identical content\n")
    print("| side | attack | n sources | recall@0.85 clean | recall@0.85 attacked | delta | flipped to clean |")
    print("|---|---|---|---|---|---|---|")
    by_src: dict[str, dict[str, dict[str, Any]]] = {}
    for it in items:
        by_src.setdefault(it["source"], {})[it["attack"]] = it
    for side in ("ai", "human"):
        for attack in ("paraphrase", "synonym"):
            pairs = [
                (v["none"], v[attack])
                for v in by_src.values()
                if "none" in v and attack in v and v["none"]["side"] == side
            ]
            if not pairs:
                continue
            a = sum(1 for c, _ in pairs if p[c["id"]] >= 0.85) / len(pairs)
            b = sum(1 for _, k in pairs if p[k["id"]] >= 0.85) / len(pairs)
            lost = sum(1 for c, k in pairs if p[c["id"]] >= 0.85 and p[k["id"]] < 0.85)
            print(f"| {side} | {attack} | {len(pairs)} | {a:.3f} | {b:.3f} | {b - a:+.3f} | {lost} |")

    print("\n### The regex under the same attacks\n")
    for side in ("ai", "human"):
        for attack in ("paraphrase", "synonym"):
            pairs = [
                (v["none"], v[attack])
                for v in by_src.values()
                if "none" in v and attack in v and v["none"]["side"] == side
            ]
            if not pairs:
                continue
            a = sum(1 for c, _ in pairs if c["rx"]) / len(pairs)
            b = sum(1 for _, k in pairs if k["rx"]) / len(pairs)
            print(f"- {side}/{attack}: regex {a:.3f} clean, {b:.3f} attacked ({b - a:+.3f})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "fetch":
        fetch()
    elif cmd == "ask":
        ask()
    elif cmd == "report":
        report()
    else:
        raise SystemExit(f"unknown command {cmd}")
