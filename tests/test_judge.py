"""Real Jev calls on realistic messages. Checks the categories, the pre-filters and the cache."""

import os

import pytest

from jevmod.judge import CATEGORIES, Judge, Message, prefilter

pytestmark = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")

CATS = list(CATEGORIES)

SAMPLES = [
    # (id, text, expected category with p>=0.7, or None for clean)
    ("1", "🔥 FREE NITRO for the first 100 people!! claim at discord-gifts.ru/nitro 🔥", "scam"),
    ("2", "Anyone know if the new patch fixed the inventory bug? Mine still duplicates items.", None),
    ("3", "DM me if you want to double your ETH in 24h, guaranteed, I work with Binance support", "scam"),
    ("4", "Check out my server!! Best giveaways!! discord.gg/xxxx join join join", "spam"),
    ("5", "you're a worthless idiot and everyone here hates you, just leave", "harassment"),
    ("6", "gg everyone, that raid was clean. same time tomorrow?", None),
    ("7", "lol", None),  # prefilter: too short
    ("8", "Hi all, I'm new here, where do I find the rules?", None),
    ("9", "I don't want to be here anymore. nobody would notice if I was gone. sorry everyone", "selfharm"),
    ("10", "this boss fight makes me want to die lol, 40 tries", None),
    ("11", "lol his real name is Marcos Pereira, lives at Calle Colón 14 in Valencia, phone 612 33 44 55", "doxxing"),
    (
        "12",
        "hey you said you're 13? you seem mature, add me on snap, don't tell your parents, I'll send you gifts",
        "minors",
    ),
    ("13", "my daughter is 12 and loves this game, any tips on parental controls?", None),
]


def test_prefilter_skips_trusted_and_tiny_messages():
    assert prefilter(Message("a", "lol")) == "too short"
    assert prefilter(Message("b", "buy now http://x.y")) is None  # links are never too short
    assert prefilter(Message("c", "long enough message here", author_trusted=True)) == "trusted author"
    assert prefilter(Message("d", "   ")) == "empty"


def test_categories_on_realistic_messages():
    j = Judge()
    msgs = [Message(i, t, channel_topic="gaming community general chat") for i, t, _ in SAMPLES]
    verdicts = j.judge(msgs, CATS)
    assert j.requests == 1  # one Jev request for the whole batch
    by_id = {v.message_id: v for v in verdicts}
    for i, text, expected in SAMPLES:
        v = by_id[i]
        if i == "7":
            assert not v.judged and v.reason == "too short"
            continue
        assert v.judged, (i, v.reason)
        if expected is None:
            assert all(p < 0.5 for p in v.scores.values()), (text, v.scores)
        else:
            assert v.scores[expected] >= 0.7, (text, v.scores)
    print(f"\n{j.judged_messages} messages, {j.input_tokens} tokens, ${j.input_tokens * 0.042 / 1e6:.6f}")


def test_cache_reuses_verdicts_and_custom_rules_work():
    j = Judge()
    rules = {"no_politics": "No political discussion in this server."}
    m = [
        Message("p1", "Who are you all voting for in the election next month? The left is destroying this country."),
        Message("p2", "Which GPU should I get for 1440p, the 5070 or wait for the 5080?"),
    ]
    v1 = j.judge(m, ["spam"], rules)
    assert v1[0].custom["no_politics"] >= 0.7 and v1[1].custom["no_politics"] < 0.4, [x.custom for x in v1]
    v2 = j.judge(m, ["spam"], rules)
    assert j.requests == 1 and all(x.reason == "cache" for x in v2)
