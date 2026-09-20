"""#29: the Twitch adapter's IRC line parsing, timeout-duration guardrail, Helix request shapes, and chat
command dispatch -- everything in twitch_bot.py that has a right answer independent of a live socket or a
real Helix call, in the same spirit as test_discord_local_commands.py and test_telegram_local_commands.py.

The module itself imports cleanly without the `websockets` package (it is only imported inside `run()`),
so none of this needs `pytest.importorskip` the way the Telegram/Reddit suites do for their own optional
dependency -- everything tested here is stdlib plus jevmod.core.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from jevmod.adapters.twitch_bot import (
    MAX_TIMEOUT_S,
    IrcMessage,
    act,
    channel_of,
    delete_message_params,
    dispatch_rule,
    dispatch_set,
    dispatch_status,
    is_moderator,
    is_privmsg,
    parse_command,
    parse_irc_line,
    parse_tags,
    tenant_of,
    timeout_request_body,
    timeout_seconds,
)
from jevmod.core import Policy

RAW_PRIVMSG = (
    "@badge-info=;badges=moderator/1;color=;display-name=Foo;id=abc-123;mod=1;room-id=1;"
    "subscriber=0;tmi-sent-ts=1;turbo=0;user-id=99;user-type=mod "
    ":foo!foo@foo.tmi.twitch.tv PRIVMSG #bar :hello world"
)

# ---- tenant_of


def test_tenant_of_strips_hash_and_lowercases():
    assert tenant_of("#SomeChannel") == "twitch:somechannel"
    assert tenant_of("SomeChannel") == "twitch:somechannel"


# ---- IRC tag parsing


def test_parse_tags_splits_key_value_pairs():
    assert parse_tags("mod=1;color=;id=abc") == {"mod": "1", "color": "", "id": "abc"}


def test_parse_tags_unescapes_semicolon_space_and_backslash():
    # \: -> ; , \s -> space, \\ -> \
    assert parse_tags(r"display-name=a\:b\sc\\d") == {"display-name": "a;b c\\d"}


def test_parse_tags_ignores_empty_pairs():
    assert parse_tags("a=1;;b=2") == {"a": "1", "b": "2"}


# ---- full-line parsing


def test_parse_irc_line_privmsg_with_tags_and_prefix():
    msg = parse_irc_line(RAW_PRIVMSG)
    assert msg.command == "PRIVMSG"
    assert msg.params == ["#bar"]
    assert msg.trailing == "hello world"
    assert msg.tags["display-name"] == "Foo"
    assert msg.tags["user-id"] == "99"
    assert msg.prefix == "foo!foo@foo.tmi.twitch.tv"


def test_parse_irc_line_ping_has_no_tags_or_prefix():
    msg = parse_irc_line("PING :tmi.twitch.tv")
    assert msg.command == "PING"
    assert msg.trailing == "tmi.twitch.tv"
    assert msg.tags == {}


def test_parse_irc_line_handles_trailing_crlf():
    msg = parse_irc_line("PING :tmi.twitch.tv\r\n")
    assert msg.trailing == "tmi.twitch.tv"


def test_is_privmsg_true_only_for_privmsg_with_trailing():
    assert is_privmsg(parse_irc_line(RAW_PRIVMSG)) is True
    assert is_privmsg(parse_irc_line("PING :tmi.twitch.tv")) is False
    assert is_privmsg(IrcMessage(command="PRIVMSG", params=["#bar"], trailing=None)) is False


def test_channel_of_strips_hash():
    assert channel_of(parse_irc_line(RAW_PRIVMSG)) == "bar"


# ---- is_moderator: broadcaster OR mod=1, nothing else


def test_is_moderator_true_for_mod_flag():
    assert is_moderator({"mod": "1", "badges": ""}) is True


def test_is_moderator_true_for_broadcaster_badge_even_with_mod_zero():
    assert is_moderator({"mod": "0", "badges": "broadcaster/1,subscriber/12"}) is True


def test_is_moderator_false_for_plain_viewer():
    assert is_moderator({"mod": "0", "badges": "subscriber/3"}) is False


def test_is_moderator_false_for_empty_tags():
    assert is_moderator({}) is False


# ---- timeout_seconds: the never-a-ban guardrail


def test_timeout_seconds_converts_minutes():
    assert timeout_seconds(10) == 600


def test_timeout_seconds_is_never_zero_or_negative():
    assert timeout_seconds(0) >= 1
    assert timeout_seconds(-5) >= 1


def test_timeout_seconds_clamps_to_twitch_maximum():
    assert timeout_seconds(999_999) == MAX_TIMEOUT_S


# ---- Helix request shapes: duration is always present, reason is always bounded


def test_timeout_request_body_always_includes_duration():
    body = timeout_request_body("123", 10, "jevmod: spam p=0.90")
    assert body["data"]["duration"] == 600
    assert body["data"]["user_id"] == "123"
    assert "duration" in body["data"]  # explicit: this is the whole guardrail


def test_timeout_request_body_truncates_long_reason():
    body = timeout_request_body("123", 5, "x" * 1000)
    assert len(body["data"]["reason"]) <= 500


def test_delete_message_params_shape():
    params = delete_message_params("bid", "mid", "msgid")
    assert params == {"broadcaster_id": "bid", "moderator_id": "mid", "message_id": "msgid"}


# ---- chat command parsing


def test_parse_command_recognizes_prefix_case_insensitively():
    assert parse_command("!JevMod status") == ("status", [])


def test_parse_command_splits_args():
    assert parse_command("!jevmod set spam flag 0.8") == ("set", ["spam", "flag", "0.8"])


def test_parse_command_none_for_other_text():
    assert parse_command("hello everyone") is None


def test_parse_command_none_for_bare_prefix():
    assert parse_command("!jevmod") is None


# ---- dispatch_status / dispatch_set / dispatch_rule: pure, same shape as telegram's _dispatch_*


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


# ---- act(): flag never calls Helix, delete/timeout do, and timeout never omits duration


def test_act_none_and_off_call_nothing():
    helix = MagicMock()
    d = MagicMock(action="none")
    asyncio.run(act(helix, "bid", "mid", {"id": "x"}, d, Policy()))
    helix.delete_message.assert_not_called()
    helix.apply_timeout.assert_not_called()


def test_act_flag_never_touches_helix():
    """No channel-visible destination on this platform (module docstring): flag must not call Helix at all,
    only log."""
    helix = MagicMock()
    d = MagicMock(action="flag", category="spam", probability=0.9)
    asyncio.run(act(helix, "bid", "mid", {"id": "x"}, d, Policy()))
    helix.delete_message.assert_not_called()
    helix.apply_timeout.assert_not_called()
    helix.assert_not_called()


def test_act_delete_calls_delete_message_only():
    helix = MagicMock()
    d = MagicMock(action="delete", category="spam", probability=0.9)
    asyncio.run(act(helix, "bid", "mid", {"id": "msg1", "user-id": "77"}, d, Policy()))
    helix.delete_message.assert_called_once_with("bid", "mid", "msg1")
    helix.apply_timeout.assert_not_called()


def test_act_timeout_deletes_and_applies_a_bounded_timeout_never_a_ban():
    """The regression this guards: a real per-call `duration` reaching Helix's ban/timeout endpoint, not an
    omitted one -- the same guarantee test_offline.py::test_no_adapter_can_ban_anybody checks by grepping
    every adapter file for the literal call shapes a ban would need, which this file must never contain."""
    helix = MagicMock()
    d = MagicMock(action="timeout", category="harassment", probability=0.95)
    policy = Policy()
    policy.timeout_minutes = 15
    asyncio.run(act(helix, "bid", "mid", {"id": "msg1", "user-id": "77"}, d, policy))
    helix.delete_message.assert_called_once_with("bid", "mid", "msg1")
    helix.apply_timeout.assert_called_once()
    args = helix.apply_timeout.call_args.args
    assert args[:4] == ("bid", "mid", "77", 15)  # minutes passed through; timeout_seconds() converts it


def test_act_timeout_without_a_user_id_tag_only_deletes():
    """Twitch always sends `user-id` on a real PRIVMSG; this is the honest degrade for a malformed or
    stripped tag set rather than crashing the batch."""
    helix = MagicMock()
    d = MagicMock(action="timeout", category="spam", probability=0.9)
    asyncio.run(act(helix, "bid", "mid", {"id": "msg1"}, d, Policy()))
    helix.delete_message.assert_called_once()
    helix.apply_timeout.assert_not_called()


def test_act_swallows_helix_exceptions():
    helix = MagicMock()
    helix.delete_message.side_effect = RuntimeError("rate limited")
    d = MagicMock(action="delete", category="spam", probability=0.9)
    asyncio.run(act(helix, "bid", "mid", {"id": "msg1"}, d, Policy()))  # must not raise


# ---- no adapter file may contain a ban/kick call shape, twitch_bot.py included -- sanity mirror of
# test_offline.py::test_no_adapter_can_ban_anybody, kept here so a change to this file that trips it is
# caught by the file most likely to be edited, not only by the cross-adapter sweep.


def test_twitch_bot_source_has_no_ban_or_kick_call_shape():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "jevmod" / "adapters" / "twitch_bot.py"
    code = "\n".join(
        line for line in src.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("banned.add", ".ban(", "ban_reason", ".kick("):
        assert forbidden not in code
