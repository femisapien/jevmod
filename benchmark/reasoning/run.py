"""JEV-15: can a jevmod judgment carry a rationale, what does it cost, and does asking for it move the scores?

Jev returns no text. `/v1/systemone` answers a Noul with a probability, a Choice with a choice and its
distribution, a Score with a level; the response schema has `model`, `answers` and `usage` and nothing else
(OpenAPI 0.2.0, typesafe-sdk 0.6.0, checked 2026-09-27), and the docs say it outright: "System One models do not
write replies, produce code, or generate explanations of their reasoning" (docs.typesafe.ai, System One). So a rationale can only be *selected*, never
generated: a Choice over reason codes written here, and a Choice over spans of the message that code cuts out.
This runner measures both, in the two places they could live:

- **inline** (arm B): one extra Choice per message in the same request as the seven-category judgment, over
  every category's reason codes. Paid for every judged message; it is the "extra field" option.
- **companion** (arm C): a second request, only for messages the policy flagged, with a reason-code Choice
  for the flagged category and an evidence-span Choice. Measured batched (every flagged message of a
  judgment batch in one request) and single (one message per request, which is what "on demand when a
  moderator opens the item" costs).

Arms A and A2 are the unchanged judgment sent twice, so the shift B causes is compared with the shift a
repeat causes. A, B and A2 are sent back to back for every batch, so drift over the run hits all three alike.
All three go through `jevmod.judge.Judge` itself; B only adds questions to the request Judge built, through a
client wrapper, so the judgment questions and the state are byte for byte the ones production sends.

    set PYTHONUTF8=1
    .venv\\Scripts\\python -m benchmark.reasoning.run prepare     # results/dataset.jsonl
    .venv\\Scripts\\python -m benchmark.reasoning.run judge       # arms A, B, A2 -> results/judge.jsonl
    .venv\\Scripts\\python -m benchmark.reasoning.run companion   # arm C -> results/companion.jsonl
    .venv\\Scripts\\python -m benchmark.reasoning.run sheet       # results/handread.md, the 30 read by hand
    .venv\\Scripts\\python -m benchmark.reasoning.run report      # every table in REPORT.md

`judge` and `companion` are resumable and stop past MAX_TOKENS input tokens.
"""

from __future__ import annotations

import csv
import json
import random
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from typesafe_sdk import Choice  # noqa: E402

from jevmod.core.policy import DEFAULT_ACTIONS, DEFAULT_THRESHOLDS  # noqa: E402
from jevmod.judge import CATEGORIES, Judge, Message, normalize  # noqa: E402

HERE = Path(__file__).parent
RESULTS = HERE / "results"
ROOT = HERE.parents[1]
SEED = 20260927
USD_PER_M = 0.042  # jev-1.13.0 list price per million input tokens; output tokens are free (docs.typesafe.ai/models)
MAX_TOKENS = 3_000_000
BATCH = 9  # nine real messages plus Judge's m0 filler: the ten-position request production sends (PAD_TO)
MAX_CHARS = 600
CATS = [c for c in CATEGORIES if DEFAULT_ACTIONS.get(c, "flag") != "off"]

# Reason codes per category. Each is one clause of that category's `criteria.true` in categories.json, written
# as a concrete situation, so the code a moderator reads is the criterion the score was asked against.
# `other` means the category fits for a reason not listed; `not_it` means nothing in the message fits, which
# is the companion's way of disagreeing with the flag instead of being forced to invent a reason.
REASONS: dict[str, dict[str, str]] = {
    "spam": {
        "invite_link": "pushes an invite, referral or affiliate link at the community",
        "advertising": "advertises a product, channel, stream or service to the community",
        "repeated": "a repeated or copy-pasted offer or block of text",
        "attention": "begs for attention: follow me, sub4sub, mass mentions",
        "bare_link": "a bare or shortened link with no conversational purpose",
    },
    "scam": {
        "fake_giveaway": "a fake giveaway: free Nitro, skins, gift cards or crypto",
        "lookalike_domain": "a link to a domain imitating a real service",
        "impersonation": "pretends to be staff, support, a bot or an official account",
        "money": "asks for money, payment or crypto under false pretenses, or promises to multiply it",
        "credentials": "asks for a login, password, code, or urgent account verification",
        "dm_deal": "asks people to DM for a deal or an offer",
    },
    "harassment": {
        "insult": "insults or name-calling aimed at a person",
        "identity_attack": "demeans a group for who they are: race, religion, gender, sexuality, disability, origin",
        "threat": "threatens violence or harm against someone",
        "tell_to_harm": "tells someone to leave, die or hurt themselves",
        "dehumanising": "dehumanising or degrading language about a person or group",
    },
    "nsfw": {
        "explicit": "describes sexual acts or sexual body parts explicitly",
        "solicitation": "solicits sexual content or contact: nudes, pics, hookups",
        "gore": "describes graphic violence, injury or gore",
    },
    "selfharm": {
        "wants_to_die": "says the author wants to die or to disappear",
        "self_injury": "describes hurting themselves or wanting to",
        "plan_or_goodbye": "describes a plan, or says goodbye",
        "hopeless": "hopelessness about the author's own life",
        "asks_method": "asks how to hurt or kill oneself",
    },
    "doxxing": {
        "address_phone": "gives or asks for someone's home address or phone number",
        "real_identity": "reveals the real name, workplace or school behind someone's account",
        "numbers": "gives ID, card or bank numbers belonging to someone",
        "hunt": "asks others to find or share private data about someone",
    },
    "minors": {
        "sexualises_minor": "sexual comments about someone under 18",
        "solicits_minor": "asks a minor for photos or private contact",
        "grooming": "gifts, secrecy or private trust-building with a child",
    },
}
LABEL = {c: CATEGORIES[c]["label"] for c in CATS}


def reason_criteria(cat: str) -> dict[str, str]:
    return {
        **REASONS[cat],
        "other": f"it is {LABEL[cat]}, but for a reason none of the other options describes",
        "not_it": f"nothing in it is {LABEL[cat]}: an ordinary message",
    }


def inline_criteria() -> dict[str, str]:
    """Arm B's one Choice per message: every category's codes, prefixed by the category, plus 'nothing'."""
    out = {f"{c}__{k}": f"{LABEL[c]}: {v}" for c in CATS for k, v in REASONS[c].items()}
    out["nothing"] = "none of these: an ordinary message"
    return out


# ---------------------------------------------------------------------------------------------------- spans

SENT_RE = re.compile(r"(?<=[.!?\n])\s+|\n+")
CLAUSE_RE = re.compile(r"(?<=[,;:])\s+")
MAX_SPANS = 6
SPAN_CHARS = 160


def spans(text: str) -> list[str]:
    """Cut a message into at most six quotable parts: sentences, or clauses when there is one long sentence."""
    t = normalize(text)
    parts = [p.strip() for p in SENT_RE.split(t) if p and p.strip()]
    if len(parts) == 1 and len(t) > 60:
        parts = [p.strip() for p in CLAUSE_RE.split(t) if p.strip()]
    while len(parts) > MAX_SPANS:  # merge the shortest neighbouring pair until six are left
        i = min(range(len(parts) - 1), key=lambda k: len(parts[k]) + len(parts[k + 1]))
        parts[i : i + 2] = [parts[i] + " " + parts[i + 1]]
    return [p if len(p) <= SPAN_CHARS else p[: SPAN_CHARS - 1] + "…" for p in parts]


def span_criteria(parts: list[str], cat: str) -> dict[str, str]:
    out = {f"s{i}": f"the part that reads: {p!r}" for i, p in enumerate(parts, start=1)}
    out["whole"] = "no single part: it is the message as a whole"
    out["none"] = f"no part of it is {LABEL[cat]}"
    return out


# ---------------------------------------------------------------------------------------------------- prepare


def prepare() -> None:
    rng = random.Random(SEED)
    items: list[dict[str, Any]] = []
    # The red-team set: chat-shaped, short, labelled by hand. Rows whose expectation is only a custom rule,
    # or a pre-filter skip, have no category to explain.
    rt = list(csv.DictReader((ROOT / "tests/data/redteam.csv").open(encoding="utf-8")))
    cat_rows = [r for r in rt if any(c in r["expected"].split("|") for c in CATS)]
    clean_rows = [r for r in rt if r["expected"] == "clean"]
    for r in cat_rows + rng.sample(clean_rows, 20):
        items.append({"id": f"rt_{r['id']}", "source": "redteam", "text": r["text"],
                      "topic": r["topic"], "labels": [c for c in r["expected"].split("|") if c in CATS]})
    # The benchmark set, stratified by the category the published v4 run flagged it under, so every category
    # with enough flags is present. Items the source labels as minors are left out: their text would be
    # committed below, and the minors category is exercised by nothing else here either (v4 flagged none).
    src = {json.loads(line)["id"]: json.loads(line)
           for line in (ROOT / "benchmark/data/items.jsonl").open(encoding="utf-8")}
    v4 = [json.loads(line) for line in (ROOT / "benchmark/results/jevmod_v4.jsonl").open(encoding="utf-8")]
    by_cat: dict[str, list[str]] = {c: [] for c in CATS}
    clean: list[str] = []
    for v in v4:
        it = src.get(v["id"])
        if not it or "minors" in it["labels"]:
            continue
        hit = [c for c in CATS if v["scores"].get(c, 0) >= DEFAULT_THRESHOLDS[c]]
        if hit:
            by_cat[max(hit, key=lambda c: v["scores"][c])].append(v["id"])
        elif max(v["scores"].values(), default=0) < 0.2:
            clean.append(v["id"])
    picked = []
    for c, ids in by_cat.items():
        picked += rng.sample(ids, min(12, len(ids)))
    picked += rng.sample(clean, 135 - len(items) - len(picked))
    for i in picked:
        it = src[i]
        items.append({"id": i, "source": it["source"], "text": it["text"][:MAX_CHARS],
                      "topic": "", "labels": it["labels"]})
    rng.shuffle(items)
    assert len(items) % BATCH == 0, len(items)
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "dataset.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{len(items)} items -> results/dataset.jsonl")


# ---------------------------------------------------------------------------------------------------- judge


class Recording:
    """Wraps the real client: records the raw request and answers, tokens and latency; optionally appends
    arm B's inline Choice to the questions Judge built, touching nothing Judge put there."""

    def __init__(self, inner: Any, inline: bool) -> None:
        self.inner, self.inline = inner, inline
        self.last: dict[str, Any] = {}

    def system_one(self, state: dict[str, Any], questions: dict[str, Any]) -> Any:
        qs = dict(questions)
        if self.inline:
            crit = inline_criteria()
            for i in range(1, len(state["messages"])):  # m0 is Judge's filler and is never explained
                qs[f"why_{i}"] = Choice(
                    instructions=f"Which of these best describes what a moderator would object to in "
                    f"`messages.m{i}.text`? Pick `nothing` if it is an ordinary message.",
                    criteria=crit,
                )
        t = time.perf_counter()
        resp = self.inner.system_one(state=state, questions=qs)
        u = resp.usage
        self.last = {"ms": round((time.perf_counter() - t) * 1000), "model": resp.model,
                     "in": u.input_tokens or 0, "out": u.output_tokens or 0, "answers": resp.answers}
        return resp


def flagged(scores: dict[str, float]) -> list[str]:
    return [c for c in CATS if scores.get(c, 0) >= DEFAULT_THRESHOLDS[c]]


def _answer(a: Any) -> dict[str, Any]:
    return {"choice": a.choice, "confidence": a.confidence, "probabilities": a.probabilities}


def judge() -> None:
    items = [json.loads(line) for line in (RESULTS / "dataset.jsonl").open(encoding="utf-8")]
    out = RESULTS / "judge.jsonl"
    done = {(r["arm"], r["batch"]) for r in map(json.loads, out.open(encoding="utf-8"))} if out.exists() else set()
    spent = 0
    with out.open("a", encoding="utf-8") as f:
        for b in range(0, len(items), BATCH):
            chunk = items[b : b + BATCH]
            msgs = [Message(it["id"], it["text"], channel_topic=it["topic"]) for it in chunk]
            for arm in ("A", "B", "A2"):
                if (arm, b // BATCH) in done:
                    continue
                j = Judge()  # a fresh Judge per arm: an empty cache, so every arm really asks
                rec = Recording(j.client, inline=arm == "B")
                j.client = rec  # type: ignore[assignment]
                # No padding, so every position after m0 is a judged message, numbered in the order
                # Judge judged them; a message Judge skips takes no position, so `why_{i}` counts only
                # judged verdicts rather than positions in the chunk.
                verdicts = j.judge(msgs, CATS)
                spent += rec.last.get("in", 0)
                i = 0
                for it, v in zip(chunk, verdicts, strict=True):
                    i += v.judged
                    row = {"arm": arm, "batch": b // BATCH, "id": it["id"], "judged": v.judged,
                           "reason": v.reason, "scores": v.scores, "flagged": flagged(v.scores),
                           "req_in": rec.last.get("in"), "req_out": rec.last.get("out"),
                           "req_ms": rec.last.get("ms"), "req_n": len(chunk), "model": rec.last.get("model")}
                    if arm == "B" and v.judged and f"why_{i}" in rec.last["answers"]:
                        row["why"] = _answer(rec.last["answers"][f"why_{i}"])
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(f"batch {b // BATCH} {arm}: {rec.last.get('in')} in / {rec.last.get('out')} out, "
                      f"{rec.last.get('ms')} ms; run {spent:,} tokens ${spent * USD_PER_M / 1e6:.4f}")
                if spent > MAX_TOKENS:
                    sys.exit("stopped: token budget")


# ---------------------------------------------------------------------------------------------------- companion


def companion_questions(k: str, cat: str, parts: list[str]) -> dict[str, Any]:
    path = f"messages.{k}"
    qs: dict[str, Any] = {
        f"reason_{k}": Choice(
            instructions=f"A moderation system flagged `{path}.text` as {LABEL[cat]}. Which of these is the main "
            f"thing in it that is {LABEL[cat]}? If nothing in it is, say so.",
            criteria=reason_criteria(cat),
        ),
    }
    if len(parts) > 1:
        qs[f"span_{k}"] = Choice(
            instructions=f"A moderation system flagged `{path}.text` as {LABEL[cat]}. Which part of it is the one "
            f"a moderator should read first to see why?",
            criteria=span_criteria(parts, cat),
        )
    return qs


def companion() -> None:
    """Arm C, for the messages arm A flagged. Each gets its top flagged category (the one the policy would act
    on: `decide()` ties severity to the higher probability, and every default action here is flag)."""
    items = {json.loads(line)["id"]: json.loads(line) for line in (RESULTS / "dataset.jsonl").open(encoding="utf-8")}
    rows = [r for r in map(json.loads, (RESULTS / "judge.jsonl").open(encoding="utf-8")) if r["arm"] == "A"]
    out = RESULTS / "companion.jsonl"
    done = {(r["mode"], r["id"]) for r in map(json.loads, out.open(encoding="utf-8"))} if out.exists() else set()
    client = Judge().client
    spent = 0

    def ask(group: list[dict[str, Any]], mode: str, f: Any) -> None:
        nonlocal spent
        state: dict[str, Any] = {"messages": {}}
        qs: dict[str, Any] = {}
        meta = []
        for n, r in enumerate(group, start=1):
            it, k = items[r["id"]], f"m{n}"
            cat = max(r["flagged"] or CATS, key=lambda c: r["scores"][c])
            parts = spans(it["text"])
            state["messages"][k] = {"text": normalize(it["text"]), "channel_topic": it["topic"] or "general chat"}
            qs.update(companion_questions(k, cat, parts))
            meta.append((r, k, cat, parts))
        t = time.perf_counter()
        resp = client.system_one(state=state, questions=qs)
        ms = round((time.perf_counter() - t) * 1000)
        spent += resp.usage.input_tokens or 0
        for r, k, cat, parts in meta:
            row = {"mode": mode, "id": r["id"], "batch": r["batch"], "category": cat, "score": r["scores"][cat],
                   "spans": parts, "reason": _answer(resp.answers[f"reason_{k}"]),
                   "span": _answer(resp.answers[f"span_{k}"]) if f"span_{k}" in resp.answers else None,
                   "req_in": resp.usage.input_tokens, "req_out": resp.usage.output_tokens, "req_ms": ms,
                   "req_n": len(group), "model": resp.model}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        print(f"{mode} batch {group[0]['batch']} n={len(group)}: {resp.usage.input_tokens} in, {ms} ms; "
              f"run {spent:,} tokens ${spent * USD_PER_M / 1e6:.4f}")

    hits = [r for r in rows if r["flagged"]]
    with out.open("a", encoding="utf-8") as f:
        for b in sorted({r["batch"] for r in hits}):
            group = [r for r in hits if r["batch"] == b]
            if not all(("batched", r["id"]) in done for r in group):
                ask(group, "batched", f)
        for r in hits:
            if ("single", r["id"]) not in done:
                ask([r], "single", f)
            if spent > MAX_TOKENS:
                sys.exit("stopped: token budget")
        # The control: messages nobody flagged, labelled clean by their source and scoring under 0.5 on
        # everything, sent through the same single-mode request as if they had been flagged under their
        # highest-scoring category, which is the category a false positive on them would most likely carry.
        # It asks whether the companion can say `not_it`, or whether it finds a reason for any flag it is given.
        ctrl = [r for r in rows if r["judged"] and not r["flagged"] and not items[r["id"]]["labels"]
                and max(r["scores"].values()) < 0.5]
        for r in ctrl:
            if ("control", r["id"]) not in done:
                ask([r], "control", f)
        # Every flagged category, not only the top one. Added after the hand reading: three of the 30 explained
        # spam on a message that was also flagged scam (a tie at 0.96 once), and the spam reason for a phishing
        # link reads as "advertises a product". One request per message, a reason and a span per category.
        for r in hits:
            if ("all", r["id"]) in done:
                continue
            it = items[r["id"]]
            parts = spans(it["text"])
            state = {"messages": {"m1": {"text": normalize(it["text"]),
                                         "channel_topic": it["topic"] or "general chat"}}}
            qs: dict[str, Any] = {}
            for cat in r["flagged"]:
                qs.update({f"{k}__{cat}": q for k, q in companion_questions("m1", cat, parts).items()})
            t = time.perf_counter()
            resp = client.system_one(state=state, questions=qs)
            ms = round((time.perf_counter() - t) * 1000)
            spent += resp.usage.input_tokens or 0
            per_cat = {cat: {"reason": _answer(resp.answers[f"reason_m1__{cat}"]),
                             "span": _answer(resp.answers[f"span_m1__{cat}"])
                             if f"span_m1__{cat}" in resp.answers else None}
                       for cat in r["flagged"]}
            f.write(json.dumps({"mode": "all", "id": r["id"], "batch": r["batch"], "categories": per_cat,
                                "scores": {c: r["scores"][c] for c in r["flagged"]}, "spans": parts,
                                "req_in": resp.usage.input_tokens, "req_out": resp.usage.output_tokens,
                                "req_ms": ms, "req_n": 1, "model": resp.model}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"all {r['id']} ({len(r['flagged'])} categories): {resp.usage.input_tokens} in, {ms} ms")


# ---------------------------------------------------------------------------------------------------- hand reading


def render(row: dict[str, Any]) -> str:
    cat, code = row["category"], row["reason"]["choice"]
    text = reason_criteria(cat)[code]
    line = f"{LABEL[cat]} ({row['score']:.2f}): {text}"
    sp = row["span"]
    if sp and sp["choice"].startswith("s"):
        line += f'. Read: "{row["spans"][int(sp["choice"][1:]) - 1]}"'
    elif sp:
        line += f" [span: {sp['choice']}]"
    return line


def sheet() -> None:
    """The 30 read by hand: a seeded sample of single-mode rationales, the mode JEV-16 would ship."""
    items = {json.loads(line)["id"]: json.loads(line) for line in (RESULTS / "dataset.jsonl").open(encoding="utf-8")}
    rows = [r for r in map(json.loads, (RESULTS / "companion.jsonl").open(encoding="utf-8")) if r["mode"] == "single"]
    pick = random.Random(SEED).sample(rows, min(30, len(rows)))
    lines = ["# The 30 rationales read by hand", "",
             "Single-mode companion output, seeded sample. Verdicts are in `handread.jsonl`.", ""]
    for n, r in enumerate(pick, start=1):
        lines += [f"## {n}. `{r['id']}` (labels: {', '.join(items[r['id']]['labels']) or 'clean'})", "",
                  "> " + normalize(items[r["id"]]["text"])[:MAX_CHARS].replace("\n", " "), "",
                  f"**Shown:** {render(r)}", "",
                  f"reason p={r['reason']['probabilities'][r['reason']['choice']]:.2f}"
                  + (f", span p={r['span']['probabilities'][r['span']['choice']]:.2f}" if r["span"] else ""), ""]
    (RESULTS / "handread.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(pick)} -> results/handread.md")


# ---------------------------------------------------------------------------------------------------- report


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def report() -> None:
    items = {json.loads(line)["id"]: json.loads(line) for line in (RESULTS / "dataset.jsonl").open(encoding="utf-8")}
    J = [json.loads(line) for line in (RESULTS / "judge.jsonl").open(encoding="utf-8")]
    C = [json.loads(line) for line in (RESULTS / "companion.jsonl").open(encoding="utf-8")]
    arm = {a: {r["id"]: r for r in J if r["arm"] == a} for a in ("A", "A2", "B")}
    judged = [i for i in arm["A"] if arm["A"][i]["judged"] and arm["B"][i]["judged"] and arm["A2"][i]["judged"]]
    models = sorted({r["model"] for r in J + C if r.get("model")})
    print(f"items {len(items)}, judged in all arms {len(judged)}, model {models}")

    print("\n### Score shift: inline Choice (B) and a plain repeat (A2), each against A\n")
    print("| comparison | pairs | mean abs | p95 | max | share > 0.03 | messages whose flag set changed |")
    print("|---|---|---|---|---|---|---|")
    for other in ("A2", "B"):
        d = [abs(arm[other][i]["scores"][c] - arm["A"][i]["scores"][c]) for i in judged for c in CATS]
        flips = sum(set(arm[other][i]["flagged"]) != set(arm["A"][i]["flagged"]) for i in judged)
        print(f"| {other} vs A | {len(d)} | {statistics.mean(d):.4f} | {pct(d, .95):.3f} | {max(d):.2f} | "
              f"{sum(x > .03 for x in d) / len(d):.1%} | {flips} of {len(judged)} |")
    d2 = [abs(arm["B"][i]["scores"][c] - arm["A2"][i]["scores"][c]) for i in judged for c in CATS]
    print(f"| B vs A2 | {len(d2)} | {statistics.mean(d2):.4f} | {pct(d2, .95):.3f} | {max(d2):.2f} | "
          f"{sum(x > .03 for x in d2) / len(d2):.1%} | "
          f"{sum(set(arm['B'][i]['flagged']) != set(arm['A2'][i]['flagged']) for i in judged)} of {len(judged)} |")

    def per_req(rows: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
        return {r[key]: r for r in rows}

    print("\n### Tokens, cost and latency per request kind\n")
    print(f"Cost at ${USD_PER_M}/M input tokens, the jev-1.13.0 list price. Output tokens are free "
          "(docs.typesafe.ai/models), so they are shown and not priced.\n")
    print("| request | requests | messages explained or judged | input tok / msg | output tok / msg | "
          "$ / 1,000 msgs | latency p50 | latency p95 |")
    print("|---|---|---|---|---|---|---|---|")
    reqs: dict[str, list[dict[str, Any]]] = {}
    for a in ("A", "B", "A2"):
        reqs[f"judge {a}"] = list(per_req([r for r in J if r["arm"] == a], "batch").values())
    reqs["companion batched"] = list(per_req([r for r in C if r["mode"] == "batched"], "batch").values())
    reqs["companion single"] = [r for r in C if r["mode"] == "single"]
    reqs["companion single, every flagged category"] = [r for r in C if r["mode"] == "all"]
    # A judge request's `req_n` is the chunk; a message Judge skipped is in the chunk but not in the request.
    n_judged = {f"judge {a}": sum(r["judged"] for r in J if r["arm"] == a) for a in ("A", "B", "A2")}
    per_msg: dict[str, float] = {}
    for name, rs in reqs.items():
        n = n_judged.get(name) or sum(r["req_n"] for r in rs)
        tin, tout = sum(r["req_in"] for r in rs), sum(r["req_out"] or 0 for r in rs)
        per_msg[name] = tin / n
        ms = [r["req_ms"] for r in rs]
        print(f"| {name} | {len(rs)} | {n} | {tin / n:,.0f} | {tout / n:,.1f} | ${tin / n * 1000 * USD_PER_M / 1e6:.4f}"
              f" | {pct(ms, .5):,} ms | {pct(ms, .95):,} ms |")
    med = {a: statistics.median(r["req_ms"] for r in reqs[f"judge {a}"]) for a in ("A", "B", "A2")}
    print(f"\nWith 15 requests per judge arm the p95 is the slowest request. A and A2 are the same request and differ "
          f"by {abs(med['A'] - med['A2']):,.0f} ms at the median; B is {med['B'] - med['A']:+,.0f} ms from A, so "
          "the inline Choice's latency cost is not resolved by this run beyond 'small'.")
    ctrl_in = sum(r["req_in"] for r in C if r["mode"] == "control")
    total = sum(r["req_in"] for rs in reqs.values() for r in rs) + ctrl_in
    print(f"Total spend for this experiment, the {sum(r['mode'] == 'control' for r in C)} control requests included: "
          f"{total:,} input tokens = ${total * USD_PER_M / 1e6:.4f}")

    print("\n### Flag rate in arm A, and what the companion costs per judged message\n")
    fl = [i for i in judged if arm["A"][i]["flagged"]]
    print(f"Arm A flagged {len(fl)} of {len(judged)} ({len(fl) / len(judged):.1%}); this set is enriched on purpose.")
    per_k = 1000 * USD_PER_M / 1e6  # dollars per 1,000 messages for each input token per message
    a_msg = per_msg["judge A"]
    inl = per_msg["judge B"] - per_msg["judge A"]
    s_in, x_in = per_msg["companion single"], per_msg["companion single, every flagged category"]
    # Arm A is the cheapest judgment there is: nine real messages sharing one request. Production pads a quiet
    # channel's small batch to ten positions (jevmod/core/service.py), so a message judged alone pays for a whole
    # ten-position request, which arm A's full requests measure. Both are shown, so the share is a range.
    full = {b for b in {r["batch"] for r in J} if all(r["judged"] for r in J if r["arm"] == "A" and r["batch"] == b)}
    pad = statistics.mean(r["req_in"] for r in reqs["judge A"] if r["batch"] in full)
    print(f"Tokens per judged message: judging costs {a_msg:,.0f} in a full batch of nine (arm A) and {pad:,.0f} "
          f"for a message padded alone (the mean of arm A's {len(full)} ten-position requests). The companion is "
          "priced at assumed flag rates; the inline Choice is paid on every judged message.\n")
    print("| flag rate | companion, top category | companion, every flagged category | inline Choice |")
    print("|---|---|---|---|")
    for rate in (0.01, 0.02, 0.05, 0.10):
        cells = [rate * s_in, rate * x_in, inl]
        print(f"| {rate:.0%} | " + " | ".join(
            f"{t:,.0f} tok, ${t * per_k:.5f} per 1,000, +{t / a_msg:.1%} full / +{t / pad:.1%} padded"
            for t in cells) + " |")

    cut = "…"
    trunc = [r for r in reqs["companion single"] if any(p.endswith(cut) for p in r["spans"])]
    chose = [r for r in trunc if r["span"] and r["span"]["choice"].startswith("s")
             and r["spans"][int(r["span"]["choice"][1:]) - 1].endswith(cut)]
    print(f"\nSpans cut at {SPAN_CHARS} characters: {len(trunc)} of {len(reqs['companion single'])} flagged messages "
          f"had at least one, and on {len(chose)} the chosen span was a cut one: {', '.join(r['id'] for r in chose)}.")

    print("\n### Agreement\n")
    single = {r["id"]: r for r in C if r["mode"] == "single"}
    batched = {r["id"]: r for r in C if r["mode"] == "batched"}
    both = [i for i in single if i in batched]
    same_r = sum(single[i]["reason"]["choice"] == batched[i]["reason"]["choice"] for i in both)
    same_s = [single[i]["span"]["choice"] == batched[i]["span"]["choice"] for i in both if single[i]["span"]]
    print(f"- companion reason code, single vs batched: same on {same_r} of {len(both)}")
    print(f"- companion span, single vs batched: same on {sum(same_s)} of {len(same_s)}")
    for mode, rows in (("single", single), ("batched", batched)):
        dis = [i for i, r in rows.items() if r["reason"]["choice"] == "not_it"]
        oth = [i for i, r in rows.items() if r["reason"]["choice"] == "other"]
        print(f"- {mode}: reason `not_it` (the companion disagrees with the flag) on {len(dis)} of {len(rows)}; "
              f"`other` on {len(oth)}")
    ctrl = [r for r in C if r["mode"] == "control"]
    if ctrl:
        from collections import Counter
        print(f"- control (clean, unflagged, sent as if flagged): `not_it` on "
              f"{sum(r['reason']['choice'] == 'not_it' for r in ctrl)} of {len(ctrl)}; span `none` on "
              f"{sum(bool(r['span']) and r['span']['choice'] == 'none' for r in ctrl)} of "
              f"{sum(bool(r['span']) for r in ctrl)}; categories {dict(Counter(r['category'] for r in ctrl))}")
        p_not = [r["reason"]["probabilities"]["not_it"] for r in ctrl]
        p_flag = [single[i]["reason"]["probabilities"]["not_it"] for i in single]
        print(f"- p(not_it): control median {statistics.median(p_not):.2f}, max {max(p_not):.2f}; "
              f"real flags median {statistics.median(p_flag):.2f}, max {max(p_flag):.2f}")
    inl = [i for i in fl if "why" in arm["B"][i]]
    agree = sum(arm["B"][i]["why"]["choice"].split("__")[0] == single[i]["category"] for i in inl if i in single)
    nothing = sum(arm["B"][i]["why"]["choice"] == "nothing" for i in inl)
    print(f"- inline Choice on messages A flagged: names the same category as the flag on {agree} of {len(inl)}; "
          f"says `nothing` on {nothing}")
    same_code = sum(arm["B"][i]["why"]["choice"] == f"{single[i]['category']}__{single[i]['reason']['choice']}"
                    for i in inl if i in single)
    print(f"- inline code equals the single companion code on {same_code} of {len(inl)}")
    in_flag = [i for i in inl if arm["B"][i]["why"]["choice"].split("__")[0] in arm["A"][i]["flagged"]]
    to_scam = [i for i in inl if i in single and single[i]["category"] == "spam"
               and arm["B"][i]["why"]["choice"].startswith("scam__") and "scam" in arm["A"][i]["flagged"]]
    print(f"- inline names a category that crossed its line on {len(in_flag)} of {len(inl)}; of the differences from "
          f"the companion's top category, {len(to_scam)} pick scam where the top score was spam: {', '.join(to_scam)}")
    hs = RESULTS / "handread.jsonl"
    if hs.exists():
        H0 = {json.loads(line)["id"] for line in hs.open(encoding="utf-8")}
        cut_read = [i for i in H0 if any(p.endswith("…") for p in single[i]["spans"])]
        print(f"- hand-read items with a cut part: {len(cut_read)} of {len(H0)} ({', '.join(sorted(cut_read))})")
    for mode, rows in (("single", single),):
        lab = [i for i in rows if items[i]["labels"]]
        unl = [i for i in rows if not items[i]["labels"]]
        print(f"- {mode}, `not_it` on flags the source labels as some category: "
              f"{sum(rows[i]['reason']['choice'] == 'not_it' for i in lab)} of {len(lab)}; "
              f"on flags the source labels clean: {sum(rows[i]['reason']['choice'] == 'not_it' for i in unl)} of {len(unl)}")

    allc = [r for r in C if r["mode"] == "all"]
    if allc:
        from collections import Counter
        ncat = [len(r["categories"]) for r in allc]
        print(f"\n### Every flagged category\n\n{sum(n > 1 for n in ncat)} of {len(allc)} flagged messages carry "
              f"more than one category ({dict(Counter(ncat))} categories per message).")
        pair = [r for r in allc if {"spam", "scam"} <= set(r["categories"])]
        print(f"- flagged both spam and scam: {len(pair)}; the scam reason on them: "
              f"{dict(Counter(r['categories']['scam']['reason']['choice'] for r in pair))}")
        print(f"- the spam reason on them: {dict(Counter(r['categories']['spam']['reason']['choice'] for r in pair))}")
        nt = sum(v["reason"]["choice"] == "not_it" for r in allc for v in r["categories"].values())
        print(f"- `not_it` across all {sum(ncat)} (message, category) pairs: {nt}")
        for r in allc:
            if items[r["id"]]["labels"] == [] or any(v["reason"]["choice"] == "not_it" for v in r["categories"].values()):
                print(f"  - `{r['id']}` labels {items[r['id']]['labels']}: "
                      + ", ".join(f"{c} {r['scores'][c]:.2f} -> {v['reason']['choice']}" for c, v in r["categories"].items()))

    hr = RESULTS / "handread.jsonl"
    if hr.exists():
        H = [json.loads(line) for line in hr.open(encoding="utf-8")]
        single_rows = [r for r in C if r["mode"] == "single"]
        pick = random.Random(SEED).sample(single_rows, min(30, len(single_rows)))
        assert [h["id"] for h in H] == [r["id"] for r in pick], "handread.jsonl is not the sheet's sample, in order"
        print(f"\n### Hand reading ({len(H)})\n")
        for k in ("truthful", "useful"):
            print(f"- {k}: {sum(h[k] for h in H)} of {len(H)}")
        print(f"- both: {sum(h['truthful'] and h['useful'] for h in H)} of {len(H)}")


def main() -> None:
    cmds = {"prepare": prepare, "judge": judge, "companion": companion, "sheet": sheet, "report": report}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(f"usage: python -m benchmark.reasoning.run {{{'|'.join(cmds)}}}")
    cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
