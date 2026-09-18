"""Regression set from the adversarial red team (tests/data/redteam.csv): 98 labelled messages across evasion,
languages, false positives, injection, custom rules and length. Real Jev calls; a handful of requests.

Two kinds of checks: hard ones for the failures we fixed (batch cross-talk, unicode evasion, CJK pre-filter) and a
scoreboard that must not regress below the red team's own numbers.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from jevmod.core import DEFAULT_THRESHOLDS, Policy, decide
from jevmod.judge import CATEGORIES, Judge, Message, normalize, prefilter

pytestmark = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")

DATA = Path(__file__).parent / "data" / "redteam.csv"
CATS = list(CATEGORIES)
TOPIC = "gaming community general chat"


def rows(block: str | None = None) -> list[dict[str, str]]:
    with DATA.open(encoding="utf-8-sig") as f:
        out = [r for r in csv.DictReader(f) if block is None or r["block"] == block]
    return out


def msg(r: dict[str, str]) -> Message:
    return Message(r["id"], r["text"], channel_topic=r.get("topic") or TOPIC)


# ------------------------------------------------------------------ offline: normalisation and pre-filter
def test_normalize_defeats_fullwidth_enclosed_and_zalgo():
    assert (
        normalize("ＦＲＥＥ ＮＩＴＲＯ ｃｌａｉｍ ａｔ ｄｉｓｃｏｒｄ．ｇｇ／ｆｗ")
        == "FREE NITRO claim at discord.gg/fw"
    )
    assert normalize("Ⓕⓡⓔⓔ ⓝⓘⓣⓡⓞ") == "Free nitro"
    assert normalize("f̸̈r̷̓e̶̔e̵̊ nitro") == "free nitro"
    assert normalize("I&#39;m A SUBSCRIBER &amp; fan﻿") == "I'm A SUBSCRIBER & fan"
    assert normalize("fr​ee ni‍tro") == "free nitro"  # zero-width characters inside words


def test_prefilter_counts_characters_not_words():
    assert prefilter(Message("jp", "【公式】Nitro無料配布中！今すぐ受け取り discord-gift.jp/nitro")) is None
    assert prefilter(Message("jp2", "お前マジで死ね、誰もお前のこと好きじゃないから消えろ")) is None
    assert prefilter(Message("enc", "🅵🆁🅴🅴 🅽🅸🆃🆁🅾 dm me 💰💰")) is None
    assert prefilter(Message("link", "https://discord-gifts.ru/nitro")) is None
    assert prefilter(Message("short", "lol")) == "too short"
    assert prefilter(Message("emoji", "🔥🔥🔥")) == "too short"


# ------------------------------------------------------------------ the batch cross-talk bug
def test_batch_matches_single_verdicts_in_multilingual_batch():
    """Red team: with a list-shaped state, position 6 of this batch received position 5's probabilities.
    Every message judged inside the batch must land close to the same message judged alone, and never on the
    other side of that category's default threshold (that is what changes a decision)."""
    j = Judge()
    batch = [msg(r) for r in rows("lang") if r["id"] in {f"l{i}" for i in range(5, 13)}]
    assert len(batch) == 8
    in_batch = {v.message_id: v.scores for v in j.judge(batch, CATS)}
    for m in batch:
        alone = Judge(client=j.client).judge([m], CATS)[0].scores
        for c in CATS:
            a, b, th = in_batch[m.id][c], alone[c], DEFAULT_THRESHOLDS[c]
            assert abs(a - b) <= 0.35 and (a >= th) == (b >= th), (m.id, c, a, b, m.text)
    # and the two concrete failures the red team found
    assert in_batch["l11"]["harassment"] >= 0.75, in_batch["l11"]  # "du bist so ein Hurensohn…"
    assert in_batch["l12"]["harassment"] < 0.75, in_batch["l12"]  # "Hat jemand Lust auf eine Runde…"


# ------------------------------------------------------------------ scoreboard per block
def score_block(block: str, policy: Policy) -> tuple[int, int, int, list[str]]:
    """Returns (true positives, false positives, false negatives, notes) with the default policy in batches of 8."""
    j = Judge()
    data = rows(block)
    tp = fp = fn = 0
    notes: list[str] = []
    for start in range(0, len(data), 8):
        chunk = data[start : start + 8]
        rules = RULES if block == "rules" else {}
        verdicts = j.judge([msg(r) for r in chunk], policy.enabled_categories(), rules)
        for r, v in zip(chunk, verdicts, strict=True):
            d = decide(policy, v)
            if r["expected"] == "skip":
                continue  # the red team expected the pre-filter to skip these; now judged, no label to score
            expected = set(r["expected"].split("|")) - {"clean"}
            expected = {e if e in CATS else f"rule:{e}" for e in expected}
            got = set()
            for c, p in {**v.scores, **{f"rule:{n}": p for n, p in v.custom.items()}}.items():
                th = policy.thresholds.get(c, policy.rule_thresholds.get(c[5:], 0.75))
                if p >= th:
                    got.add(c)
            if expected and got & expected:
                tp += 1
            elif expected and not got:
                fn += 1
                notes.append(f"FN {r['id']} {r['text'][:60]!r} -> {d.to_dict()['scores']}")
            elif not expected and got:
                fp += 1
                notes.append(f"FP {r['id']} {r['text'][:60]!r} -> {sorted(got)} {d.to_dict()['scores']}")
    return tp, fp, fn, notes


RULES = {
    "no_politics": "No political discussion in this server.",
    "english_only": "English only in this channel.",
    "no_selfpromo": "No self-promotion or advertising other servers. Selling your own used items is fine.",
}

# the red team measured these with the old judge; the new one must not do worse (fp, fn allowed per block)
BUDGET = {
    "evasion": (0, 1),
    "lang": (0, 2),
    "fp": (0, 0),
    "inject": (0, 1),
    "rules": (1, 2),
    "length": (0, 2),
    "nsfw": (0, 0),
}


@pytest.mark.parametrize("block", list(BUDGET))
def test_block_does_not_regress(block):
    policy = Policy()
    for c in CATS:
        policy.set_category(c, "flag")  # judge every category, including offtopic
    for name, text in RULES.items():
        policy.set_rule(name, text)
    tp, fp, fn, notes = score_block(block, policy)
    print(f"\n[{block}] tp={tp} fp={fp} fn={fn}\n" + "\n".join(notes))
    max_fp, max_fn = BUDGET[block]
    assert fp <= max_fp and fn <= max_fn, "\n".join(notes)
