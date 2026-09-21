"""The billing hole: a server removes jevmod (or is kicked) and nothing else is watching. `on_guild_remove`
already deletes the tenant's data; this file is about the piece that was missing, `Store.leave_tenant`,
which also queues the tenant's Stripe subscription for cancellation -- without this package, which is the
open-core one self-hosters run with no billing at all, ever calling Stripe itself. That call is the hosted
service's own sweep's job (`jevmod_hosted/cancel_sweep.py`); this module only has to leave it an honest,
once-only queue to read.
"""

from jevmod.core import Store


def _with_subscription(s: Store, tenant: str, subscription_id: str) -> None:
    s.set_subscription(
        tenant,
        customer_id="cus_1",
        subscription_id=subscription_id,
        price_id="price_1",
        status="active",
        current_period_end=1234.0,
    )


def test_leave_tenant_deletes_data_like_delete_tenant_did():
    s = Store(":memory:")
    t = "discord:1"
    s.set_plan(t, "pro")
    s.add_usage(t, 10, 1, 100)
    s.leave_tenant(t)
    assert s.usage(t) == (0, 0, 0) and s.plan(t) == "inactive"


def test_leave_tenant_with_no_subscription_queues_nothing():
    s = Store(":memory:")
    t = "discord:free-server"
    s.set_plan(t, "inactive")
    s.leave_tenant(t)
    assert s.pending_cancellations() == []


def test_leave_tenant_with_a_subscription_queues_exactly_that_one():
    s = Store(":memory:")
    t = "discord:paying-server"
    _with_subscription(s, t, "sub_abc")
    s.leave_tenant(t)
    pending = s.pending_cancellations()
    assert len(pending) == 1
    assert pending[0]["subscription_id"] == "sub_abc"
    assert pending[0]["tenant"] == t


def test_leave_tenant_never_queues_another_servers_subscription():
    """The non-negotiable rule: only this server's own subscription_id, read from this server's own
    `subscriptions` row, ever reaches the queue -- never a guess, never another tenant's id."""
    s = Store(":memory:")
    other = "discord:other-server"
    _with_subscription(s, other, "sub_other")

    mine = "discord:my-server"
    s.set_plan(mine, "inactive")  # no subscription of its own
    s.leave_tenant(mine)

    pending = s.pending_cancellations()
    assert pending == []  # the other server's subscription was never touched
    assert s.subscription(other)["subscription_id"] == "sub_other"  # untouched


def test_leaving_twice_queues_the_subscription_once():
    """A server that leaves, is re-added, and leaves again must not queue the same Stripe subscription id
    twice -- `subscription_id` is the queue's primary key for exactly this."""
    s = Store(":memory:")
    t = "discord:flaky-server"
    _with_subscription(s, t, "sub_xyz")
    s.leave_tenant(t)
    # simulate the bot rejoining and the same subscription still being on file, then leaving again
    _with_subscription(s, t, "sub_xyz")
    s.leave_tenant(t)
    pending = s.pending_cancellations()
    assert len(pending) == 1


def test_clear_cancellation_removes_the_queued_row():
    s = Store(":memory:")
    t = "discord:paid"
    _with_subscription(s, t, "sub_done")
    s.leave_tenant(t)
    assert len(s.pending_cancellations()) == 1
    s.clear_cancellation("sub_done")
    assert s.pending_cancellations() == []


def test_deleting_a_tenant_over_the_api_queues_its_cancellation_too():
    """`DELETE /v1/tenant` deletes the subscription row along with everything else, so without this the card
    keeps being charged for a tenant that no longer exists. It is the same hole `on_guild_remove` had, and
    it matters more here: `/mod forget` is typed by a person who can be told to cancel, and an API call is
    nobody reading anything."""
    import inspect

    from jevmod.api import server

    src = inspect.getsource(server.delete_tenant)
    assert "leave_tenant" in src, "the API delete must queue the cancellation"
    assert "store.delete_tenant(" not in src, "and must not call the one that forgets the subscription id"
