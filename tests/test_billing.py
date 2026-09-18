"""Hosted billing: signed checkout links, Stripe webhook signature and plan transitions, admin panel, plan quotas.
No Stripe network calls: the webhook is exercised with locally signed payloads exactly as Stripe signs them."""

import importlib
import json
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from jevmod.api.billing import sign_for_test, sign_tenant, verify_stripe_signature
from jevmod.core import Store


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JEVMOD_DB", str(tmp_path / "hosted.sqlite"))
    monkeypatch.setenv("JEVMOD_DEMO_DB", str(tmp_path / "demo.sqlite"))
    monkeypatch.setenv("JEVMOD_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_test")
    monkeypatch.setenv("JEVMOD_MONTHLY_QUOTA", "5000")
    monkeypatch.setenv("JEVMOD_PRO_MONTHLY_QUOTA", "50000")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from jevmod.api import billing, demo, hosted
    from jevmod.core import store as store_mod

    importlib.reload(store_mod)
    importlib.reload(billing)
    importlib.reload(demo)
    importlib.reload(hosted)
    return TestClient(hosted.app), hosted.store


def event(kind: str, obj: dict) -> bytes:
    return json.dumps({"id": "evt_1", "type": kind, "data": {"object": obj}}).encode()


def test_signature_verification_rejects_forgeries():
    payload = b'{"type":"x","data":{"object":{}}}'
    good = sign_for_test(payload, "whsec_test")
    assert verify_stripe_signature(payload, good, "whsec_test")["type"] == "x"
    with pytest.raises(HTTPException):
        verify_stripe_signature(payload, good, "whsec_other")
    with pytest.raises(HTTPException):
        verify_stripe_signature(payload, sign_for_test(payload, "whsec_test", ts=1), "whsec_test")  # too old


def test_checkout_link_is_signed_and_plans_follow_stripe(app):
    c, store = app
    tenant = "discord:123"
    # forged or missing signature is refused; a valid one would redirect to Stripe (503 here: no secret key)
    assert c.get(f"/billing/checkout?tenant={tenant}&sig=deadbeefdeadbeef").status_code == 403
    r = c.get(f"/billing/checkout?tenant={tenant}&sig={sign_tenant(tenant)}", follow_redirects=False)
    assert r.status_code == 503
    # webhook: unsigned is refused
    assert c.post("/billing/stripe/webhook", content=event("checkout.session.completed", {})).status_code == 400
    # paid → pro
    body = event(
        "checkout.session.completed",
        {"client_reference_id": tenant, "customer": "cus_1", "subscription": "sub_1", "metadata": {"tenant": tenant}},
    )
    r = c.post("/billing/stripe/webhook", content=body, headers={"Stripe-Signature": sign_for_test(body, "whsec_test")})
    assert r.status_code == 200 and store.plan(tenant) == "pro"
    assert store.quota_for(tenant) == 50000 and store.subscription(tenant)["subscription_id"] == "sub_1"
    # past_due keeps pro; canceled → free
    body = event(
        "customer.subscription.updated",
        {"id": "sub_1", "status": "past_due", "customer": "cus_1", "items": {"data": []}},
    )
    c.post("/billing/stripe/webhook", content=body, headers={"Stripe-Signature": sign_for_test(body, "whsec_test")})
    assert store.plan(tenant) == "pro"
    body = event("customer.subscription.deleted", {"id": "sub_1", "customer": "cus_1", "items": {"data": []}})
    c.post("/billing/stripe/webhook", content=body, headers={"Stripe-Signature": sign_for_test(body, "whsec_test")})
    assert store.plan(tenant) == "free" and store.subscription(tenant)["status"] == "canceled"
    assert store.quota_for(tenant) == 5000


def test_admin_panel_and_comps(app):
    c, store = app
    store.add_usage("discord:9", 120, 5, 120000)
    assert c.get("/admin").status_code == 403
    html = c.get("/admin?token=admin-secret").text
    assert "discord:9" in html and "120 / 5,000" in html
    r = c.post("/admin/api/plan?token=admin-secret", json={"tenant": "discord:9", "plan": "unlimited"})
    assert r.status_code == 200 and store.plan("discord:9") == "unlimited" and store.quota_for("discord:9") == 0
    assert c.post("/admin/api/plan?token=admin-secret", json={"tenant": "discord:9", "plan": "gold"}).status_code == 422
    totals = c.get("/admin/api/totals", headers={"Authorization": "Bearer admin-secret"}).json()
    assert totals["judged"] == 120 and totals["plans"]["unlimited"] == 1 and "demo_spent_usd" in totals
    rows = c.get("/admin/api/tenants?token=admin-secret").json()
    assert rows[0]["tenant"] == "discord:9" and rows[0]["quota"] == 0


def test_plan_quotas_in_store(tmp_path):
    s = Store(tmp_path / "q.sqlite", monthly_quota=10)
    t = "discord:1"
    s.add_usage(t, 10, 1, 100)
    assert s.over_quota(t)
    s.set_plan(t, "pro")
    assert not s.over_quota(t) and s.quota_for(t) == int(os.environ.get("JEVMOD_PRO_MONTHLY_QUOTA", "50000") or 0)
    s.set_plan(t, "unlimited")
    assert s.quota_for(t) == 0 and not s.over_quota(t)
    s.delete_tenant(t)
    assert s.subscription(t) is None
