"""The public demo endpoint: CORS allow-list, per-IP limits, hard budget, logging and admin stats. Real Jev."""

import importlib
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JEVMOD_DEMO_DB", str(tmp_path / "demo.sqlite"))
    monkeypatch.setenv("JEVMOD_DEMO_PER_MINUTE", "3")
    monkeypatch.setenv("JEVMOD_DEMO_BUDGET_USD", "0.5")
    monkeypatch.setenv("JEVMOD_DEMO_ORIGINS", "https://example.github.io")
    monkeypatch.setenv("JEVMOD_ADMIN_TOKEN", "admin-secret")
    from jevmod.api import demo

    importlib.reload(demo)
    from fastapi.testclient import TestClient

    return TestClient(demo.app), demo


def test_check_limits_and_stats(client):
    c, demo = client
    assert c.get("/demo/health").json()["open"] is True
    r = c.post("/demo/check", json={"text": "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "scam" and body["action"] == "flag" and body["budget_left_usd"] < 0.5
    # the same text again is a cache hit and costs nothing
    r2 = c.post("/demo/check", json={"text": "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"})
    assert r2.json()["reason"] == "cache"
    # too long
    assert c.post("/demo/check", json={"text": "x" * 301}).status_code == 422
    # third call in the minute is the last allowed; the fourth is refused
    c.post("/demo/check", json={"text": "Anyone know if the patch fixed the inventory bug?"})
    assert (
        c.post("/demo/check", json={"text": "gg everyone, that raid was clean. same time tomorrow?"}).status_code == 429
    )
    # CORS: allowed origin gets the header, another does not
    ok = c.options(
        "/demo/check",
        headers={"Origin": "https://example.github.io", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "https://example.github.io"
    bad = c.options("/demo/check", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
    # admin
    assert c.get("/demo/stats").status_code == 403
    s = c.get("/demo/stats", headers={"Authorization": "Bearer admin-secret"}).json()
    assert s["checks"] == 3 and s["cache_hits"] == 1 and s["spent_usd"] < 0.01 and s["by_category"]["scam"] == 2
    rec = c.get("/demo/recent", headers={"Authorization": "Bearer admin-secret"}).json()
    assert len(rec) == 3 and "FREE NITRO" in rec[-1]["text"]


def test_budget_closes_the_demo(client, monkeypatch):
    c, demo = client
    monkeypatch.setattr(demo, "BUDGET_USD", 0.0)
    r = c.post("/demo/check", json={"text": "hello there, is the shop open today?"})
    assert r.status_code == 503 and "budget" in r.json()["detail"]
