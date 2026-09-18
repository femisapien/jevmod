"""Can Jev tell AI-written text from human-written text, well enough for an `ai_generated` jevmod category?

Three competing question formulations are asked about the same 520 texts, one request per batch of 25, the same
batching contract as `jevmod.judge.Judge`: state is a dict keyed `m0..mN`, every question carries criteria.

    A  one Noul, direct: "was this written by a language model rather than typed by a person?"
    B  one Score, indirect proxy: "how much does this read like a person typing quickly in a chat" (4 levels)
    C  two Nouls, decomposed: "polished prose rather than a chat message" and "contains personal specific detail"

Usage (repo venv, PYTHONUTF8=1, TYPESAFE_API_KEY in the environment):

    python -m benchmark.ai_detect.run prepare     # builds results/dataset.jsonl
    python -m benchmark.ai_detect.run ask A B C   # resumable; appends to results/raw_<F>.jsonl
    python -m benchmark.ai_detect.run report      # prints the tables in REPORT.md
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
RESULTS = HERE / "results"
DATASET = RESULTS / "dataset.jsonl"
MAX_CHARS = 400
BATCH = 25
USD_PER_M = 0.042
TOKEN_BUDGET = 5_000_000

# ---------------------------------------------------------------------------------------------- data


def _clip(text: str) -> str:
    """Normalise like jevmod does, then truncate to a chat-sized message on a word boundary."""
    from jevmod.judge import normalize

    t = normalize(text)
    if len(t) <= MAX_CHARS:
        return t
    cut = t[:MAX_CHARS]
    return cut[: cut.rfind(" ")] if " " in cut[300:] else cut


def prepare(seed: int = 20260918) -> None:
    """Balanced human/AI set in the shape jevmod sees: short messages, not essays. Provenance per item."""
    from datasets import load_dataset

    rng = random.Random(seed)
    items: list[dict[str, Any]] = []

    # 1. HC3: the same questions answered by a human and by ChatGPT. Topic-matched, so the classifier cannot
    #    win on subject matter alone. Only rows where both answers are short enough to be a chat message.
    hc3 = load_dataset("json", data_files="hf://datasets/Hello-SimpleAI/HC3/all.jsonl", split="train")
    pool = []
    for r in hc3:
        h = (r["human_answers"] or [None])[0]
        a = (r["chatgpt_answers"] or [None])[0]
        if not h or not a:
            continue
        if not (60 <= len(h) <= 1200 and 60 <= len(a) <= 1200):
            continue
        pool.append((r["source"], _clip(h), _clip(a)))
    rng.shuffle(pool)
    by_source: dict[str, list[tuple[str, str, str]]] = {}
    for row in pool:
        by_source.setdefault(row[0], []).append(row)
    # even spread over the five HC3 domains
    picked: list[tuple[str, str, str]] = []
    per = 260 // len(by_source) + 1
    for src in sorted(by_source):
        picked += by_source[src][:per]
    rng.shuffle(picked)
    picked = picked[:260]
    for i, (src, h, a) in enumerate(picked):
        items.append(
            {
                "id": f"ai{i}",
                "text": a,
                "label": 1,
                "provenance": f"HC3/{src}/chatgpt",
                "stratum": "ai_chatgpt",
                "pair": i,
            }
        )
        if i < 130:  # topic-matched human half; the rest of the human side is real chat
            items.append(
                {
                    "id": f"hu{i}",
                    "text": h,
                    "label": 0,
                    "provenance": f"HC3/{src}/human",
                    "stratum": "human_hc3_formal",
                    "pair": i,
                }
            )

    # 2. Real chat we already have on disk: YouTube comments and Civil Comments, clean labels only.
    disk = [json.loads(l) for l in (HERE.parent / "data" / "items.jsonl").open(encoding="utf-8")]
    yt = [r for r in disk if r["source"] == "youtube_spam" and not r["labels"]]
    cc = [r for r in disk if r["source"] == "civil_comments" and not r["labels"]]
    rng.shuffle(yt)
    rng.shuffle(cc)
    cc_short = [r for r in cc if len(r["text"]) < 200]
    cc_long = [r for r in cc if len(r["text"]) >= 200]
    for r in yt[:60]:
        items.append(
            {
                "id": f"yt{r['id']}",
                "text": _clip(r["text"]),
                "label": 0,
                "provenance": "UCI YouTube Spam Collection (non-spam)",
                "stratum": "human_chat",
                "pair": None,
            }
        )
    for r in cc_short[:30]:
        items.append(
            {
                "id": f"cs{r['id']}",
                "text": _clip(r["text"]),
                "label": 0,
                "provenance": "Civil Comments (toxicity<=0.1, short)",
                "stratum": "human_chat",
                "pair": None,
            }
        )
    for r in cc_long[:20]:
        items.append(
            {
                "id": f"cl{r['id']}",
                "text": _clip(r["text"]),
                "label": 0,
                "provenance": "Civil Comments (toxicity<=0.1, >=200 chars)",
                "stratum": "human_formal_long",
                "pair": None,
            }
        )

    # 3. Non-native English, written by learners: the false positive that matters most for moderation.
    jf = load_dataset("jhu-clsp/jfleg", split="validation")
    learner = [s for s in jf["sentence"] if 80 <= len(s.strip()) <= 400]
    rng.shuffle(learner)
    for i, s in enumerate(learner[:20]):
        items.append(
            {
                "id": f"nn{i}",
                "text": _clip(s),
                "label": 0,
                "provenance": "JFLEG (English-learner sentences, uncorrected)",
                "stratum": "human_nonnative",
                "pair": None,
            }
        )

    rng.shuffle(items)
    RESULTS.mkdir(parents=True, exist_ok=True)
    with DATASET.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    n_ai = sum(it["label"] for it in items)
    print(f"{len(items)} items, {n_ai} AI, {len(items) - n_ai} human, base rate {n_ai / len(items):.3f}")
    for s in sorted({it["stratum"] for it in items}):
        print(f"  {s:22s} {sum(1 for it in items if it['stratum'] == s):4d}")


def load_items() -> list[dict[str, Any]]:
    return [json.loads(l) for l in DATASET.open(encoding="utf-8")]


# ---------------------------------------------------------------------- the three question formulations

HUMAN_TELLS = (
    "typos, missing apostrophes, lowercase starts, slang, abbreviations (lol, idk, imo), emotion or swearing, "
    "an unfinished thought, a reply to someone else, an in-joke or a reference to this channel/video/thread, "
    "an opinion stated bluntly with no hedging"
)
AI_TELLS = (
    "evenly hedged structure, complete and correct punctuation with no typos, generic politeness, "
    "list-like or 'there are several reasons' phrasing, a tidy summary sentence at the end, "
    "no slang, no in-jokes, an encyclopedic explaining register aimed at nobody in particular"
)


def questions_a(path: str) -> dict[str, Any]:
    from typesafe_sdk import Noul

    return {
        "a": Noul(
            instructions=(
                f"Was `{path}.text` written by a language model (an AI assistant) rather than typed by a "
                f"person in a chat, comment thread or forum?"
            ),
            criteria={
                "true": f"it reads as generated assistant output: {AI_TELLS}",
                "false": f"it reads as a person typing: {HUMAN_TELLS}. Careful writing, correct grammar, a formal "
                f"register or imperfect English from a non-native speaker are NOT by themselves signs of a "
                f"language model; many people write carefully",
            },
        )
    }


def questions_b(path: str) -> dict[str, Any]:
    from typesafe_sdk import Score

    return {
        "b": Score(
            instructions=f"How much does `{path}.text` read like a person typing quickly in a chat?",
            criteria=[
                "Not at all: polished assistant prose. Balanced, hedged, fully punctuated, explains a topic to "
                "nobody in particular, often a tidy closing summary.",
                "Barely: careful, complete, neutral writing with no personal voice, but addressed to someone; "
                "could be a well-written forum post or could be generated.",
                "Mostly: a real person writing at their own pace, with opinions, a point of view and small "
                "informalities, though the grammar is fine.",
                "Completely: typed fast into a chat box. Typos, lowercase, slang, abbreviations, emotion, "
                "in-jokes, replies to someone, unfinished thoughts.",
            ],
        )
    }


def questions_c(path: str) -> dict[str, Any]:
    from typesafe_sdk import Noul

    return {
        "c_polished": Noul(
            instructions=(
                f"Does `{path}.text` read as edited, polished prose rather than a message typed into a chat box?"
            ),
            criteria={
                "true": "complete sentences, full punctuation, no typos, even structure, an explaining or essay "
                "register, no abbreviations or slang",
                "false": "typed-in-the-moment writing: typos, lowercase, slang, abbreviations, emoji, "
                "an abrupt or unfinished thought, a direct reply to another person",
            },
        ),
        "c_personal": Noul(
            instructions=(
                f"Does `{path}.text` contain personal, specific or situated detail that a language model "
                f"writing a generic answer would not produce?"
            ),
            criteria={
                "true": "the author's own experience, a named person or place they know, a reference to this "
                "channel, video, thread or a previous message, a strong personal opinion, an in-joke, "
                "a concrete anecdote",
                "false": "general explanation with no first-hand detail, textbook facts, advice addressed to "
                "nobody in particular",
            },
        ),
    }


FORMULATIONS = {"A": questions_a, "B": questions_b, "C": questions_c}


def _answer(ans: Any) -> dict[str, float]:
    from typesafe_sdk import NoulAnswer, ScoreAnswer

    if isinstance(ans, NoulAnswer):
        return {"p": float(ans.noul)}
    if isinstance(ans, ScoreAnswer):
        return {"score": float(ans.score), "levels": len(ans.legend)}
    raise TypeError(f"unexpected answer type {type(ans).__name__}")


def ask(formulations: list[str]) -> None:
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    from jevmod.keys import get_api_key

    items = load_items()
    client = TypeSafeClient(
        api_key=get_api_key(),
        retry=RetryPolicy(
            max_retries=3, backoff_initial=0.5, backoff_max=8.0, http_statuses={429, 500, 502, 503, 504, 529}
        ),
        timeout=90.0,
    )
    total_tokens = 0
    for f in formulations:
        build = FORMULATIONS[f]
        out = RESULTS / f"raw_{f}.jsonl"
        done = {json.loads(l)["id"] for l in out.open(encoding="utf-8")} if out.exists() else set()
        todo = [it for it in items if it["id"] not in done]
        print(f"[{f}] {len(todo)} to ask, {len(done)} already done")
        with out.open("a", encoding="utf-8") as fh:
            for start in range(0, len(todo), BATCH):
                chunk = todo[start : start + BATCH]
                state = {"messages": {f"m{i}": {"text": it["text"]} for i, it in enumerate(chunk)}}
                questions: dict[str, Any] = {}
                for i in range(len(chunk)):
                    for name, q in build(f"messages.m{i}").items():
                        questions[f"{name}_{i}"] = q
                t0 = time.time()
                resp = client.system_one(state=state, questions=questions)
                ms = (time.time() - t0) * 1000
                toks = getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0
                total_tokens += toks
                for i, it in enumerate(chunk):
                    rec = {
                        "id": it["id"],
                        "formulation": f,
                        "answers": {n: _answer(resp.answers[f"{n}_{i}"]) for n in build("x")},
                        "batch_tokens": toks,
                        "batch_n": len(chunk),
                        "batch_ms": ms,
                    }
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                print(
                    f"[{f}] {start + len(chunk)}/{len(todo)}  {toks:,} tok  {ms:.0f} ms  "
                    f"running {total_tokens:,} tok  ${total_tokens * USD_PER_M / 1e6:.4f}"
                )
                if total_tokens > TOKEN_BUDGET:
                    print(f"STOP: token budget {TOKEN_BUDGET:,} exceeded")
                    return


# ------------------------------------------------------------------------------------------- reporting


def auroc(pairs: list[tuple[float, int]]) -> float | None:
    pos = [s for s, y in pairs if y]
    neg = [s for s, y in pairs if not y]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def prf(pairs: list[tuple[float, int]], th: float) -> tuple[float, float, float]:
    tp = sum(1 for s, y in pairs if y and s >= th)
    fp = sum(1 for s, y in pairs if not y and s >= th)
    fn = sum(1 for s, y in pairs if y and s < th)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return (2 * prec * rec / (prec + rec) if prec + rec else 0.0, prec, rec)


def best_f1(pairs: list[tuple[float, int]]) -> tuple[float, float]:
    best = (0.0, 0.5)
    for th in [i / 100 for i in range(5, 100, 5)]:
        f = prf(pairs, th)[0]
        if f > best[0]:
            best = (f, th)
    return best


def ship_threshold(pairs: list[tuple[float, int]], min_p: float = 0.90, min_r: float = 0.50) -> tuple | None:
    """Lowest threshold that reaches precision >= min_p with recall >= min_r: the ship bar."""
    for th in [i / 100 for i in range(5, 100, 1)]:
        f, p, r = prf(pairs, th)
        if p >= min_p and r >= min_r:
            return (th, p, r, f)
    return None


def ece(pairs: list[tuple[float, int]], bins: int = 10) -> float:
    n = len(pairs)
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(s, y) for s, y in pairs if (lo <= s < hi or (b == bins - 1 and s == 1.0))]
        if not sel:
            continue
        conf = sum(s for s, _ in sel) / len(sel)
        acc = sum(y for _, y in sel) / len(sel)
        total += len(sel) / n * abs(conf - acc)
    return total


def brier(pairs: list[tuple[float, int]]) -> float:
    return sum((s - y) ** 2 for s, y in pairs) / len(pairs)


def scores_for(f: str) -> dict[str, dict[str, float]]:
    """Every probability a formulation yields, including the combinations for C."""
    p = RESULTS / f"raw_{f}.jsonl"
    if not p.exists():
        return {}
    out: dict[str, dict[str, float]] = {}
    for line in p.open(encoding="utf-8"):
        r = json.loads(line)
        a = r["answers"]
        if f == "A":
            out[r["id"]] = {"A": a["a"]["p"]}
        elif f == "B":
            lv = a["b"]["levels"] - 1
            out[r["id"]] = {"B": 1.0 - a["b"]["score"] / lv}
        else:
            pol, per = a["c_polished"]["p"], a["c_personal"]["p"]
            out[r["id"]] = {
                "C": (pol + (1 - per)) / 2,
                "C_product": pol * (1 - per),
                "C_polished": pol,
                "C_impersonal": 1 - per,
            }
    return out


def all_scores() -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {}
    for f in FORMULATIONS:
        for i, s in scores_for(f).items():
            merged.setdefault(i, {}).update(s)
    return merged


def report() -> None:
    items = {it["id"]: it for it in load_items()}
    sc = all_scores()
    variants = ["A", "B", "C", "C_product", "C_polished", "C_impersonal"]
    ids = [i for i in items if i in sc and all(v in sc[i] for v in variants)]
    n_ai = sum(items[i]["label"] for i in ids)
    print(f"n={len(ids)}  AI={n_ai}  human={len(ids) - n_ai}  base rate={n_ai / len(ids):.3f}\n")

    subsets = {
        "all": ids,
        "chat-shaped only (AI vs real chat)": [
            i for i in ids if items[i]["label"] or items[i]["stratum"] == "human_chat"
        ],
        "topic-matched HC3 pairs": [i for i in ids if items[i]["pair"] is not None],
    }

    print("| subset | variant | n | AUROC | F1@0.5 | P@0.5 | R@0.5 | best F1 (th) | ECE | Brier |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, sub in subsets.items():
        for v in variants:
            pairs = [(sc[i][v], items[i]["label"]) for i in sub]
            a = auroc(pairs)
            f, p, r = prf(pairs, 0.5)
            bf, bth = best_f1(pairs)
            print(
                f"| {label} | {v} | {len(sub)} | {a:.3f} | {f:.3f} | {p:.3f} | {r:.3f} | "
                f"{bf:.3f} ({bth:.2f}) | {ece(pairs):.3f} | {brier(pairs):.3f} |"
            )

    print("\n### Ship bar: lowest threshold with precision >= 0.90 at recall >= 0.50\n")
    print("| subset | variant | threshold | precision | recall | F1 |")
    print("|---|---|---|---|---|---|")
    for label, sub in subsets.items():
        for v in variants:
            pairs = [(sc[i][v], items[i]["label"]) for i in sub]
            t = ship_threshold(pairs)
            print(
                f"| {label} | {v} | {t[0]:.2f} | {t[1]:.3f} | {t[2]:.3f} | {t[3]:.3f} |"
                if t
                else f"| {label} | {v} | none | | | |"
            )

    print("\n### False positive rate per human stratum (at 0.5, and at the best-F1 threshold of A)\n")
    a_pairs = [(sc[i]["A"], items[i]["label"]) for i in ids]
    a_th = best_f1(a_pairs)[1]
    print(f"| stratum | n | " + " | ".join(f"{v} @0.5" for v in ["A", "B", "C"]) + f" | A @{a_th:.2f} |")
    print("|---|---|---|---|---|---|")
    for s in sorted({items[i]["stratum"] for i in ids if not items[i]["label"]}):
        sub = [i for i in ids if items[i]["stratum"] == s]
        cells = [f"{sum(1 for i in sub if sc[i][v] >= 0.5) / len(sub):.3f}" for v in ["A", "B", "C"]]
        hi = sum(1 for i in sub if sc[i]["A"] >= a_th) / len(sub)
        print(f"| {s} | {len(sub)} | " + " | ".join(cells) + f" | {hi:.3f} |")

    print("\n### Human false positives by source (A), at 0.5 and at 0.85\n")
    print("| provenance | n | FPR @0.5 | FPR @0.85 |")
    print("|---|---|---|---|")
    for prov in sorted({items[i]["provenance"] for i in ids if not items[i]["label"]}):
        sub = [i for i in ids if items[i]["provenance"] == prov]
        lo = sum(1 for i in sub if sc[i]["A"] >= 0.5) / len(sub)
        hi = sum(1 for i in sub if sc[i]["A"] >= 0.85) / len(sub)
        print(f"| {prov} | {len(sub)} | {lo:.3f} | {hi:.3f} |")

    print("\n### Precision if AI messages are rare (A, TPR/FPR measured here)\n")
    print("FPR* is the 95% upper bound (rule of three, 3/n, when no false positive was observed): a zero on")
    print("90 messages only means the rate is below ~3%. Precision is projected with FPR*.\n")
    print("| human side | threshold | TPR | FPR obs | FPR* | P @50% AI | P @10% | P @5% | P @2% | P @1% |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, sub in (
        ("chat only", subsets["chat-shaped only (AI vs real chat)"]),
        ("all human", ids),
    ):
        for th in (0.5, 0.85, 0.95):
            pos = [i for i in sub if items[i]["label"]]
            neg = [i for i in sub if not items[i]["label"]]
            tpr = sum(1 for i in pos if sc[i]["A"] >= th) / max(len(pos), 1)
            k = sum(1 for i in neg if sc[i]["A"] >= th)
            fpr = k / max(len(neg), 1)
            fpr_ub = max(fpr, 3.0 / len(neg))
            cells = []
            for pi in (0.5, 0.10, 0.05, 0.02, 0.01):
                denom = pi * tpr + (1 - pi) * fpr_ub
                cells.append(f"{pi * tpr / denom:.3f}" if denom else "n/a")
            print(
                f"| {label} | {th:.2f} | {tpr:.3f} | {fpr:.3f} | {fpr_ub:.3f} | " + " | ".join(cells) + " |"
            )

    for v in ["A"]:
        for kind, rev, want in (("false positives", True, 0), ("false negatives", False, 1)):
            rows = sorted(
                (i for i in ids if items[i]["label"] == want), key=lambda i: sc[i][v], reverse=rev
            )[:10]
            print(f"\n### 10 worst {kind} ({v})\n")
            print("| p | stratum | provenance | text |")
            print("|---|---|---|---|")
            for i in rows:
                t = items[i]["text"].replace("|", "/")[:180]
                print(f"| {sc[i][v]:.3f} | {items[i]['stratum']} | {items[i]['provenance']} | {t} |")

    print("\n### Cost and latency (measured input tokens, ${:.3f}/M)\n".format(USD_PER_M))
    print("| formulation | requests | input tokens | tokens/msg | $ / 1,000 msgs | latency / msg |")
    print("|---|---|---|---|---|---|")
    grand = 0
    for f in FORMULATIONS:
        rows = [json.loads(l) for l in (RESULTS / f"raw_{f}.jsonl").open(encoding="utf-8")]
        batches = {(r["batch_tokens"], r["batch_ms"], r["batch_n"]) for r in rows}
        toks = sum(b[0] for b in batches)
        ms = sum(b[1] for b in batches)
        n = len(rows)
        grand += toks
        print(
            f"| {f} | {len(batches)} | {toks:,} | {toks / n:.0f} | ${toks / n * 1000 * USD_PER_M / 1e6:.4f} "
            f"| {ms / n:.0f} ms |"
        )
    print(f"\nTotal spend for this experiment: {grand:,} input tokens = ${grand * USD_PER_M / 1e6:.4f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "prepare":
        prepare()
    elif cmd == "ask":
        ask(sys.argv[2:] or list(FORMULATIONS))
    else:
        report()
