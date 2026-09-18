"""No key needed: policy decisions, store, quota, retention, erasure, pre-filters."""

import time
from pathlib import Path

from jevmod import Message, Policy, decide
from jevmod.core import Decision, Store
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
    assert not Store(":memory:").over_quota("x")  # unlimited by default
    s = Store(":memory:", keep_text_chars=50, retention_days=1, monthly_quota=100)
    t = "discord:1"
    assert not s.over_quota(t)
    s.add_usage(t, 100, 10, 1000)
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


def test_every_role_is_dispatchable(monkeypatch):
    """`jevmod <role>` must reach its runner: the hosted role once fell out of the dispatcher unnoticed."""
    import jevmod.__main__ as m

    seen = []
    monkeypatch.setattr(m, "run_role", lambda r: seen.append(r))
    for role in ("api", "demo", "hosted", "discord", "telegram", "reddit", "mcp"):
        m.run_role(role)
    assert seen == ["api", "demo", "hosted", "discord", "telegram", "reddit", "mcp"]
    import inspect

    src = inspect.getsource(m)
    for role in ("api", "hosted", "demo", "discord", "telegram", "reddit", "mcp"):
        assert f'"{role}"' in src.split("def run_role")[1].split("def main")[0], role


def test_keep_text_chars_env_and_zero(monkeypatch, tmp_path):
    """The hosted bot must be able to run without storing any message text (JEVMOD_KEEP_TEXT_CHARS=0)."""
    monkeypatch.setenv("JEVMOD_KEEP_TEXT_CHARS", "0")
    s = Store(tmp_path / "k.sqlite")
    assert s.keep_text_chars == 0
    m = Message("m1", "some flagged message text", author="42", channel_topic="general")
    d = Decision("m1", "flag", "spam", 0.9, {"spam": 0.9}, True, "jev")
    s.log_decision("discord:1", m, d, "rid")
    row = s.recent_decisions("discord:1")[0]
    assert row["text"] == "" and row["message_id"] == "m1" and row["scores"] == {"spam": 0.9}
    assert Store(tmp_path / "k2.sqlite", keep_text_chars=50).keep_text_chars == 50


def test_ai_generated_is_opt_in_and_not_nudged():
    """Measured in benchmark/ai_detect/REPORT.md: good ranking, but it flags humans who write encyclopedically,
    so it ships off by default, flag-only, and outside the reaction feedback loop."""
    from jevmod.core.policy import DEFAULT_ACTIONS, DEFAULT_THRESHOLDS
    from jevmod.judge import CATEGORIES

    assert CATEGORIES["ai_generated"]["experimental"] is True
    assert "not by themselves signs of a language model" in CATEGORIES["ai_generated"]["criteria"]["false"].lower()
    assert DEFAULT_ACTIONS["ai_generated"] == "off" and DEFAULT_THRESHOLDS["ai_generated"] == 0.85
    p = Policy()
    assert "ai_generated" not in p.enabled_categories()
    before = p.thresholds["ai_generated"]
    assert p.nudge("ai_generated", 0.03) == before and p.thresholds["ai_generated"] == before
    p.set_category("ai_generated", "flag")
    assert "ai_generated" in p.enabled_categories()
    assert p.nudge("spam", 0.03) > DEFAULT_THRESHOLDS["spam"]


def test_published_openapi_matches_the_app(tmp_path, monkeypatch):
    """docs/openapi.json is what people import into Postman. It drifted once already, naming five of the nine
    categories. Regenerate it with `python scripts/site/gen_openapi.py` when this fails."""
    import json
    import sys

    monkeypatch.setenv("JEVMOD_DB", str(tmp_path / "oa.sqlite"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "site"))
    import gen_openapi

    published = json.loads((Path(__file__).resolve().parents[1] / "docs" / "openapi.json").read_text("utf-8"))
    assert published == json.loads(json.dumps(gen_openapi.schema(), sort_keys=True))


def test_postman_collection_covers_every_endpoint():
    """The collection is a hand-written walkthrough, not generated, so a new endpoint can go missing from it."""
    import json

    root = Path(__file__).resolve().parents[1]
    paths = set(json.loads((root / "docs" / "openapi.json").read_text("utf-8"))["paths"])
    collection = json.loads((root / "docs" / "jevmod.postman_collection.json").read_text("utf-8"))
    urls: list[str] = []

    def walk(items: list[dict]) -> None:
        for item in items:
            if "item" in item:
                walk(item["item"])
                continue
            url = item.get("request", {}).get("url")
            urls.append(url.get("raw", "") if isinstance(url, dict) else str(url))

    walk(collection["item"])
    raw = " ".join(urls)
    missing = sorted(p for p in paths if p not in raw)
    assert not missing, f"docs/jevmod.postman_collection.json has no request for {missing}"
