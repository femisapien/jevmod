"""The spend ceilings.

These exist for one reason: the operator pays the model bill before anybody pays them, and a single busy
server can spend more in a weekend than the whole month's subscriptions bring in. What they assert is who
stops first and when, because a ceiling that pauses the people who paid is worse than no ceiling at all.
"""

from __future__ import annotations

import importlib

import pytest


def load(monkeypatch, tmp_path, *, hard="0", free="0", paid="0"):
    monkeypatch.setenv("JEVMOD_GLOBAL_BUDGET_USD", hard)
    monkeypatch.setenv("JEVMOD_FREE_BUDGET_USD", free)
    monkeypatch.setenv("JEVMOD_PAID_BUDGET_USD", paid)
    from jevmod.core import store as store_mod

    importlib.reload(store_mod)
    return store_mod, store_mod.Store(tmp_path / "budget.sqlite")


def spend(store_mod, store, usd: float, tenant: str = "discord:noise") -> None:
    """Burn exactly this many dollars of the month's budget, through the counter production writes to."""
    tokens = round(usd * 1e6 / store_mod.USD_PER_M_INPUT)
    store.add_usage(tenant, judged=1, requests=1, tokens=tokens)
    store._spend_at = 0.0  # the 30 second cache would otherwise hide what we just wrote


def test_no_ceilings_configured_never_pauses_anybody(monkeypatch, tmp_path):
    store_mod, store = load(monkeypatch, tmp_path)
    spend(store_mod, store, 10_000.0)
    assert store.over_budget("discord:1") is None


def test_free_tenants_pause_before_paying_ones(monkeypatch, tmp_path):
    store_mod, store = load(monkeypatch, tmp_path, hard="60", free="15")
    store.set_plan("discord:pro", "pro")
    spend(store_mod, store, 20.0)  # past the free ceiling, nowhere near the hard one

    assert store.over_budget("discord:free") == "free_budget"
    assert store.over_budget("discord:pro") is None, "a customer who paid must not be paused by free traffic"


def test_the_hard_ceiling_stops_everybody_including_paying_ones(monkeypatch, tmp_path):
    store_mod, store = load(monkeypatch, tmp_path, hard="60", free="15")
    store.set_plan("discord:pro", "pro")
    spend(store_mod, store, 61.0)

    assert store.over_budget("discord:free") == "global_budget"
    assert store.over_budget("discord:pro") == "global_budget"


def test_every_paid_plan_raises_the_ceiling_by_its_own_allowance(monkeypatch, tmp_path):
    store_mod, store = load(monkeypatch, tmp_path, hard="60", free="15", paid="3")
    assert store.budget_ceiling() == pytest.approx(60.0)

    for i in range(10):
        store.set_plan(f"discord:pro{i}", "pro")
        store._paying_at = 0.0
    assert store.paying_tenants() == 10
    assert store.budget_ceiling() == pytest.approx(90.0)

    # $61 stopped everybody in the test above. With ten subscriptions funding it, it no longer does.
    spend(store_mod, store, 61.0)
    assert store.over_budget("discord:pro0") is None
    assert store.over_budget("discord:free") == "free_budget", "the free ceiling does not move with revenue"


def test_a_ceiling_turned_off_does_not_grow_back_from_subscriptions(monkeypatch, tmp_path):
    """0 means the operator pays their own model bill. Ten subscriptions must not invent a ceiling of 30."""
    store_mod, store = load(monkeypatch, tmp_path, hard="0", free="0", paid="3")
    for i in range(10):
        store.set_plan(f"discord:pro{i}", "pro")
        store._paying_at = 0.0

    assert store.budget_ceiling() == 0.0
    spend(store_mod, store, 5_000.0)
    assert store.over_budget("discord:pro0") is None


def test_free_is_the_default_so_an_unknown_server_is_counted_as_free(monkeypatch, tmp_path):
    store_mod, store = load(monkeypatch, tmp_path, hard="60", free="15", paid="3")
    spend(store_mod, store, 16.0)
    assert store.paying_tenants() == 0
    assert store.over_budget("discord:never-seen-before") == "free_budget"


def test_near_the_ceiling_the_spend_is_read_fresh_rather_than_cached(monkeypatch, tmp_path):
    """The cache is what turns a bounded bill into an unbounded one: every batch that reads a stale figure
    is judged in full before the write that would have refused it. Far from the ceiling that is fine; close
    to it, it is the whole exposure."""
    store_mod, store = load(monkeypatch, tmp_path, hard="60", free="15")

    # Far from the ceiling: a write made behind the cache's back stays invisible, which is the point.
    spend(store_mod, store, 1.0)
    assert store.over_budget("discord:pro") is None
    store.add_usage("discord:noise", judged=1, requests=1, tokens=round(5.0 * 1e6 / store_mod.USD_PER_M_INPUT))
    assert store.month_spend_usd() == pytest.approx(1.0), "still cached, as designed"

    # Past four fifths of the ceiling, a write made behind the cache's back is seen on the very next ask.
    spend(store_mod, store, 43.0)  # 1 + 5 + 43 = 49, past 0.8 * 60
    store.add_usage("discord:noise", judged=1, requests=1, tokens=round(12.0 * 1e6 / store_mod.USD_PER_M_INPUT))
    assert store.over_budget("discord:pro") == "global_budget", "61 dollars spent must not read as 49"
