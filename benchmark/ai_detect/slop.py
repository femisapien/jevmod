"""Formulation D: Jev as a semantic matcher for the humanizer's patterns, not as an authorship judge.

The question changed. `run.py` asked "was this written by a language model", which is authorship, needs a
ground truth nobody can see, and flags careful humans. The product question is narrower and answerable:
**does this message read as assistant slop?** A member pasting an assistant answer into a channel is the
thing a server owner wants gone, and a human who writes that way is producing the same thing.

`deterministic.py` answers it with regex over the five mined assistant-register patterns. That is precise
and blind: each phrase list fires on at most 21% of AI text, the union on 48.5%, and any paraphrase escapes.
Omar's point, and it is the right one: give Jev the same five patterns as criteria and let it match them by
meaning instead of by phrase.

So D asks one Noul per message, naming the patterns and nothing about who typed it. What it is compared
against needs no new labels:

  recall  the 260 AI texts of `results/dataset.jsonl` - specifically the 51.5% the regex misses
  FPR     the 697 careful/formal/non-native humans of `results/trap.jsonl`, plus the 90 real chat messages

If D fires where the regex fires AND on the paraphrases it misses, at the same false-positive rate, Omar is
right and the category becomes shippable as a slop rule. If it buys recall by also firing on careful humans,
it is formulation A again under a new name.

    python -m benchmark.ai_detect.slop ask        # sorted batches: all AI, then chat, then careful
    python -m benchmark.ai_detect.slop ask-mixed  # the same texts shuffled into 25%-AI batches
    python -m benchmark.ai_detect.slop report

`ask` batches the corpus in the order it loads, which puts every AI text in an all-AI batch. REPORT2.md
measured that this inflates scores. `ask-mixed` shuffles the same 1047 texts with a fixed seed so every
batch is roughly 25% AI, and the report compares the two: the gap between them is the composition effect
on this question, and the mixed column is the one that counts.

Nothing here touches `jevmod/`.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from .features import extract

HERE = Path(__file__).parent
RESULTS = HERE / "results"
RAW = RESULTS / "raw_D.jsonl"
RAW_MIXED = RESULTS / "raw_D_mixed.jsonl"
USD_PER_M = 0.042
BATCH = 25

# The five mined assistant-register patterns, written as meanings rather than as phrase lists. These are the
# same SKILL.md sections `features.py` implements as regex; the wording is deliberately about what the
# sentence is DOING, so a paraphrase still matches.
PATTERNS = (
    "announcing a list before giving it ('there are several reasons', 'a variety of factors'); "
    "scaffolding a point with a stock qualifier ('it is important to note', 'keep in mind that', "
    "'it is worth noting'); "
    "opening with a definition nobody asked for ('X refers to', 'X is a type of', 'also known as'); "
    "explaining its own sentence ('this means that', 'in other words', 'this is because'); "
    "handing the question off to an authority ('consult a professional', 'seek medical attention'); "
    "staging the point before making it, defending against an objection nobody raised, or closing with a "
    "summary that restates instead of adding"
)


def questions_d(path: str) -> dict[str, Any]:
    from typesafe_sdk import Noul

    return {
        "d": Noul(
            instructions=(
                f"Does `{path}.text` use the writing patterns of an AI assistant answering a question, "
                f"whoever typed it?"
            ),
            criteria={
                "true": (
                    f"one or more of these are present, in any wording: {PATTERNS}. "
                    "It is asking whether the text DOES these things, not whether it uses these exact phrases: "
                    "a paraphrase counts"
                ),
                "false": (
                    "none of those patterns are present. Formal register, correct grammar, long sentences, "
                    "technical vocabulary, a neutral tone and imperfect English from a non-native speaker are "
                    "NOT patterns on that list and do not make this true on their own. A careful person "
                    "explaining something plainly, without the assistant scaffolding, is false"
                ),
            },
        )
    }


REGISTER = ("d_enumerative", "d_hedge_scaffold", "d_definitional", "d_explainer", "d_safety_referral")
STAGING = ("d_not_x_but_y", "d_deep_sayings", "d_staged_opener", "d_strawman", "d_tidy_closer")


def regex_fires(text: str) -> bool:
    """What `deterministic.py` would say: any of the five register patterns, or any staging tell."""
    f = extract(text)
    return sum(f[k] for k in REGISTER) >= 1 or sum(f[k] for k in STAGING) >= 1


def load_items() -> list[dict[str, Any]]:
    """The 260 AI texts and the 90 real chat messages from round one, plus the 697-item trap corpus."""
    items = []
    for line in (RESULTS / "dataset.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r["label"] == 1:
            items.append({"id": r["id"], "text": r["text"], "side": "ai", "stratum": r["stratum"]})
        elif r["stratum"] == "human_chat":
            items.append({"id": r["id"], "text": r["text"], "side": "chat", "stratum": r["stratum"]})
    for line in (RESULTS / "trap.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        items.append({"id": r["id"], "text": r["text"], "side": "careful", "stratum": r["stratum"]})
    return items


def ask(mixed: bool = False) -> None:
    """`mixed` shuffles the corpus with a fixed seed, so no batch is all-AI or all-human."""
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    from jevmod.keys import get_api_key

    items = load_items()
    out = RAW_MIXED if mixed else RAW
    if mixed:
        random.Random(20260919).shuffle(items)
    done = {json.loads(line)["id"] for line in out.open(encoding="utf-8")} if out.exists() else set()
    todo = [it for it in items if it["id"] not in done]
    print(f"[D{'-mixed' if mixed else ''}] {len(todo)} to ask, {len(done)} already done")

    client = TypeSafeClient(
        api_key=get_api_key(),
        retry=RetryPolicy(
            max_retries=3, backoff_initial=0.5, backoff_max=8.0, http_statuses={429, 500, 502, 503, 504, 529}
        ),
        timeout=90.0,
    )
    total = 0
    with out.open("a", encoding="utf-8") as fh:
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
                f"[D] {start + len(chunk)}/{len(todo)}  {toks:,} tok  {ms:.0f} ms  "
                f"running {total:,} tok  ${total * USD_PER_M / 1e6:.4f}"
            )


def _rate(sub: list[dict[str, Any]], hit) -> float:
    return sum(1 for it in sub if hit(it)) / len(sub) if sub else float("nan")


def _scores(path: Path) -> dict[str, float]:
    return {json.loads(line)["id"]: json.loads(line)["p"] for line in path.open(encoding="utf-8")}


def report() -> None:
    items = load_items()
    sorted_p = _scores(RAW)
    p = _scores(RAW_MIXED) if RAW_MIXED.exists() else sorted_p
    items = [it for it in items if it["id"] in p]
    for it in items:
        it["rx"] = regex_fires(it["text"])
    ai = [it for it in items if it["side"] == "ai"]
    careful = [it for it in items if it["side"] == "careful"]
    chat = [it for it in items if it["side"] == "chat"]
    wiki = [it for it in careful if it["stratum"] == "hc3_human_wiki_csai"]
    nn = [it for it in careful if it["stratum"] == "nonnative_learner"]

    print(f"\n## Formulation D: Jev matching the humanizer's patterns by meaning, n={len(items)}\n")
    which = "shuffled 25%-AI batches" if RAW_MIXED.exists() else "sorted batches"
    print(f"AI {len(ai)}, careful human {len(careful)}, real chat {len(chat)}. Scores from {which}.\n")

    print("| rule | fires on AI | careful human | wiki-style | non-native | real chat |")
    print("|---|---|---|---|---|---|")
    rules: list[tuple[str, Any]] = [("regex (deterministic.py)", lambda it: it["rx"])]
    for th in (0.5, 0.7, 0.85, 0.9):
        rules.append((f"D >= {th}", lambda it, th=th: p[it["id"]] >= th))
    rules.append(("regex OR D >= 0.85", lambda it: it["rx"] or p[it["id"]] >= 0.85))
    rules.append(("regex AND D >= 0.85", lambda it: it["rx"] and p[it["id"]] >= 0.85))
    for label, hit in rules:
        print(
            f"| {label} | {_rate(ai, hit):.3f} | {_rate(careful, hit):.3f} | {_rate(wiki, hit):.3f} "
            f"| {_rate(nn, hit):.3f} | {_rate(chat, hit):.3f} |"
        )

    # The whole question: does D see the AI text the regex is blind to, without also seeing careful humans?
    print("\n### Where the regex is blind\n")
    missed = [it for it in ai if not it["rx"]]
    caught = [it for it in ai if it["rx"]]
    print(f"- regex fires on {len(caught)}/{len(ai)} AI texts ({len(caught) / len(ai):.3f})")
    for th in (0.5, 0.7, 0.85, 0.9):
        r = sum(1 for it in missed if p[it["id"]] >= th) / len(missed) if missed else float("nan")
        c = sum(1 for it in careful if not it["rx"] and p[it["id"]] >= th) / max(
            1, sum(1 for it in careful if not it["rx"])
        )
        print(f"- of the {len(missed)} it misses, D >= {th} recovers {r:.3f}; on regex-clean careful humans it adds {c:.3f}")

    if RAW_MIXED.exists():
        print("\n### The same question in sorted and in shuffled batches\n")
        print("| side | n | mean p, sorted | mean p, shuffled | drift | fires@0.7 sorted | fires@0.7 shuffled |")
        print("|---|---|---|---|---|---|---|")
        for name, sub in (("AI", ai), ("careful human", careful), ("wiki-style", wiki), ("real chat", chat)):
            a = sum(sorted_p[i["id"]] for i in sub) / len(sub)
            b = sum(p[i["id"]] for i in sub) / len(sub)
            fa = _rate(sub, lambda it: sorted_p[it["id"]] >= 0.7)
            fb = _rate(sub, lambda it: p[it["id"]] >= 0.7)
            print(f"| {name} | {len(sub)} | {a:.3f} | {b:.3f} | {b - a:+.3f} | {fa:.3f} | {fb:.3f} |")
        flip = sum(1 for it in items if (sorted_p[it["id"]] >= 0.7) != (p[it["id"]] >= 0.7))
        print(f"\n{flip} of {len(items)} items cross 0.7 between the two runs ({flip / len(items):.3f}).")

    print("\n### Disagreements, for a human to read\n")
    dis = [it for it in items if it["rx"] != (p[it["id"]] >= 0.85)]
    print(f"{len(dis)} of {len(items)} items disagree at D >= 0.85. Written to results/disagree_D.md")
    out = ["# Where the regex and Jev disagree about slop", ""]
    for it in sorted(dis, key=lambda i: -p[i["id"]]):
        verdict = "Jev says slop, regex does not" if not it["rx"] else "regex says slop, Jev does not"
        out += [f"## {it['id']}  ({it['side']}/{it['stratum']})", f"**{verdict}**, D={p[it['id']]:.2f}", "",
                "> " + it["text"].replace("\n", " "), ""]
    (RESULTS / "disagree_D.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "ask":
        ask()
    elif cmd == "ask-mixed":
        ask(mixed=True)
    elif cmd == "report":
        report()
    else:
        raise SystemExit(f"unknown command {cmd}")
