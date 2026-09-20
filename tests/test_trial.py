"""What is left of the trial in the open package after Stripe took over owning it
(`odd/tasks/free-tier.md`, "the free tier that never calls the model" superseded by Omar's later call: Stripe
owns the subscription lifecycle, including the trial, and this package is a mirror). `Store.start_trial`,
`expire_trial` and `note_trial_warning` are gone — a tenant reaches `plan == "trial"` only because the hosted
webhook wrote it there (`jevmod_hosted/billing.py`), mirroring Stripe's own `trialing` status. This file keeps
exactly what is still this package's job: reading a `trial` plan correctly once it is set, by whatever means,
and opening a database that predates this change without choking on the columns it left behind.

`tests/test_discord_local_commands.py` covers the Discord surface; `jevmod_hosted/tests/test_billing.py` (the
private repository) covers the mirror table itself, status by status, and is where the actual state machine
now lives.
"""

from __future__ import annotations

import sqlite3

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


# ---- migration: a database written before `trial_ends_at`/`trial_warned` existed still opens and reads,
# and one written *with* those columns (every production database, as of this change) still opens too.


def test_a_pre_trial_database_still_opens_and_reads(tmp_path):
    path = tmp_path / "old.sqlite"
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


def test_a_database_carrying_the_old_trial_columns_still_opens_and_reads(tmp_path):
    """The column this package used to write is not dropped (see the comment above `PLAN_QUOTAS` in
    `store.py`): a production database still has it, and opening one must not choke on an extra column
    nothing here looks at any more."""
    path = tmp_path / "with_columns.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE tenants (
            id TEXT PRIMARY KEY, policy TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free',
            meta TEXT NOT NULL DEFAULT '{}', quota_notified TEXT DEFAULT '',
            trial_ends_at REAL, trial_warned INTEGER);
        """
    )
    con.execute(
        "INSERT INTO tenants (id, policy, plan, trial_ends_at) VALUES (?, ?, ?, ?)",
        ("discord:withcol", '{"actions": {}}', "trial", 4_000_000_000.0),
    )
    con.commit()
    con.close()

    store = Store(path)

    assert store.plan("discord:withcol") == "trial"
    assert store.quota_for("discord:withcol") == store.quota_for("discord:withcol")  # does not raise


# ---- quota while on trial: Pro's ceiling, not Free's, however `plan` got set to "trial"


def test_a_trial_tenant_gets_pro_quota(monkeypatch, tmp_path):
    monkeypatch.setenv("JEVMOD_PRO_MONTHLY_QUOTA", "50000")
    import importlib

    from jevmod.core import store as store_mod

    importlib.reload(store_mod)
    store = store_mod.Store(tmp_path / "s.sqlite", monthly_quota=5)
    store.set_plan("t", "trial")

    assert store.quota_for("t") == 50000, "a trial must not be capped at Free's quota"


# ---- over_budget classifies a trial as free, so trials pause before paying servers


def test_a_trial_tenant_counts_as_free_for_the_budget_ceiling(monkeypatch, tmp_path):
    from jevmod.core import store as store_mod

    monkeypatch.setattr(store_mod, "GLOBAL_BUDGET_USD", 60.0)
    monkeypatch.setattr(store_mod, "FREE_BUDGET_USD", 15.0)
    store = store_mod.Store(tmp_path / "s.sqlite")
    store.set_plan("pro-tenant", "pro")
    store.set_plan("trial-tenant", "trial")

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
    store.set_plan("trial-tenant", "trial")
    store.set_plan("trial-tenant-2", "trial")

    assert store.paying_tenants() == 1, "trials are not subscriptions and must not raise the spend ceiling"
    assert store.budget_ceiling() == pytest.approx(160.0)


# ---- a live trial still reaches the model; local rules run regardless of plan


def test_a_trial_tenant_still_reaches_the_model(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    store.set_plan("t", "trial")
    policy = Policy()
    policy.set_category("spam", "flag")
    store.save_policy("t", policy)

    judge = _CountingJudge()
    service = ModerationService(store=store, judge=judge)
    service.moderate("t", [Message("m1", "hello there, a perfectly normal message")])

    assert judge.seen_texts == ["hello there, a perfectly normal message"]


def test_local_rules_keep_running_once_a_trial_becomes_free(tmp_path):
    """Whatever flips `plan` back to `free` — the webhook mirroring Stripe now, an admin comp, anything — the
    local word list never depended on plan at all and keeps deciding regardless."""
    store = Store(tmp_path / "s.sqlite", monthly_quota=0)
    store.set_plan("t", "trial")
    store.set_plan("t", "free")

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

    assert decisions[0].category == "local:word" and decisions[0].reason == "local", "local rules still run"
    assert store.quota_for("t") == 0, "back on free, the trial's Pro quota is gone"


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
        store.set_plan("t", "trial")
        service.moderate("t", [Message("m3", "hello there, a perfectly normal message")])
        assert judge.seen_texts == ["hello there, a perfectly normal message"]
    finally:
        monkeypatch.delenv("JEVMOD_MODEL_ON_FREE")
        importlib.reload(service_mod)
