"""Does a line of community state beside the conversation window make verdicts better, worse or no different?

JEV-30, experiment D. JEV-18 (`benchmark/context_quality/REPORT.md`) measured the conversation window. JEV-19
(`odd/decisions/jev-19-context-worth-its-cost.md` in the private repository) budgets 50 of the 550 tokens a
judged message may add to **community state**: what is happening in the channel right now. This run measures
what those 50 tokens buy, on rows written for the purpose, before any detector produces the state in
production (JEV-26, JEV-27 and JEV-70 build those). There is still no labelled multi-party set (JEV-64 has not
merged one), so the rows are constructed and labelled by model authors, and everything here is about them.

**The data** (`data/<category>.jsonl`; spam 70 rows, harassment 75, scam 33; brief in `BRIEF.md`). Two edits
were made by hand after the authors and before any paid call: every `event_neg` row but `harassment-e04` (which
quotes the spam line itself) had the wave's copies or the victim's counts written into its *own* message part,
which describes the closing line, and those were set to 0; and fifteen hard negatives were added where the
message part is high for an innocent reason, because that is where it can hurt: a hype chant many accounts type
at once (`spam-b11`..`b15`), many people congratulating one person (`harassment-b11`..`b15`), and a defender
replying to the target of a pile-on (`harassment-e11`..`e15`).

* **pairs** (`pair_pos`, `pair_neg`): the same topic, lead-up and closing line byte for byte; only the state
  differs. One half is an incident under which a moderator would call the closing a violation (a spam wave
  of copies of this very line, a pile-on at the person it addresses, a scam raid); the other a normal
  channel under which it is innocent. With the window alone both halves are one request, so at most one can
  be right. This is where the state can help, and it is the favourable case by construction.
* **event_neg**: an incident is happening and the closing is innocent (a bystander, the target, someone
  warning about the spam). Can telling the model about an incident make innocent people look guilty?
* **busy_neg**: a normal busy channel (a hype moment, a friendly raid, rate 3x to 15x, no event) and an
  innocent line an over-eager filter might catch. Does a busy channel inflate false positives?
* **control_pos**: a clear violation in a normal channel. Does a calm state talk the model out of it?

**The arms**, every row in all three, two repeats each, arm order shuffled per row, cache off, padding off
(the default since JEV-61), through `ModerationService.moderate` with the lead-up written into its
`ConversationBuffer`, which is production's path:

* `win`: the conversation window only. **What production does today.**
* `chan`: the window plus the state line's channel part (rate, newcomers, flagged counts, open event).
* `full`: the window plus the whole line, channel part and the message's own part (how many near-identical
  copies of this line were just posted and by how many accounts; how many messages the person it addresses
  just received, and from how many users). Rendered by `jevmod.core.context.render_state`, at most 50
  estimated tokens.

**Pre-registered, written and pushed before the paid run:**

1. A row is flagged when its own category is at or over the shipped threshold (`DEFAULT_THRESHOLDS`: spam
   0.85, scam 0.75, harassment 0.75); its score is the mean of its two repeats. Recall over `label: true`
   rows, false-positive rate over `label: false` rows, per category and pooled. Intervals are percentile
   bootstraps over scenarios (a pair is one scenario), 2,000 resamples, fixed seed.
2. A format F (`chan`, `full`) **passes** against `win` when all of these hold:
   a. the pooled gain, (recall change) minus (FPR change), has the lower end of its 97.5% interval above
      zero (two formats tested, so 0.05 / 2);
   b. no category's 95% interval of the gain lies wholly below zero;
   c. **busy-chat guard**: on the `busy_neg` rows, the rows with *any* enabled category over its threshold
      rise by at most 1 against `win`, and the upper end of the 95% interval of the paired mean change in
      the row's own category score is under +0.10;
   d. **bystander guard**: the same two conditions on the `event_neg` rows;
   e. at most 1 `control_pos` row flagged under `win` is lost.
3. **What ships.** If both pass, `chan` (fewer tokens) unless `full` beats `chan` with the lower end of the
   95% interval of the pooled gain above zero, in which case `full`. If one passes, that one. If neither
   passes, the state line does not go on the wire by default.
4. Nothing is dropped after the run. A row the blind labeller disagreed with stays in the primary numbers
   and `report --agreed-only` recomputes without its whole scenario.

    python -m benchmark.community_state.run check    # free: schema, pairs, states, rendered lines
    python -m benchmark.community_state.run blind    # free: the unlabelled file for the blind labeller
    python -m benchmark.community_state.run ask      # paid, about $0.10, resumable, prints the running cost
    python -m benchmark.community_state.run report   # free, every table in REPORT.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import jevmod.core.context as ctx_mod  # noqa: E402
import jevmod.core.service as service_mod  # noqa: E402
from benchmark.context_quality.run import Recorder, _mcnemar  # noqa: E402
from jevmod.core.context import (  # noqa: E402
    EVENT_LEVELS,
    EVENT_TYPES,
    CommunityState,
    ConversationBuffer,
    render_state,
)
from jevmod.core.policy import DEFAULT_THRESHOLDS  # noqa: E402
from jevmod.core.service import ModerationService  # noqa: E402
from jevmod.core.store import Store  # noqa: E402
from jevmod.judge import CATEGORIES, Judge, Message, prefilter  # noqa: E402

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "results" / "raw.jsonl"
BLIND = HERE / "results" / "blind_input.jsonl"
BLIND_KEY = HERE / "results" / "blind_key.json"
BLIND_LABELS = HERE / "results" / "blind_labels.jsonl"
CATS = ("spam", "harassment", "scam")
KINDS = ("pair_pos", "pair_neg", "event_neg", "busy_neg", "control_pos")
ARMS = ("win", "chan", "full")
FORMATS = ("chan", "full")
REPEATS = 2
SEED = 20260929
USD_PER_M = 0.042  # list price per million input tokens, as every other benchmark here
BUDGET_TOKENS = 20_000_000  # abort past this, about $0.84
TENANT = "bench"
BOOT = 2000
STATE_KEYS = {"rate_x", "newcomers_5m", "flagged_5m", "event", "copies_60s", "copies_accounts", "target_5m",
              "target_users"}


def rows() -> list[dict[str, Any]]:
    out = []
    for cat in CATS:
        for line in (DATA / f"{cat}.jsonl").open(encoding="utf-8"):
            if line.strip():
                out.append(json.loads(line))
    return out


def data_hash() -> str:
    h = hashlib.sha256()
    for cat in CATS:
        h.update((DATA / f"{cat}.jsonl").read_bytes())
    return h.hexdigest()


def to_state(s: dict[str, Any]) -> CommunityState:
    ev = s.get("event") or {}
    return CommunityState(
        rate_x=float(s["rate_x"]), newcomers_5m=int(s["newcomers_5m"]),
        flagged_5m=tuple(sorted((str(c), int(k)) for c, k in (s.get("flagged_5m") or {}).items())),
        event=ev.get("type", ""), event_level=ev.get("level", ""),
        copies_60s=int(s["copies_60s"]), copies_accounts=int(s["copies_accounts"]),
        target_5m=int(s["target_5m"]), target_users=int(s["target_users"]),
    )


def line_for(r: dict[str, Any], arm: str) -> str:
    if arm == "win":
        return ""
    return render_state(to_state(r["state"]), tuple(CATEGORIES), message_part=arm == "full")


def check() -> int:
    rs = rows()
    bad: list[str] = []
    ids = [r["id"] for r in rs]
    if len(ids) != len(set(ids)):
        bad.append("duplicate ids")
    by_scn: dict[str, list[dict[str, Any]]] = {}
    for r in rs:
        by_scn.setdefault(r["scenario"], []).append(r)
        if r["category"] not in CATS or r["kind"] not in KINDS:
            bad.append(f"{r['id']}: category or kind")
        if r["label"] != r["kind"].endswith("pos"):
            bad.append(f"{r['id']}: label does not match kind")
        if not 4 <= len(r["lead"]) <= 9 or not all(isinstance(t, str) for t in r["lead"]):
            bad.append(f"{r['id']}: lead")
        if set(r["state"]) != STATE_KEYS:
            bad.append(f"{r['id']}: state keys {sorted(set(r['state']) ^ STATE_KEYS)}")
        ev = r["state"].get("event")
        if ev and (ev.get("type") not in EVENT_TYPES or ev.get("level") not in EVENT_LEVELS):
            bad.append(f"{r['id']}: event {ev}")
        if r["kind"] in ("busy_neg", "control_pos") and ev:
            bad.append(f"{r['id']}: {r['kind']} with an open event")
        if r["kind"] == "event_neg" and not ev:
            bad.append(f"{r['id']}: event_neg without an event")
        for f in (r["state"].get("flagged_5m") or {}):
            if f not in CATEGORIES:
                bad.append(f"{r['id']}: flagged category {f!r} is not one the engine prints")
        if prefilter(Message(r["id"], r["closing"])):
            bad.append(f"{r['id']}: the pre-filter skips the closing")
        for arm in FORMATS:
            if len(line_for(r, arm)) > ctx_mod.STATE_TOKENS * ctx_mod.CHARS_PER_TOKEN:
                bad.append(f"{r['id']}: {arm} line over budget")
    for scn, rr in by_scn.items():
        if rr[0]["kind"].startswith("pair"):
            if sorted(r["kind"] for r in rr) != ["pair_neg", "pair_pos"]:
                bad.append(f"{scn}: not one pos and one neg")
            elif any(rr[0][k] != rr[1][k] for k in ("closing", "topic", "lead")):
                bad.append(f"{scn}: closing, topic or lead differs between the halves")
        elif len(rr) != 1:
            bad.append(f"{scn}: single-row scenario with {len(rr)} rows")
    for cat in CATS:
        print(cat, {k: sum(1 for r in rs if r["category"] == cat and r["kind"] == k) for k in KINDS})
    lens = [len(line_for(r, a)) for r in rs for a in FORMATS]
    print(f"{len(rs)} rows, data sha256 {data_hash()}; state line {min(lens)} to {max(lens)} characters, "
          f"mean {statistics.mean(lens):.0f}")
    for a in FORMATS:
        print(f"  e.g. {a}: {line_for(rs[0], a)}")
    for b in bad:
        print("BAD", b)
    return 1 if bad else 0


def blind() -> None:
    """Shuffled rows with the label, kind and reason removed and ids replaced, the state shown as the full line
    the model would read."""
    rs = rows()
    rng = random.Random(SEED + 7)
    rng.shuffle(rs)
    key = {}
    BLIND.parent.mkdir(exist_ok=True)
    with BLIND.open("w", encoding="utf-8") as f:
        for k, r in enumerate(rs):
            bid = f"b{k:03d}"
            key[bid] = r["id"]
            f.write(json.dumps({"bid": bid, "category": r["category"], "topic": r["topic"], "lead": r["lead"],
                                "closing": r["closing"], "community_state": line_for(r, "full")},
                               ensure_ascii=False) + "\n")
    BLIND_KEY.write_text(json.dumps(key, indent=0), encoding="utf-8")
    print(f"wrote {len(rs)} rows to {BLIND}")


def one(rec: Recorder, r: dict[str, Any], arm: str) -> dict[str, Any]:
    before = len(rec.calls)
    store = Store(":memory:")
    store.set_plan(TENANT, "unlimited")
    svc = ModerationService(store, judge=Judge(client=rec, cache_ttl_s=0))  # type: ignore[arg-type]
    svc.context = ConversationBuffer()
    for text in r["lead"]:
        svc.context.add((TENANT, ""), text)
    m = Message(r["id"], r["closing"], channel_topic=r["topic"],
                community=None if arm == "win" else to_state(r["state"]))
    ctx_mod.STATE_MESSAGE_PART = arm == "full"
    try:
        d = svc.moderate(TENANT, [m])[0]
    finally:
        ctx_mod.STATE_MESSAGE_PART = True
    calls = rec.calls[before:]
    return {
        "id": r["id"], "arm": arm, "scores": {k: round(v, 5) for k, v in d.scores.items()},
        "judged": d.judged, "reason": d.reason, "context_kept": len(m.context), "state_line": line_for(r, arm),
        "sent_state": [c.get("state_line", "") for c in calls],
        "positions": sum(c["positions"] for c in calls),
        "input_tokens": sum(c["input_tokens"] or 0 for c in calls), "requests": len(calls),
        "ms": sum(c["ms"] for c in calls),
    }


class StateRecorder(Recorder):
    """The JEV-18 recorder, also writing down the state line exactly as it went on the wire."""

    def system_one(self, *, state: dict[str, Any], questions: dict[str, Any]) -> Any:
        resp = super().system_one(state=state, questions=questions)
        self.calls[-1]["state_line"] = state["messages"].get("m1", {}).get("community_state", "")
        return resp


def ask() -> None:
    if not ctx_mod.FULL_CONTEXT or service_mod.PAD_BATCH:
        raise SystemExit("run with JEVMOD_FULL_CONTEXT on and JEVMOD_PAD_BATCH off, which are the defaults")
    rs = rows()
    sha = data_hash()
    OUT.parent.mkdir(exist_ok=True)
    done: set[tuple[str, str, int]] = set()
    spent = 0
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            x = json.loads(line)
            if x["data_sha256"] != sha:
                raise SystemExit("results/raw.jsonl was produced from different data; refusing to mix")
            done.add((x["id"], x["arm"], x["repeat"]))
            spent += x["input_tokens"]
    rng = random.Random(SEED)
    rec = StateRecorder()
    todo = [(r, rep) for rep in range(REPEATS) for r in rs]
    with OUT.open("a", encoding="utf-8") as f:
        for k, (r, rep) in enumerate(todo, 1):
            order = list(ARMS)
            rng.shuffle(order)  # drawn even when skipped, so a resumed run keeps the same order
            for arm in order:
                if (r["id"], arm, rep) in done:
                    continue
                x = one(rec, r, arm)
                if x["sent_state"] != [x["state_line"]] * x["requests"]:
                    raise SystemExit(f"{r['id']} {arm}: the line on the wire is not the line rendered")
                x.update(repeat=rep, data_sha256=sha, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
                f.write(json.dumps(x) + "\n")
                f.flush()
                spent += x["input_tokens"]
                if spent > BUDGET_TOKENS:
                    print(f"\nstopped: {spent:,} input tokens is past the budget")
                    return
            print(f"  {k}/{len(todo)}  {spent:,} tok  ${spent * USD_PER_M / 1e6:.4f}", end="\r")
    print(f"\ndone: {spent:,} input tokens, ${spent * USD_PER_M / 1e6:.4f}")


# ---------------------------------------------------------------- report


def _blind_agreement(rs: list[dict[str, Any]], quiet: bool = False) -> dict[str, bool]:
    if not BLIND_LABELS.exists():
        return {}
    key = json.loads(BLIND_KEY.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rs}
    out = {}
    for line in BLIND_LABELS.open(encoding="utf-8"):
        if line.strip():
            x = json.loads(line)
            rid = key[x["bid"]]
            if rid in by_id:
                out[rid] = bool(x["violates"]) == by_id[rid]["label"]
    if not quiet:
        print(f"blind labeller: {len(out)} rows, agrees with the author on {sum(out.values())} "
              f"({100 * sum(out.values()) / max(1, len(out)):.0f}%)")
        for kind in KINDS:
            ks = [r["id"] for r in rs if r["kind"] == kind and r["id"] in out]
            print(f"  {kind}: {sum(out[i] for i in ks)} of {len(ks)}")
        print("  disagrees: " + ", ".join(sorted(i for i, ok in out.items() if not ok)))
    return out


def _load(agreed_only: bool) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, float]], list[Any]]:
    rs = rows()
    raw = [json.loads(line) for line in OUT.open(encoding="utf-8")]
    if agreed_only:
        agree = _blind_agreement(rs, quiet=True)
        drop = {r["scenario"] for r in rs if not agree.get(r["id"], True)}
        rs = [r for r in rs if r["scenario"] not in drop]
    ids = {r["id"] for r in rs}
    per: dict[tuple[str, str], dict[str, list[float]]] = {}
    for x in raw:
        if x["id"] in ids:
            d = per.setdefault((x["id"], x["arm"]), {})
            for c, v in x["scores"].items():
                d.setdefault(c, []).append(v)
    means = {k: {c: statistics.mean(v) for c, v in d.items()} for k, d in per.items()}
    return rs, means, raw


def _s(means: dict[tuple[str, str], dict[str, float]], r: dict[str, Any], arm: str) -> float:
    return means[(r["id"], arm)].get(r["category"], 0.0)


def _flag(means: dict[tuple[str, str], dict[str, float]], r: dict[str, Any], arm: str) -> bool:
    return _s(means, r, arm) >= DEFAULT_THRESHOLDS[r["category"]]


def _any(means: dict[tuple[str, str], dict[str, float]], r: dict[str, Any], arm: str) -> bool:
    return any(v >= DEFAULT_THRESHOLDS.get(c, 2.0) for c, v in means[(r["id"], arm)].items())


def _rates(rs: list[dict[str, Any]], means: Any, arm: str) -> tuple[float, float]:
    pos = [r for r in rs if r["label"]]
    neg = [r for r in rs if not r["label"]]
    rec = sum(_flag(means, r, arm) for r in pos) / len(pos) if pos else float("nan")
    fpr = sum(_flag(means, r, arm) for r in neg) / len(neg) if neg else float("nan")
    return rec, fpr


def _gain(rs: list[dict[str, Any]], means: Any, arm: str, base: str) -> float:
    r1, f1 = _rates(rs, means, arm)
    r0, f0 = _rates(rs, means, base)
    return (r1 - r0) - (f1 - f0)


def _boot(rs: list[dict[str, Any]], fn: Any, alpha: float = 0.05) -> tuple[float, float]:
    scn: dict[str, list[dict[str, Any]]] = {}
    for r in rs:
        scn.setdefault(r["scenario"], []).append(r)
    keys = sorted(scn)
    rng = random.Random(SEED)
    vals = []
    for _ in range(BOOT):
        v = fn([r for k in (rng.choice(keys) for _ in keys) for r in scn[k]])
        if v == v:
            vals.append(v)
    vals.sort()
    return vals[int(alpha / 2 * len(vals))], vals[int((1 - alpha / 2) * len(vals)) - 1]


def _auroc(rs: list[dict[str, Any]], means: Any, arm: str) -> float:
    pos = [_s(means, r, arm) for r in rs if r["label"]]
    neg = [_s(means, r, arm) for r in rs if not r["label"]]
    if not pos or not neg:
        return float("nan")
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))


def _pc(x: float) -> str:
    return f"{100 * x:.0f}%"


def report(agreed_only: bool) -> None:
    rs, means, raw = _load(agreed_only)
    print(f"{len(rs)} rows, {len(raw)} judgements, data sha256 {raw[0]['data_sha256']}")
    bad = [x for x in raw if not x["judged"]]
    print(f"not judged: {len(bad)} {sorted({x['reason'] for x in bad})}\n")
    if not agreed_only:
        _blind_agreement(rows())
        print()
    groups = [(c, [r for r in rs if r["category"] == c]) for c in CATS] + [("all", rs)]

    print("## Recall and false-positive rate at the shipped thresholds\n")
    print("| category | arm | recall | 95% CI | FPR | 95% CI | AUROC |")
    print("|---|---|---|---|---|---|---|")
    for name, g in groups:
        npos, nneg = sum(r["label"] for r in g), sum(not r["label"] for r in g)
        for arm in ARMS:
            rec, fpr = _rates(g, means, arm)
            rlo, rhi = _boot(g, lambda s, a=arm: _rates(s, means, a)[0])
            flo, fhi = _boot(g, lambda s, a=arm: _rates(s, means, a)[1])
            print(f"| {name} | {arm} | {_pc(rec)} of {npos} | {100 * rlo:.0f} to {100 * rhi:.0f} | {_pc(fpr)} of "
                  f"{nneg} | {100 * flo:.0f} to {100 * fhi:.0f} | {_auroc(g, means, arm):.3f} |")

    print("\n## Pre-registered criterion, each format against `win`\n")
    verdicts: dict[str, bool] = {}
    for f in FORMATS:
        print(f"### `{f}`\n")
        print("| group | recall change | FPR change | gain | 95% CI | 97.5% CI | right only with | only without "
              "| McNemar p |")
        print("|---|---|---|---|---|---|---|---|---|")
        hurts = []
        pooled_lo = 0.0
        for name, g in groups:
            r1, f1 = _rates(g, means, f)
            r0, f0 = _rates(g, means, "win")
            lo, hi = _boot(g, lambda s, a=f: _gain(s, means, a, "win"))
            blo, bhi = _boot(g, lambda s, a=f: _gain(s, means, a, "win"), alpha=0.025)
            b = sum(_flag(means, r, f) == r["label"] and _flag(means, r, "win") != r["label"] for r in g)
            c = sum(_flag(means, r, "win") == r["label"] and _flag(means, r, f) != r["label"] for r in g)
            print(f"| {name} | {100 * (r1 - r0):+.0f} | {100 * (f1 - f0):+.0f} | {100 * _gain(g, means, f, 'win'):+.0f}"
                  f" | {100 * lo:+.0f} to {100 * hi:+.0f} | {100 * blo:+.0f} to {100 * bhi:+.0f} | {b} | {c} | "
                  f"{_mcnemar(b, c):.3g} |")
            if name == "all":
                pooled_lo = blo
            elif hi < 0:
                hurts.append(name)
        ok_a = pooled_lo > 0
        ok_b = not hurts
        guards = {}
        for kind in ("busy_neg", "event_neg"):
            k = [r for r in rs if r["kind"] == kind]
            n_f = sum(_any(means, r, f) for r in k)
            n_w = sum(_any(means, r, "win") for r in k)
            diff = statistics.mean(_s(means, r, f) - _s(means, r, "win") for r in k)
            dlo, dhi = _boot(k, lambda s, a=f: statistics.mean(_s(means, r, a) - _s(means, r, "win") for r in s))
            guards[kind] = n_f - n_w <= 1 and dhi < 0.10
            print(f"\n{kind}: any category flagged {n_f} of {len(k)} with `{f}`, {n_w} with `win`; mean change in the "
                  f"row's category {diff:+.3f} [{dlo:+.3f}, {dhi:+.3f}] -> {'pass' if guards[kind] else 'FAIL'}")
        ctl = [r for r in rs if r["kind"] == "control_pos"]
        lost = sum(_flag(means, r, "win") and not _flag(means, r, f) for r in ctl)
        ok_e = lost <= 1
        print(f"control_pos lost against `win`: {lost} of {sum(_flag(means, r, 'win') for r in ctl)} flagged")
        verdicts[f] = ok_a and ok_b and guards["busy_neg"] and guards["event_neg"] and ok_e
        print(f"\n(a) pooled 97.5% lower end {100 * pooled_lo:+.1f} -> {'pass' if ok_a else 'FAIL'}; (b) categories "
              f"hurting: {hurts or 'none'}; (c) busy {'pass' if guards['busy_neg'] else 'FAIL'}; (d) bystanders "
              f"{'pass' if guards['event_neg'] else 'FAIL'}; (e) controls {'pass' if ok_e else 'FAIL'}. "
              f"**`{f}` {'passes' if verdicts[f] else 'does not pass'}.**\n")
    lo, hi = _boot(rs, lambda s: _gain(s, means, "full", "chan"))
    print(f"`full` against `chan`, pooled gain {100 * _gain(rs, means, 'full', 'chan'):+.0f} points "
          f"[{100 * lo:+.0f}, {100 * hi:+.0f}]")
    passing = [f for f in FORMATS if verdicts[f]]
    ship = ("full" if lo > 0 else "chan") if len(passing) == 2 else (passing[0] if passing else "none")
    print(f"**Ships by rule 3: {ship}.**\n")

    print("## By kind of row (the row's own category at or over its threshold)\n")
    print("| category | kind | rows | " + " | ".join(ARMS) + " | mean score " + " / ".join(ARMS) + " |")
    print("|---|---|---|" + "---|" * len(ARMS) + "---|")
    for name, g in groups:
        for kind in KINDS:
            k = [r for r in g if r["kind"] == kind]
            if not k:
                continue
            cells = [str(sum(_flag(means, r, a) for r in k)) for a in ARMS]
            ms = " / ".join(f"{statistics.mean(_s(means, r, a) for r in k):.2f}" for a in ARMS)
            print(f"| {name} | {kind} | {len(k)} | " + " | ".join(cells) + f" | {ms} |")

    print("\n## Negatives with any enabled category over its threshold\n")
    print("| kind | rows | " + " | ".join(ARMS) + " |")
    print("|---|---|" + "---|" * len(ARMS))
    for kind in ("pair_neg", "event_neg", "busy_neg"):
        k = [r for r in rs if r["kind"] == kind]
        print(f"| {kind} | {len(k)} | " + " | ".join(str(sum(_any(means, r, a) for r in k)) for a in ARMS) + " |")

    print("\n## Pairs with both halves right\n")
    print("| category | " + " | ".join(ARMS) + " |")
    print("|---|" + "---|" * len(ARMS))
    for name, g in groups:
        scn: dict[str, list[dict[str, Any]]] = {}
        for r in g:
            if r["kind"].startswith("pair"):
                scn.setdefault(r["scenario"], []).append(r)
        full = [v for v in scn.values() if len(v) == 2]
        print(f"| {name} | " + " | ".join(
            f"{sum(all(_flag(means, r, a) == r['label'] for r in v) for v in full)} of {len(full)}" for a in ARMS)
            + " |")

    print("\n## Repeat noise: rows whose verdict flips between the two repeats\n")
    by_id = {r["id"]: r for r in rs}
    rep: dict[tuple[str, str], list[float]] = {}
    for x in raw:
        if x["id"] in by_id:
            rep.setdefault((x["id"], x["arm"]), []).append(x["scores"].get(by_id[x["id"]]["category"], 0.0))
    for arm in ARMS:
        pr = [(i, v) for (i, a), v in rep.items() if a == arm and len(v) == 2]
        flips = sum((v[0] >= DEFAULT_THRESHOLDS[by_id[i]["category"]]) != (v[1] >= DEFAULT_THRESHOLDS[by_id[i]["category"]])
                    for i, v in pr)
        print(f"- {arm}: {flips} of {len(pr)} flip; mean abs difference {statistics.mean(abs(v[0] - v[1]) for _, v in pr):.3f}")

    print("\n## Cost, billed input tokens per judged message\n")
    print("| arm | tokens | x win | added tokens | state line chars, mean / max | ms median | ms p95 |")
    print("|---|---|---|---|---|---|---|")
    base = statistics.mean(x["input_tokens"] for x in raw if x["arm"] == "win" and x["id"] in by_id)
    for arm in ARMS:
        xs = [x for x in raw if x["arm"] == arm and x["id"] in by_id]
        tok = statistics.mean(x["input_tokens"] for x in xs)
        ln = [len(x["state_line"]) for x in xs]
        ms = sorted(x["ms"] for x in xs if x["judged"])
        print(f"| {arm} | {tok:,.0f} | {tok / base:.3f}x | {tok - base:+.0f} | {statistics.mean(ln):.0f} / {max(ln)} "
              f"| {statistics.median(ms):.0f} | {ms[int(0.95 * len(ms))]:.0f} |")
    total = sum(x["input_tokens"] for x in raw)
    print(f"\nwhole run: {total:,} input tokens, ${total * USD_PER_M / 1e6:.3f}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("check", "blind", "ask", "report"))
    ap.add_argument("--agreed-only", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check()
    if a.cmd == "blind":
        blind()
    elif a.cmd == "ask":
        ask()
    else:
        report(a.agreed_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
