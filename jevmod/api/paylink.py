"""Where to send a server owner who wants to pay, when someone is running jevmod as a paid service.

This is a URL builder and nothing else. It holds no payment provider, no price, no customer record and no
network call: those belong to whoever operates the service, not to the open package. What has to live here is
the link, because `/mod upgrade` is a command of the open bot and a bot that cannot say where to pay is a bot
that cannot be run commercially by anyone but its author.

The signature is an HMAC over the guild id with `JEVMOD_BILLING_SECRET`. Without it, anyone who knows a
guild id could open that owner's billing portal, which lists their invoices and can cancel their plan. There
is deliberately no default key: a constant fallback would make every signature forgeable.

That secret used to be `JEVMOD_ADMIN_TOKEN`, which also authenticated the operator's admin panel and
authorised minting an API key for any tenant. One secret doing three unrelated jobs means one leak opens all
three, so they are three secrets now and this one signs links and nothing else.

`JEVMOD_PUBLIC_URL` and `JEVMOD_BILLING_SECRET` are the operator's. A self-hosted copy sets neither,
`enabled()` is false, and the bot says there is nothing to pay.
"""

from __future__ import annotations

import hashlib
import hmac
import os


def enabled() -> bool:
    """True when this copy is operated as a paid service: a public URL and a key to sign links with."""
    return bool(os.environ.get("JEVMOD_PUBLIC_URL") and os.environ.get("JEVMOD_BILLING_SECRET"))


def sign_tenant(tenant: str) -> str:
    key = os.environ.get("JEVMOD_BILLING_SECRET", "")
    if not key:
        raise RuntimeError("JEVMOD_BILLING_SECRET must be set to sign billing links")
    return hmac.new(key.encode(), tenant.encode(), hashlib.sha256).hexdigest()[:24]


def checkout_url(tenant: str) -> str:
    """The operator's checkout endpoint for one tenant. Valid for that tenant only.

    Also where an already-subscribed tenant ends up: the operator's `/billing/checkout` route sends a
    tenant that is not on Free straight to the billing portal instead of starting a second subscription, so
    `/mod upgrade` can hand out this one link regardless of whether the server is new or already paying."""
    base = os.environ.get("JEVMOD_PUBLIC_URL", "").rstrip("/")
    return f"{base}/billing/checkout?tenant={tenant}&sig={sign_tenant(tenant)}"


def portal_url(tenant: str) -> str:
    """A direct link to Stripe's own billing portal for one tenant: cancel, switch plans, update the card,
    see invoices — all inside Stripe's UI, never reimplemented here. Valid for that tenant only.

    Anything that wants a "manage your subscription" link without `checkout_url`'s free/paying branch —
    the web app's own account page, for one — calls this instead."""
    base = os.environ.get("JEVMOD_PUBLIC_URL", "").rstrip("/")
    return f"{base}/billing/portal?tenant={tenant}&sig={sign_tenant(tenant)}"
