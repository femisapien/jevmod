"""JEV-83: a lone UTF-16 surrogate in a request is refused before Jev is called, never after.

Offline: Jev is a fake client that counts calls and answers every question, so "was the model paid"
is a number these tests read rather than a claim. The request bodies are raw JSON with the escape
written out (`\\ud83d`), because that is the only way a surrogate arrives over HTTP: a client cannot
send one as UTF-8 bytes, and `json.loads` is what turns the escape into one.
"""

from __future__ import annotations

import importlib
import json

import pytest
from typesafe_sdk import NoulAnswer

from jevmod.core.policy import Policy
from jevmod.core.service import ModerationService
from jevmod.core.store import Store
from jevmod.core.surrogates import contains_lone_surrogate, replace_lone_surrogates, scrub
from jevmod.judge import Judge, Message

HIGH = "\\ud83d"  # a high surrogate, written as it appears inside a JSON string
LOW = "\\ude00"  # a low surrogate
SPAM = "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"


class _Jev:
    """Answers every question with 0.99, so a message that reaches it is flagged and logged, which is the
    path that used to write `author` and `id` after paying."""

    def __init__(self) -> None:
        self.calls = 0

    def system_one(self, state, questions):
        self.calls += 1
        # The real client serialises the request; a surrogate that got this far would fail here.
        json.dumps(state, ensure_ascii=False).encode("utf-8")

        class Resp:
            answers = {k: NoulAnswer(noul=0.99) for k in questions}
            usage = None

        return Resp()


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("JEVMOD_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.setenv("JEVMOD_KEYMINT_TOKEN", "mint")
    from jevmod.api import server

    importlib.reload(server)
    jev = _Jev()
    server.service._judge = Judge(client=jev, cache_ttl_s=0)
    from fastapi.testclient import TestClient

    client = TestClient(server.app, raise_server_exceptions=False)
    key = client.post("/v1/keys", json={"tenant": "t"}, headers={"Authorization": "Bearer mint"}).json()["api_key"]
    auth = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    return client, auth, jev, server


def _message(**fields: str) -> str:
    """One message as raw JSON, with `fields` spliced in unescaped so a `\\ud83d` stays an escape."""
    base = {"id": "a", "text": SPAM, "author": "someone", "channel_topic": "gaming"}
    base.update({k: "@@" + k for k in fields})
    raw = json.dumps(base)
    for k, v in fields.items():
        raw = raw.replace(f'"@@{k}"', f'"{v}"')
    return raw


@pytest.mark.parametrize("field", ["id", "author", "text", "channel_topic"])
@pytest.mark.parametrize("where", ["x" + HIGH, HIGH + "x", "x" + LOW, LOW + HIGH])
def test_a_lone_surrogate_in_any_field_is_a_422_naming_it_and_nothing_is_paid(api, field, where):
    client, auth, jev, server = api
    r = client.post("/v1/moderate", content='{"messages":[' + _message(**{field: where}) + "]}", headers=auth)
    assert r.status_code == 422, r.text
    locs = [e["loc"] for e in r.json()["detail"]]
    assert ["body", "messages", 0, field] in locs
    assert jev.calls == 0, "the model was called for a request that was then refused"
    assert server.store.usage("t") == (0, 0, 0)


def test_the_bad_message_can_sit_anywhere_in_the_batch(api):
    client, auth, jev, _ = api
    good = _message()
    body = '{"messages":[' + ",".join([good] * 7 + [_message(author="a" + HIGH)] + [good] * 3) + "]}"
    r = client.post("/v1/moderate", content=body, headers=auth)
    assert r.status_code == 422
    assert ["body", "messages", 7, "author"] in [e["loc"] for e in r.json()["detail"]]
    assert jev.calls == 0


def test_the_same_request_without_the_surrogate_is_judged_and_logged(api):
    """The control: the fake answers 0.99, so this is flagged, logged with its author, and answered 200."""
    client, auth, jev, server = api
    r = client.post("/v1/moderate", content='{"messages":[' + _message() + "]}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["decisions"][0]["action"] == "flag"
    assert jev.calls == 1
    assert server.store.recent_decisions("t", 5)[0]["author"] == "someone"


def test_a_whole_surrogate_pair_is_an_emoji_and_is_accepted(api):
    client, auth, jev, server = api
    body = '{"messages":[' + _message(author="x" + HIGH + LOW, id="id" + HIGH + LOW) + "]}"
    r = client.post("/v1/moderate", content=body, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["decisions"][0]["message_id"] == "id\U0001f600"
    assert server.store.recent_decisions("t", 5)[0]["author"] == "x\U0001f600"


def test_a_rule_with_a_surrogate_is_refused_and_does_not_break_the_server_after(api):
    """It used to be saved (json.dumps escapes it), answer 500 to the PUT that saved it, and then make every
    `/v1/moderate` for that server fail, because the rules are part of every cache key."""
    client, auth, jev, _ = api
    for body in (
        '{"rules":{"r":"no ' + HIGH + ' spam"}}',
        '{"rules":{"r' + HIGH + '":"no spam"}}',
        '{"actions":{"spam' + LOW + '":"flag"}}',
        '{"rule_thresholds":{"r' + HIGH + '":0.9}}',
    ):
        r = client.put("/v1/policy", content=body, headers=auth)
        assert r.status_code == 422, (body, r.text)
        json.loads(r.content.decode("ascii"))  # the error itself is sendable and is JSON
    assert client.get("/v1/policy", headers=auth).json()["rules"] == {}
    r = client.post("/v1/moderate", content='{"messages":[' + _message() + "]}", headers=auth)
    assert r.status_code == 200 and jev.calls == 1


def test_minting_a_key_for_a_surrogate_tenant_is_refused(api):
    client, _, _, _ = api
    r = client.post(
        "/v1/keys",
        content='{"tenant":"t' + HIGH + '"}',
        headers={"Authorization": "Bearer mint", "Content-Type": "application/json"},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ callers that are not the HTTP API


def test_the_service_repairs_text_so_one_message_cannot_break_its_channel(tmp_path):
    """An adapter has nobody to answer 422 to. Before the fix the surrogate went into the conversation
    window, and every later message in that channel failed on its cache key for as long as it stayed there."""
    jev = _Jev()
    svc = ModerationService(Store(tmp_path / "s.sqlite"), judge=Judge(client=jev, cache_ttl_s=0))
    bad = "half an emoji \ud83d at the end of " + SPAM
    first = svc.moderate("discord:1", [Message("1", bad, author="nick\udc80", channel="c")])
    assert first[0].action == "flag"
    later = svc.moderate("discord:1", [Message("2", "and then somebody says something ordinary", channel="c")])
    assert later[0].judged
    assert jev.calls == 2
    window = svc.context.window_for(("discord:1", "c"))
    assert not any(contains_lone_surrogate(t) for t in window)
    assert svc.store.recent_decisions("discord:1", 5)[-1]["author"] == "nick\ufffd"


def test_the_service_refuses_a_surrogate_id_before_calling_the_model(tmp_path):
    jev = _Jev()
    svc = ModerationService(Store(tmp_path / "s.sqlite"), judge=Judge(client=jev, cache_ttl_s=0))
    with pytest.raises(ValueError, match="surrogate"):
        svc.moderate("t", [Message("fine", SPAM), Message("id\ud83d", SPAM)])
    assert jev.calls == 0
    assert svc.store.usage("t") == (0, 0, 0)


def test_a_policy_stored_with_a_surrogate_before_the_fix_is_repaired_on_load(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    p = Policy()
    p.rules["r\ud83d"] = "no \udc80 spam"  # written directly, as an older version's PUT would have
    store.save_policy("t", p)
    loaded = store.get_policy("t")
    assert loaded.rules == {"r\ufffd": "no \ufffd spam"}
    jev = _Jev()
    svc = ModerationService(store, judge=Judge(client=jev, cache_ttl_s=0))
    assert svc.moderate("t", [Message("1", SPAM)])[0].judged
    assert jev.calls == 1


def test_set_rule_refuses_a_surrogate():
    with pytest.raises(ValueError, match="surrogate"):
        Policy().set_rule("r", "no \ud83d spam")


def test_the_helpers():
    assert not contains_lone_surrogate("plain \U0001f600 text")
    assert contains_lone_surrogate("a\ud83d") and contains_lone_surrogate("\udc80")
    assert replace_lone_surrogates("a\ud83db") == "a\ufffdb"
    assert replace_lone_surrogates("\ude00\ud83d") == "\ufffd\ufffd"  # reversed: not a pair
    assert replace_lone_surrogates("\ud83d\ude00") == "\U0001f600"  # a pair held as two code points
    s = "untouched"
    assert replace_lone_surrogates(s) is s
    assert scrub({"k\ud83d": ["v\udc80", 1, {"x": "y"}]}) == {"k\ufffd": ["v\ufffd", 1, {"x": "y"}]}


@pytest.mark.parametrize("body", ['{"timeout_minutes":NaN}', '{"timeout_minutes":Infinity}'])
def test_a_422_echoing_nan_or_infinity_is_still_a_422(api, body):
    """Red-team round 1: `json.loads` accepts NaN, the 422 echoes it, and strict JSON cannot write it."""
    client, auth, jev, _ = api
    r = client.put("/v1/policy", content=body, headers=auth)
    assert r.status_code == 422, r.text
    r = client.post("/v1/moderate", content='{"messages":[{"text":NaN}]}', headers=auth)
    assert r.status_code == 422 and jev.calls == 0


def test_the_service_refuses_a_surrogate_request_id_before_calling_the_model(tmp_path):
    jev = _Jev()
    svc = ModerationService(Store(tmp_path / "s.sqlite"), judge=Judge(client=jev, cache_ttl_s=0))
    with pytest.raises(ValueError, match="surrogate"):
        svc.moderate("t", [Message("1", SPAM)], request_id="r\ud800")
    assert jev.calls == 0
