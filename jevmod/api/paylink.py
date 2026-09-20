"""Where to send a server owner who wants to pay, when someone is running jevmod as a paid service.

This is a URL builder and nothing else. It holds no payment provider, no price, no customer record and no
network call: those belong to whoever operates the service, not to the open package. What has to live here is
the link, because `/mod upgrade` is a command of the open bot and a bot that cannot say where to pay is a bot
that cannot be run commercially by anyone but its author.

The signature is an HMAC over `tenant:exp` with `JEVMOD_BILLING_SECRET`, where `exp` is a unix timestamp the
link stops working at. Without the expiry, anyone who ever obtained a valid `sig` for a tenant — a
screenshot, a forwarded message, browser history sync, somebody reading over a shoulder — could open that
tenant's Stripe billing portal forever, with no re-check that they still administer the server: a red-team
finding against an earlier version of this file, which signed the tenant alone. Folding `exp` into the
signed message (not appending it unsigned) means stretching `exp` on an old link is a forgery, not a
renewal: the HMAC no longer matches, exactly like changing `tenant` never worked before. There is
deliberately no default key: a constant fallback would make every signature forgeable.

`LINK_TTL_S` is ten minutes. Both issuers of this link are a single click away from a live session: `/mod
upgrade` posts it into the same Discord channel the owner is already reading, and the dashboard renders a
fresh one on every page load rather than caching it. Ten minutes is generous slack for someone who is about
to click it and worthless to someone who is not, which is the property the missing expiry never had.

Links already in the wild before this change verified an unexpiring `HMAC(tenant)` with no `exp` field at
all, so there is nothing for a grace period to accept: the two are different messages under the same key,
and an old signature simply does not match `tenant:exp` for any `exp`. That is intentional, not an
oversight: the only two issuers of this link are `/mod upgrade` (an ephemeral, per-invocation bot reply) and
the dashboard (which renders a fresh link on every page load), so nothing legitimate depends on an old
signature surviving. A grace period that still accepted the unexpiring form would keep the exact hole this
change closes open for its own duration, in exchange for compatibility with links nobody actually keeps
around.

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
import time

# Ten minutes: comfortably longer than the minute or two between handing someone the link and them clicking
# it, short enough that a leaked link (screenshot, forwarded message, shared clipboard) is worthless soon
# after. Both issuers (`/mod upgrade`, the dashboard) mint a fresh one per use rather than storing this one,
# so there is no legitimate flow this length ever interrupts.
LINK_TTL_S = 600


def enabled() -> bool:
    """True when this copy is operated as a paid service: a public URL and a key to sign links with."""
    return bool(os.environ.get("JEVMOD_PUBLIC_URL") and os.environ.get("JEVMOD_BILLING_SECRET"))


def sign_tenant(tenant: str, exp: int) -> str:
    """HMAC over `tenant:exp`, so a link's expiry is part of what is signed, not a separate unsigned field
    an attacker could stretch. Callers pick `exp`; `checkout_url`/`portal_url` below always pick one that is
    `LINK_TTL_S` seconds in the future."""
    key = os.environ.get("JEVMOD_BILLING_SECRET", "")
    if not key:
        raise RuntimeError("JEVMOD_BILLING_SECRET must be set to sign billing links")
    message = f"{tenant}:{exp}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:24]


def verify_signature(tenant: str, exp: str | int, sig: str) -> bool:
    """Constant-time check that `sig` is this exact tenant+exp pair's own signature. Deliberately does not
    check whether `exp` has already passed — that is `link_expired`, a separate question with a separate,
    human-readable failure. Keeping them apart means a genuine link that merely ran out gets "this link has
    expired", while a forged or tampered one gets the generic "invalid link", instead of one message that
    would tell an attacker which part of their forgery worked."""
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    try:
        expected = sign_tenant(tenant, exp_int)
    except RuntimeError:
        return False
    return hmac.compare_digest(sig, expected)


def link_expired(exp: str | int) -> bool:
    """True once `exp` (a unix timestamp) is in the past, or is not a valid timestamp at all — a malformed
    `exp` fails closed as expired rather than open as forever-valid."""
    try:
        return int(exp) < int(time.time())
    except (TypeError, ValueError):
        return True


def checkout_url(tenant: str, *, ttl_s: int = LINK_TTL_S) -> str:
    """The operator's checkout endpoint for one tenant. Valid for that tenant only, and only for `ttl_s`
    seconds from the moment this function is called.

    Also where an already-subscribed tenant ends up: the operator's `/billing/checkout` route sends a
    tenant that is not on Free straight to the billing portal instead of starting a second subscription, so
    `/mod upgrade` can hand out this one link regardless of whether the server is new or already paying.

    `ttl_s` defaults to `LINK_TTL_S` for the two interactive callers (`/mod upgrade`, the dashboard button),
    which is what someone is looking at when the link is minted. A caller that instead hands this link to
    someone who may not open it for hours — an email, say — needs a longer `ttl_s` or the link is dead on
    arrival; see `portal_url` below, whose one such caller does exactly that."""
    base = os.environ.get("JEVMOD_PUBLIC_URL", "").rstrip("/")
    exp = int(time.time()) + ttl_s
    return f"{base}/billing/checkout?tenant={tenant}&exp={exp}&sig={sign_tenant(tenant, exp)}"


def portal_url(tenant: str, *, ttl_s: int = LINK_TTL_S) -> str:
    """A direct link to Stripe's own billing portal for one tenant: cancel, switch plans, update the card,
    see invoices — all inside Stripe's UI, never reimplemented here. Valid for that tenant only, and only
    for `ttl_s` seconds from the moment this function is called.

    Anything that wants a "manage your subscription" link without `checkout_url`'s free/paying branch —
    the web app's own account page, for one — calls this instead. The hosted service's payment-failed email
    (`jevmod_hosted/billing.py`) is the one caller that passes a longer `ttl_s`: a person reads that email
    whenever they next check their inbox, not within the minute or two `LINK_TTL_S` is sized for, so the
    default would make the link in the email already-expired more often than not."""
    base = os.environ.get("JEVMOD_PUBLIC_URL", "").rstrip("/")
    exp = int(time.time()) + ttl_s
    return f"{base}/billing/portal?tenant={tenant}&exp={exp}&sig={sign_tenant(tenant, exp)}"
