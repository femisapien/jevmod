"""Call a running `jevmod api` with the standard library: mint a tenant key, moderate a batch."""

import json
import os
import urllib.request

URL = os.environ.get("JEVMOD_URL", "http://localhost:8080")


def post(path: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        URL + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def moderate(api_key: str, texts: list[str], topic: str = "") -> list[dict]:
    body = {"messages": [{"id": str(i), "text": t, "channel_topic": topic} for i, t in enumerate(texts)]}
    return post("/v1/moderate", api_key, body)["decisions"]


if __name__ == "__main__":
    admin = os.environ["JEVMOD_ADMIN_TOKEN"]
    key = post("/v1/keys", admin, {"tenant": "example-python", "label": "python_client.py"})["api_key"]
    for d in moderate(key, ["FREE NITRO!! claim at discord-gifts.ru/nitro", "did the patch fix the inventory bug?"]):
        print(d["message_id"], d["action"], d["category"], d["probability"])
