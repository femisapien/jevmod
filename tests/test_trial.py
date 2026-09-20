"""T1: the fourteen day trial's state machine (`trial_ends_at`, the plan transition, the expiry sweep) and
the schema migration that adds it. T2's `/mod trial` and `/mod status` wrap `Store.start_trial` and
`Store.trial_ends_at` directly, so their behaviour is covered here rather than through a mocked Discord
interaction — see `tests/test_discord_local_commands.py` for why the slash callbacks themselves are not.

Five things the spec calls out by name get their own test: one trial per tenant ever, Pro's quota while on
trial, the free-budget classification while on trial, `paying_tenants()` ignoring trials, and expiry leaving
the local rules running.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from jevmod.core.policy import Policy
from jevmod.core.service import ModerationService
from jevmod.core.store import Store
from jevmod.judge import Message, Verdict


class _CountingJudge:
    """A fake Judge: no network, records exactly which messages it was asked to judge."""

    def __init__(self):
        self.seen_texts: list[str] = []
        self.requests = 0
        self.input_tokens = 0
        self.judged_messages = 0

    def judge(self, messages, categories, custom_rules=None):
        self.seen_texts.extend(m.text for m in messages)
        self.judged_messages += len(messages)
        return [Verdict(m.id, {c: 0.99 for c in categories}, True, "jev") for m in messages]


# ---- migration: an existing database opens and keeps working


def test_a_pre_trial_database_still_opens_and_reads(tmp_path):
    path = tmp_path / "old.sqlite"
    # The schema exactly as it was before this column existed.
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE tenants (
            id TEXT PRIMARY KEY, policy TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free',
            meta TEXT NOT NULL DEFAULT '{}', quota_notified TEXT DEFAULT '');
        """
    )
    con.execute(
        "INSERT INTO tenants (id, policy, plan) VALUES (?, ?, ?)",
        ("discord:old", '{"actions": {}}', "pro"),
    )
    con.commit()
    con.close()

    store = Store(path)

    assert store.plan("discord:old") == "pro", "a row written before this column existed must still read"
    assert store.trial_ends_at("discord:old") is None
    # The migrated column must accept writes too, not just reads.
    assert store.start_trial("discord:new") is True
    assert store.trial_ends_at("discord:new") is not None


# ---- one trial per tenant, ever


def test_a_tenant_can_start_exactly_one_trial_ever(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    assert store.start_trial("t") is True
    assert store.plan("t") == "trial"
    ends = store.trial_ends_at("t")
    assert ends is not None and ends == pytest.approx(time.time() + 14 * 86400, abs=5)


def test_a_second_trial_is_refused_even_after_the_first_expired(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    assert store.start_trial("t") is True
    assert store.expire_trial("t") is False, "not due yet"
    # Force the trial into the past and let it expire.
    store.db.execute("UPDATE tenants SET trial_ends_at=? WHERE id=?", (time.time() - 1, "t"))
    store.db.commit()
    assert store.expire_trial("t") is True
    assert store.plan("t") == "free"

    assert store.start_trial("t") is False, "trial_ends_at was set once and a tenant gets exactly one, ever"
    assert store.plan("t") == "free"


# ---- quota while on trial: Pro's ceiling, not Free's


def test_a_trial_tenant_gets_pro_quota(monkeypatch, tmp_path):
    monkeypatch.setenv("JEVMOD_PRO_MONTHLY_QUOTA", "50000")
    import importlib

    from jevmod.core import store as store_mod

    importlib.reload(store_mod)
    store = store_mod.Store(tmp_path / "s.sqlite", monthly_quota=5)
    store.start_trial("t")

    assert store.quota_for("t") == 50000, "a trial must not be capped at Free's quota"


# ---- over_budget classifies a trial as free, so trials pause before paying servers


def test_a_trial_tenant_counts_as_free_for_the_budget_ceiling(monkeypatch, tmp_path):
    from jevmod.core import store as store_mod

    monkeypatch.setattr(store_mod, "GLOBAL_BUDGET_USD", 60.0)
    monkeypatch.setattr(store_mod, "FREE_BUDGET_USD", 15.0)
    store = store_mod.Store(tmp_path / "s.sqlite")
    store.set_plan("pro-tenant", "pro")
    store.start_trial("trial-tenant")

    tokens = round(20.0 * 1e6 / store_mod.USD_PER_M_INPUT)  # past the free ceiling, nowhere near the hard one
    store.add_usage("noise", judged=1, requests=1, tokens=tokens)
    store._spend_at = 0.0

    assert store.over_budget("trial-tenant") == "free_budget", "a trial must pause before paying servers do"
    assert store.over_budget("pro-tenant") is None, "a paying server must not be paused by trial traffic"


# ---- paying_tenants() must not count trials, or a trial would raise the ceiling it spends against


def test_paying_tenants_ignores_trials(monkeypatch, tmp_path):
    from jevmod.core import store as store_mod

    monkeypatch.setattr(store_mod, "GLOBAL_BUDGET_USD", 60.0)
    monkeypatch.setattr(store_mod, "PAID_BUDGET_USD", 100.0)
    store = store_mod.Store(tmp_path / "s.sqlite")
    store.set_plan("pro-tenant", "pro")
    store.start_trial("trial-tenant")
    store.start_trial("trial-tenant-2")

    assert store.paying_tenants() == 1, "trials are not subscriptions and must not raise the spend ceiling"
    assert store.budget_ceiling() == pytest.approx(160.0)


# ---- expiry: the plan becomes free, the model stops, the local rules keep running


def test_expiry_flips_the_plan_and_local_rules_keep_running(tmp_path, monkeypatch):
    """`moderate()` applies the sweep for the tenant it is already reading, so the plan is `free` by the time
    this very call finishes gating — no separate sweep gets to run first. The local word list, which never
    depended on plan at all, keeps deciding regardless."""
    monkeypatch.setenv("JEVMOD_PRO_MONTHLY_QUOTA", "50000")
    import importlib

    from jevmod.core import store as store_mod

    importlib.reload(store_mod)
    store = store_mod.Store(tmp_path / "s.sqlite", monthly_quota=0)
    store.start_trial("t")
    store.db.execute("UPDATE tenants SET trial_ends_at=? WHERE id=?", (time.time() - 1, "t"))
    store.db.commit()

    policy = Policy()
    policy.set_category("spam", "flag")
    policy.set_words(["nitro"])
    store.save_policy("t", policy)

    judge = _CountingJudge()
    service = ModerationService(store=store, judge=judge)

    decisions = service.moderate(
        "t",
        [Message("m1", "free nitro codes"), Message("m2", "hello there, a perfectly normal message")],
    )

    assert store.plan("t") == "free", "moderate() must apply the sweep for the tenant it is already reading"
    assert decisions[0].category == "local:word" and decisions[0].reason == "local", "local rules still run"
    assert store.quota_for("t") == 0, "expiry drops the trial's Pro quota back to Free's"
    assert judge.seen_texts == ["hello there, a perfectly normal message"], (
        "on a self-hosted copy, which pays its own model bill and has no notion of plans, expiry changes "
        "only the quota and the budget classification; the hosted deployment sets JEVMOD_MODEL_ON_FREE=0 "
        "and is covered by its own test below"
    )


# ---- the three-day warning latch: fires once, alongside the batch sweep that already runs for expiry


def test_trial_warning_fires_once_inside_the_three_day_window(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    store.start_trial("t")
    store.db.execute("UPDATE tenants SET trial_ends_at=? WHERE id=?", (time.time() + 2 * 86400, "t"))
    store.db.commit()

    assert store.note_trial_warning("t") is True, "two days left is inside the three-day window"
    assert store.note_trial_warning("t") is False, "a second check must not warn twice"


def test_trial_warning_does_not_fire_before_the_window(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    store.start_trial("t")  # fourteen days left: outside the three-day window

    assert store.note_trial_warning("t") is False, "a fresh trial is not due for a warning yet"


def test_trial_warning_does_not_fire_once_the_trial_has_already_expired(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    store.start_trial("t")
    store.db.execute("UPDATE tenants SET trial_ends_at=? WHERE id=?", (time.time() - 1, "t"))
    store.db.commit()

    assert store.note_trial_warning("t") is False, "an expired trial gets the 'ended' email, not the warning"


def test_trial_warning_latch_survives_twenty_batches_in_the_window(tmp_path):
    """The sweep in `moderate()` must run on every batch and still send exactly one warning, or a batcher
    that flushes twenty times during the window would fire twenty emails instead of one.

    RED, observed before `note_trial_warning` existed:
        AttributeError: 'Store' object has no attribute 'note_trial_warning'
    """
    store = Store(tmp_path / "s.sqlite")
    store.start_trial("t")
    store.db.execute("UPDATE tenants SET trial_ends_at=? WHERE id=?", (time.time() + 2 * 86400, "t"))
    store.db.commit()

    judge = _CountingJudge()
    service = ModerationService(store=store, judge=judge)

    fires = 0
    for _ in range(20):
        # A caller that wants to react (send the email) checks the latch before handing the batch to
        # `moderate()`, exactly the way `discord_bot.handle_batch` checks `expire_trial` before calling it.
        if store.note_trial_warning("t"):
            fires += 1
        service.moderate("t", [Message("m", "hello there, a perfectly normal message")])

    assert fires == 1, "twenty batches inside the window must warn exactly once"


def test_a_trial_that_is_not_due_yet_still_reaches_the_model(tmp_path):
    """The companion to the test above: a live trial must not be mistaken for a free tenant."""
    store = Store(tmp_path / "s.sqlite")
    store.start_trial("t")
    policy = Policy()
    policy.set_category("spam", "flag")
    store.save_policy("t", policy)

    judge = _CountingJudge()
    service = ModerationService(store=store, judge=judge)
    service.moderate("t", [Message("m1", "hello there, a perfectly normal message")])

    assert judge.seen_texts == ["hello there, a perfectly normal message"]


# ---- _trial_days_left: the pure helper `/mod trial` and `/mod status` report from


def test_trial_days_left_is_none_off_trial():
    discord_mod = pytest.importorskip("jevmod.adapters.discord_bot")
    assert discord_mod._trial_days_left(None) is None


def test_trial_days_left_rounds_up_a_partial_day():
    discord_mod = pytest.importorskip("jevmod.adapters.discord_bot")
    now = 1_000_000.0
    ends = now + 3600  # one hour left
    assert discord_mod._trial_days_left(ends, now=now) == 1


def test_trial_days_left_floors_at_zero_past_the_deadline():
    discord_mod = pytest.importorskip("jevmod.adapters.discord_bot")
    now = 1_000_000.0
    assert discord_mod._trial_days_left(now - 3600, now=now) == 0

def test_the_hosted_free_plan_never_reaches_the_model_but_keeps_its_local_rules(tmp_path, monkeypatch):
    """What actually makes the free tier free.

    Not a quota that runs out and not a ceiling that pauses: a plan that never spends. The switch exists
    because a self-hosted copy pays its own model bill and has no notion of plans, so there every tenant is
    "free" and every tenant should be judged. Only the hosted deployment turns it off, and the test above
    describes that other deployment rather than this one.
    """
    import importlib

    monkeypatch.setenv("JEVMOD_MODEL_ON_FREE", "0")
    from jevmod.core import service as service_mod

    importlib.reload(service_mod)
    assert service_mod.MODEL_ON_FREE is False
    try:
        store = Store(tmp_path / "free.sqlite")
        policy = Policy()
        policy.set_category("spam", "flag")
        policy.set_words(["nitro"])
        store.save_policy("t", policy)

        judge = _CountingJudge()
        service = service_mod.ModerationService(store=store, judge=judge)
        decisions = service.moderate(
            "t",
            [Message("m1", "free nitro codes"), Message("m2", "hello there, a perfectly normal message")],
        )

        assert judge.seen_texts == [], "a free tenant must not cost a single token"
        assert decisions[0].category == "local:word", "and must still get the rules that cost nothing"
        assert decisions[1].reason == "free_plan"

        # A trial is not free for this purpose.
        store.start_trial("t")
        service.moderate("t", [Message("m3", "hello there, a perfectly normal message")])
        assert judge.seen_texts == ["hello there, a perfectly normal message"]
    finally:
        monkeypatch.delenv("JEVMOD_MODEL_ON_FREE")
        importlib.reload(service_mod)
