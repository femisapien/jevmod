"""Hosted plans: Stripe Checkout, webhook and a small admin panel. Mounted by the `hosted` role next to the demo.

    STRIPE_SECRET_KEY=sk_live_...  STRIPE_WEBHOOK_SECRET=whsec_...  STRIPE_PRICE_ID=price_...  JEVMOD_ADMIN_TOKEN=...
    JEVMOD_PUBLIC_URL=https://jevmod.dev  jevmod hosted

Flow: a server manager types `/mod upgrade` in Discord → the bot answers with
`{PUBLIC_URL}/billing/checkout?tenant=discord:<guild>&sig=<hmac>` → Stripe Checkout (subscription, one price) →
`checkout.session.completed` webhook → `Store.set_plan(tenant, "pro")` and the subscription row → the bot sees
the new quota on its next batch. `customer.subscription.deleted` (or a non-active status on `updated`) puts the
tenant back on `free`. The checkout link is signed so nobody can start a checkout for a guild they do not manage.

Admin: `GET /admin` (HTML, Bearer token or `?token=`) lists tenants, plans, usage, subscriptions, demo spend,
and lets the operator comp or revoke a plan. Everything the panel does is also JSON under `/admin/api/*`.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import time
from pathlib import Path
from string import Template
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..core import PLAN_QUOTAS, Store

PUBLIC_URL = os.environ.get("JEVMOD_PUBLIC_URL", "https://jevmod.dev").rstrip("/")
PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")
JEV_USD_PER_M = 0.042
PLANS = ("free", "pro", "unlimited")
ADMIN_TEMPLATE = Template(Path(__file__).with_name("admin.html").read_text(encoding="utf-8"))


def _secret(name: str) -> str:
    return os.environ.get(name, "")


def sign_tenant(tenant: str) -> str:
    """HMAC over the tenant id with the admin token, so `/mod upgrade` links cannot be forged for another guild."""
    key = (_secret("JEVMOD_ADMIN_TOKEN") or "unset").encode()
    return hmac.new(key, tenant.encode(), hashlib.sha256).hexdigest()[:24]


def checkout_url(tenant: str) -> str:
    return f"{PUBLIC_URL}/billing/checkout?tenant={tenant}&sig={sign_tenant(tenant)}"


def make_router(store: Store, demo_spend: Any = None) -> APIRouter:
    r = APIRouter()

    # ------------------------------------------------------------------ Stripe
    def stripe_client() -> Any:
        import stripe

        key = _secret("STRIPE_SECRET_KEY")
        if not key:
            raise HTTPException(503, "billing is not configured on this server")
        stripe.api_key = key
        return stripe

    @r.get("/billing/checkout")
    def checkout(tenant: str = Query(..., min_length=3, max_length=80), sig: str = Query(..., min_length=8)) -> Any:
        if not hmac.compare_digest(sig, sign_tenant(tenant)):
            raise HTTPException(403, "invalid link; ask for a new one with /mod upgrade")
        if not PRICE_ID:
            raise HTTPException(503, "billing is not configured on this server")
        if store.plan(tenant) != "free":
            return RedirectResponse(f"{PUBLIC_URL}/billing/portal?tenant={tenant}&sig={sig}", status_code=303)
        stripe = stripe_client()
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": PRICE_ID, "quantity": 1}],
            client_reference_id=tenant,
            metadata={"tenant": tenant},
            subscription_data={"metadata": {"tenant": tenant}},
            success_url=f"{PUBLIC_URL}/thanks.html",
            cancel_url=f"{PUBLIC_URL}/cancelled.html",
            allow_promotion_codes=True,
        )
        return RedirectResponse(session.url, status_code=303)

    @r.get("/billing/portal")
    def portal(tenant: str = Query(...), sig: str = Query(...)) -> Any:
        if not hmac.compare_digest(sig, sign_tenant(tenant)):
            raise HTTPException(403, "invalid link")
        sub = store.subscription(tenant)
        if not sub or not sub.get("customer_id"):
            raise HTTPException(404, "no subscription for this server")
        stripe = stripe_client()
        ps = stripe.billing_portal.Session.create(customer=sub["customer_id"], return_url=f"{PUBLIC_URL}/")
        return RedirectResponse(ps.url, status_code=303)

    @r.post("/billing/stripe/webhook")
    async def webhook(request: Request, stripe_signature: str = Header(default="", alias="Stripe-Signature")) -> Any:
        secret = _secret("STRIPE_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(503, "webhook secret not configured")
        payload = await request.body()
        event = verify_stripe_signature(payload, stripe_signature, secret)
        kind = event.get("type", "")
        obj = event.get("data", {}).get("object", {})
        if kind == "checkout.session.completed":
            tenant = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("tenant")
            if tenant:
                store.set_plan(tenant, "pro")
                store.set_subscription(
                    tenant,
                    customer_id=obj.get("customer"),
                    subscription_id=obj.get("subscription"),
                    price_id=PRICE_ID or None,
                    status="active",
                    current_period_end=None,
                )
        elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
            sub_id = obj.get("id")
            tenant = (obj.get("metadata") or {}).get("tenant") or (
                store.tenant_for_subscription(sub_id) if sub_id else None
            )
            if tenant:
                status = "canceled" if kind.endswith("deleted") else str(obj.get("status", ""))
                active = status in ("active", "trialing", "past_due")
                store.set_plan(tenant, "pro" if active else "free")
                item = ((obj.get("items") or {}).get("data") or [{}])[0]
                store.set_subscription(
                    tenant,
                    customer_id=obj.get("customer"),
                    subscription_id=sub_id,
                    price_id=(item.get("price") or {}).get("id") or PRICE_ID or None,
                    status=status,
                    current_period_end=obj.get("current_period_end") or item.get("current_period_end"),
                )
        return {"received": True}

    # ------------------------------------------------------------------ admin
    def admin(authorization: str, token: str) -> None:
        want = _secret("JEVMOD_ADMIN_TOKEN")
        given = authorization[7:].strip() if authorization.startswith("Bearer ") else token
        if not want or not hmac.compare_digest(given, want):
            raise HTTPException(403, "admin token required")

    @r.get("/admin/api/tenants")
    def api_tenants(authorization: str = Header(default=""), token: str = "") -> list[dict[str, Any]]:
        admin(authorization, token)
        return store.tenants_overview()

    @r.get("/admin/api/totals")
    def api_totals(authorization: str = Header(default=""), token: str = "") -> dict[str, Any]:
        admin(authorization, token)
        t = store.totals()
        t["usd"] = round(t["tokens"] * JEV_USD_PER_M / 1e6, 4)
        if demo_spend is not None:
            t["demo_spent_usd"] = round(demo_spend(), 4)
        t["quotas"] = {"free": store.monthly_quota, **{k: v for k, v in PLAN_QUOTAS.items() if k != "free"}}
        return t

    @r.post("/admin/api/plan")
    def api_plan(body: dict[str, str], authorization: str = Header(default=""), token: str = "") -> dict[str, str]:
        admin(authorization, token)
        tenant, plan = body.get("tenant", ""), body.get("plan", "")
        if plan not in PLANS or not tenant:
            raise HTTPException(422, f"plan must be one of {PLANS}")
        store.set_plan(tenant, plan)
        return {"tenant": tenant, "plan": plan}

    @r.get("/admin", response_class=HTMLResponse)
    def panel(authorization: str = Header(default=""), token: str = "") -> str:
        admin(authorization, token)
        rows = store.tenants_overview()
        totals = store.totals()
        tr = []
        for x in rows:
            quota = "unlimited" if not x["quota"] else f"{x['quota']:,}"
            end = time.strftime("%Y-%m-%d", time.gmtime(x["current_period_end"])) if x["current_period_end"] else ""
            opts = "".join(f'<option value="{p}"{" selected" if p == x["plan"] else ""}>{p}</option>' for p in PLANS)
            t = html.escape(x["tenant"])
            tr.append(
                f"<tr><td class=m>{t}</td><td>{x['plan']}</td><td class=n>{x['judged']:,} / {quota}</td>"
                f"<td class=n>{x['tokens']:,}</td><td>{html.escape(str(x['subscription_status'] or ''))} {end}</td>"
                f'<td><select data-t="{t}">{opts}</select></td></tr>'
            )
        return ADMIN_TEMPLATE.substitute(
            month=totals["month"],
            plans=html.escape(json.dumps(totals["plans"])),
            free_quota=store.monthly_quota or "unlimited",
            pro_quota=PLAN_QUOTAS.get("pro") or "unlimited",
            active=totals["active_tenants"],
            judged=f"{totals['judged']:,}",
            usd=f"{totals['tokens'] * JEV_USD_PER_M / 1e6:.4f}",
            demo=f"{demo_spend():.4f}" if demo_spend is not None else "n/a",
            rows="".join(tr) or '<tr><td colspan=6 style="color:#71717A">no tenants yet</td></tr>',
        )

    return r


def verify_stripe_signature(payload: bytes, header: str, secret: str, tolerance_s: int = 300) -> dict[str, Any]:
    """Stripe's scheme: header `t=<ts>,v1=<hmac>`; hmac = HMAC-SHA256(secret, f"{ts}.{payload}")."""
    parts = dict(kv.split("=", 1) for kv in header.split(",") if "=" in kv)
    ts = parts.get("t", "")
    sigs = [v for k, v in (kv.split("=", 1) for kv in header.split(",") if "=" in kv) if k == "v1"]
    if not ts or not sigs:
        raise HTTPException(400, "bad signature header")
    expected = hmac.new(secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise HTTPException(400, "signature mismatch")
    if abs(time.time() - int(ts)) > tolerance_s:
        raise HTTPException(400, "timestamp outside tolerance")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "bad json") from exc


def sign_for_test(payload: bytes, secret: str, ts: int | None = None) -> str:
    """Build a Stripe-Signature header the way Stripe does (used by tests and the local smoke script)."""
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def json_error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)
