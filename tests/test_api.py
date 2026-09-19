"""HTTP API end to end with FastAPI's test client and the real Jev API."""

import pytest
from conftest import KEY, NO_KEY_REASON

pytestmark = pytest.mark.skipif(not KEY, reason=NO_KEY_REASON)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JEVMOD_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.setenv("JEVMOD_ADMIN_TOKEN", "admin-secret")
    import importlib

    from jevmod.api import server

    importlib.reload(server)
    from fastapi.testclient import TestClient

    return TestClient(server.app)


def test_keys_policy_moderate_and_audit(client):
    assert client.get("/v1/health").json()["ok"] is True
    # admin creates a key for a tenant
    r = client.post(
        "/v1/keys", json={"tenant": "api:acme", "label": "test"}, headers={"Authorization": "Bearer admin-secret"}
    )
    assert r.status_code == 200
    key = r.json()["api_key"]
    auth = {"Authorization": f"Bearer {key}"}
    assert client.post("/v1/keys", json={"tenant": "x"}, headers=auth).status_code == 403  # tenants cannot mint keys
    assert client.post("/v1/moderate", json={"messages": [{"text": "hi"}]}).status_code == 401

    # policy: scam -> delete, plus a custom rule
    r = client.put(
        "/v1/policy",
        json={"actions": {"scam": "delete"}, "rules": {"no_politics": "No political discussion here."}},
        headers=auth,
    )
    assert r.status_code == 200 and r.json()["actions"]["scam"] == "delete"

    r = client.post(
        "/v1/moderate",
        json={
            "messages": [
                {
                    "id": "a",
                    "text": "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro",
                    "channel_topic": "gaming",
                },
                {"id": "b", "text": "Anyone know if the patch fixed the inventory bug?", "channel_topic": "gaming"},
                {
                    "id": "c",
                    "text": "The left is destroying this country, vote them out next month",
                    "channel_topic": "gaming",
                },
                {"id": "d", "text": "ok", "channel_topic": "gaming"},
            ]
        },
        headers={**auth, "X-Request-Id": "req-1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request_id"] == "req-1"
    d = {x["message_id"]: x for x in body["decisions"]}
    assert d["a"]["action"] == "delete" and d["a"]["category"] == "scam", d["a"]
    assert d["b"]["action"] == "none" and d["b"]["judged"]
    assert d["c"]["action"] == "flag" and d["c"]["category"] == "rule:no_politics", d["c"]
    assert d["d"]["judged"] is False and d["d"]["reason"] == "too short"
    assert body["usage"]["judged_this_month"] == 3

    log = client.get("/v1/decisions", headers=auth).json()
    assert {x["message_id"] for x in log} == {"a", "c"}
    assert client.get("/metrics").text.startswith("jevmod_http_requests_total 1")
    assert client.delete("/v1/tenant", headers=auth).json()["deleted"] is True
