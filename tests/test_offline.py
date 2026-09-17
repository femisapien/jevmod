"""No key needed: policy decisions, store, quota, retention, erasure, pre-filters."""

import time

from jevmod import Message, Policy, decide
from jevmod.core import FREE_MONTHLY, Decision, Store
from jevmod.judge import Verdict, prefilter


def v(mid, scores, custom=None, judged=True, reason="jev"):
    return Verdict(mid, scores, judged, reason, custom or {})


def test_most_severe_action_wins_then_probability():
    p = Policy()
    p.set_category("spam", "flag", 0.8)
    p.set_category("scam", "delete", 0.8)
    d = decide(p, v("1", {"spam": 0.95, "scam": 0.85}))
    assert d.action == "delete" and d.category == "scam"
    d = decide(p, v("2", {"spam": 0.95, "scam": 0.5}))
    assert d.action == "flag" and d.category == "spam"
    d = decide(p, v("3", {"spam": 0.5, "scam": 0.5}))
    assert d.action == "none" and d.judged


def test_rules_have_their_own_threshold_and_off_disables():
    p = Policy()
    p.set_rule("no_politics", "No politics", "flag", 0.6)
    assert decide(p, v("1", {}, {"no_politics": 0.65})).action == "flag"
    p.set_rule("no_politics", "No politics", "off")
    assert decide(p, v("1", {}, {"no_politics": 0.99})).action == "none"


def test_unjudged_messages_never_act():
    p = Policy()
    assert decide(p, v("1", {}, judged=False, reason="too short")).action == "none"


def test_nudge_both_ways_and_clamp():
    p = Policy()
    assert p.nudge("spam", 0.03) == 0.88
    assert p.nudge("spam", -0.02) == 0.86
    for _ in range(30):
        p.nudge("spam", 0.03)
    assert p.thresholds["spam"] == 0.99
    for _ in range(60):
        p.nudge("spam", -0.02)
    assert p.thresholds["spam"] == 0.5


def test_policy_roundtrip_and_validation():
    p = Policy()
    p.set_category("harassment", "timeout", 0.7)
    p.set_rule("english_only", "English only in this channel")
    q = Policy.from_dict(p.to_dict())
    assert q.actions["harassment"] == "timeout" and q.thresholds["harassment"] == 0.7 and "english_only" in q.rules
    for bad in (("nope", "flag"), ("spam", "nuke")):
        try:
            p.set_category(*bad)
            raise AssertionError("should fail")
        except ValueError:
            pass


def test_store_quota_retention_and_erasure():
    s = Store(":memory:", keep_text_chars=50, retention_days=1)
    t = "discord:1"
    assert not s.over_quota(t)
    s.add_usage(t, FREE_MONTHLY, 10, 1000)
    assert s.over_quota(t)
    assert s.note_quota_hit(t) is True and s.note_quota_hit(t) is False
    s.set_plan(t, "pro")
    assert not s.over_quota(t)
    m = Message("m1", "x" * 200, author="42", channel_topic="general")
    d = Decision("m1", "flag", "spam", 0.9, {"spam": 0.9}, True, "jev")
    s.log_decision(t, m, d, "rid")
    rows = s.recent_decisions(t)
    assert len(rows) == 1 and len(rows[0]["text"]) == 50
    assert s.delete_user(t, "42") == 1 and not s.recent_decisions(t)
    s.log_decision(t, m, d, "rid")
    s.db.execute("UPDATE decisions SET ts=?", (time.time() - 3 * 86400,))
    assert s.purge_expired() == 1
    s.delete_tenant(t)
    assert s.usage(t) == (0, 0, 0) and s.plan(t) == "free"


def test_api_keys_are_hashed_lookups():
    s = Store(":memory:")
    s.create_api_key("api:acme", "deadbeef", "prod")
    assert s.tenant_for_key("deadbeef") == "api:acme" and s.tenant_for_key("nope") is None


def test_prefilter():
    assert prefilter(Message("a", "lol")) == "too short"
    assert prefilter(Message("b", "see http://x.y")) is None
    assert prefilter(Message("c", "long enough text here", author_trusted=True)) == "trusted author"
