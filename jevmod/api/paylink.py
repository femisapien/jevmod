"""Where to send a server owner who wants to pay, when someone is running jevmod as a paid service.

This is a URL builder and nothing else. It holds no payment provider, no price, no customer record and no
network call: those belong to whoever operates the service, not to the open package. What has to live here is
the link, because `/mod upgrade` is a command of the open bot and a bot that cannot say where to pay is a bot
that cannot be run commercially by anyone but its author.

The signature is an HMAC over the guild id with the operator's admin token. Without it, anyone who knows a
guild id could open that owner's billing portal, which lists their invoices and can cancel their plan. There
is deliberately no default key: a constant fallback would make every signature forgeable.

`JEVMOD_PUBLIC_URL` and `JEVMOD_ADMIN_TOKEN` are the operator's. A self-hosted copy sets neither, `enabled()`
is false, and the bot says there is nothing to pay.
"""

from __future__ import annotations

import hashlib
import hmac
import os


def enabled() -> bool:
    """True when this copy is operated as a paid service: a public URL and a key to sign links with."""
    return bool(os.environ.get("JEVMOD_PUBLIC_URL") and os.environ.get("JEVMOD_ADMIN_TOKEN"))


def sign_tenant(tenant: str) -> str:
    key = os.environ.get("JEVMOD_ADMIN_TOKEN", "")
    if not key:
        raise RuntimeError("JEVMOD_ADMIN_TOKEN must be set to sign billing links")
    return hmac.new(key.encode(), tenant.encode(), hashlib.sha256).hexdigest()[:24]


def checkout_url(tenant: str) -> str:
    """The operator's checkout endpoint for one tenant. Valid for that tenant only."""
    base = os.environ.get("JEVMOD_PUBLIC_URL", "").rstrip("/")
    return f"{base}/billing/checkout?tenant={tenant}&sig={sign_tenant(tenant)}"
