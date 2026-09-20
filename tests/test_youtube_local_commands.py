"""#30: the YouTube adapter's ban/delete request shapes, poll-interval flooring, chat-item parsing, and chat
command dispatch -- everything in youtube_bot.py that has a right answer independent of a live poll or a
real Data API call, in the same spirit as test_twitch_local_commands.py.

youtube_bot.py needs no optional dependency (plain stdlib `urllib`), so this needs no `pytest.importorskip`
the way the Telegram/Reddit/Twitch suites do for their own optional package.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from jevmod.adapters.youtube_bot import (
    MAX_TIMEOUT_S,
    MIN_POLL_WAIT_S,
    act,
    author_channel_id,
    author_name,
    ban_request_body,
    delete_message_params,
    dispatch_rule,
    dispatch_set,
    dispatch_status,
    is_text_message,
    is_trusted,
    message_text,
    parse_command,
    poll_wait_s,
    tenant_of,
    timeout_seconds,
)
from jevmod.core import Policy

TEXT_ITEM = {
    "id": "msg1",
    "snippet": {"type": "textMessageEvent", "displayMessage": "hello world"},
    "authorDetails": {"displayName": "Foo", "channelId": "UC123", "isChatOwner": False, "isChatModerator": False},
}

# ---- tenant_of


def test_tenant_of_uses_channel_id():
    assert tenant_of("UCabc123") == "youtube:UCabc123"


# ---- timeout_seconds: the never-a-ban guardrail


def test_timeout_seconds_converts_minutes():
    assert timeout_seconds(10) == 600


def test_timeout_seconds_is_never_zero_or_negative():
    assert timeout_seconds(0) >= 1
    assert timeout_seconds(-5) >= 1


def test_timeout_seconds_clamps_to_max():
    assert timeout_seconds(999_999) == MAX_TIMEOUT_S


# ---- API request shapes: type is always temporary, never permanent


def test_ban_request_body_is_always_temporary_with_a_duration():
    body = ban_request_body("chat1", "UC999", 10)
    assert body["snippet"]["type"] == "temporary"
    assert body["snippet"]["banDurationSeconds"] == 600
    assert body["snippet"]["bannedUserDetails"]["channelId"] == "UC999"
    assert body["snippet"]["liveChatId"] == "chat1"


def test_ban_request_body_never_produces_permanent():
    for minutes in (0, 1, 10, 999_999, -5):
        body = ban_request_body("chat1", "UC999", minutes)
        assert body["snippet"]["type"] == "temporary"


def test_delete_message_params_shape():
    assert delete_message_params("msg1") == {"id": "msg1"}


# ---- poll_wait_s: floored, never a guess above what's floored


def test_poll_wait_s_honors_a_reasonable_interval():
    assert poll_wait_s(5000) == 5.0


def test_poll_wait_s_floors_a_small_interval():
    assert poll_wait_s(200) == MIN_POLL_WAIT_S


def test_poll_wait_s_floors_missing_or_invalid_values():
    assert poll_wait_s(None) == MIN_POLL_WAIT_S
    assert poll_wait_s(0) == MIN_POLL_WAIT_S
    assert poll_wait_s(-100) == MIN_POLL_WAIT_S


# ---- chat item parsing


def test_is_text_message_true_only_for_textMessageEvent():
    assert is_text_message(TEXT_ITEM) is True
    assert is_text_message({"snippet": {"type": "superChatEvent"}}) is False
    assert is_text_message({}) is False


def test_message_text_reads_display_message():
    assert message_text(TEXT_ITEM) == "hello world"
    assert message_text({}) == ""


def test_author_name_and_channel_id():
    assert author_name(TEXT_ITEM) == "Foo"
    assert author_channel_id(TEXT_ITEM) == "UC123"


def test_is_trusted_true_for_owner_or_moderator():
    assert is_trusted({"isChatOwner": True}) is True
    assert is_trusted({"isChatModerator": True}) is True
    assert is_trusted({"isChatOwner": False, "isChatModerator": False}) is False
    assert is_trusted({}) is False


# ---- chat command parsing


def test_parse_command_recognizes_prefix_case_insensitively():
    assert parse_command("!JevMod status") == ("status", [])


def test_parse_command_splits_args():
    assert parse_command("!jevmod set spam flag 0.8") == ("set", ["spam", "flag", "0.8"])


def test_parse_command_none_for_other_text():
    assert parse_command("hello everyone") is None


def test_parse_command_none_for_bare_prefix():
    assert parse_command("!jevmod") is None


# ---- dispatch_status / dispatch_set / dispatch_rule: pure, same shape as twitch's


def test_dispatch_status_reports_on_categories():
    p = Policy()
    p.set_category("spam", "flag")
    text = dispatch_status(p, 42, 3, 1000)
    assert "spam flag" in text
    assert "42" in text


def test_dispatch_set_updates_policy_and_returns_confirmation():
    p = Policy()
    text = dispatch_set(p, ["spam", "delete", "0.9"])
    assert p.actions["spam"] == "delete"
    assert p.thresholds["spam"] == 0.9
    assert "delete" in text


def test_dispatch_set_missing_args_raises_usage():
    p = Policy()
    with pytest.raises(ValueError, match="usage: !jevmod set"):
        dispatch_set(p, ["spam"])


def test_dispatch_set_invalid_action_raises():
    p = Policy()
    with pytest.raises(ValueError):
        dispatch_set(p, ["spam", "nonsense"])


def test_dispatch_rule_adds_and_removes():
    p = Policy()
    text = dispatch_rule(p, ["nofish", "no", "fishing", "content"])
    assert p.rules["nofish"] == "no fishing content"
    assert "no fishing content" in text
    text2 = dispatch_rule(p, ["nofish", "remove"])
    assert "nofish" not in p.rules
    assert "removed" in text2


def test_dispatch_rule_no_args_raises_usage():
    p = Policy()
    with pytest.raises(ValueError, match="usage: !jevmod rule"):
        dispatch_rule(p, [])


# ---- act(): flag never calls the client, delete/timeout do, and timeout never omits a duration


def test_act_none_and_off_call_nothing():
    client = MagicMock()
    d = MagicMock(action="none")
    asyncio.run(act(client, "chat1", TEXT_ITEM, d, Policy()))
    client.delete_message.assert_not_called()
    client.apply_timeout.assert_not_called()


def test_act_flag_never_touches_the_client():
    """No channel-visible destination on this platform (module docstring): flag must not call the client at
    all, only log."""
    client = MagicMock()
    d = MagicMock(action="flag", category="spam", probability=0.9)
    asyncio.run(act(client, "chat1", TEXT_ITEM, d, Policy()))
    client.delete_message.assert_not_called()
    client.apply_timeout.assert_not_called()


def test_act_delete_calls_delete_message_only():
    client = MagicMock()
    d = MagicMock(action="delete", category="spam", probability=0.9)
    asyncio.run(act(client, "chat1", TEXT_ITEM, d, Policy()))
    client.delete_message.assert_called_once_with("msg1")
    client.apply_timeout.assert_not_called()


def test_act_timeout_deletes_and_applies_a_bounded_timeout_never_a_ban():
    """The regression this guards: a real per-call `banDurationSeconds` with `type: "temporary"` reaching the
    ban endpoint, not an omitted or `"permanent"` one -- the same guarantee
    test_offline.py::test_no_adapter_can_ban_anybody checks by grepping every adapter file for the literal
    call shapes a ban would need, which this file must never contain."""
    client = MagicMock()
    d = MagicMock(action="timeout", category="harassment", probability=0.95)
    policy = Policy()
    policy.timeout_minutes = 15
    asyncio.run(act(client, "chat1", TEXT_ITEM, d, policy))
    client.delete_message.assert_called_once_with("msg1")
    client.apply_timeout.assert_called_once_with("chat1", "UC123", 15)


def test_act_skips_delete_and_timeout_when_ids_are_missing():
    client = MagicMock()
    d = MagicMock(action="timeout", category="spam", probability=0.9)
    item = {"id": "", "authorDetails": {"channelId": ""}}
    asyncio.run(act(client, "chat1", item, d, Policy()))
    client.delete_message.assert_not_called()
    client.apply_timeout.assert_not_called()
