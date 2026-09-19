"""L3: the Discord surface for local rules (`/mod link`, `/mod words`, `/mod pattern`, `/mod raid`) and the
`on_member_join` anti-raid counter.

The bot itself is hard to test end to end (it needs a live gateway connection), so this tests the two things
that have a right answer without one: the pure helpers the commands are built from (`_toggle_list`,
`_chunked_list`), and `on_member_join`'s counting/alerting logic against a mocked guild, the same way
`test_discord_actions.py` mocks `act()`. The slash command callbacks themselves (`link_cmd`, `words_cmd`,
`pattern_cmd`, `raid_cmd`) are not covered here: exercising them needs a mocked `discord.Interaction` with a
working `response`/`followup` pair and `app_commands` invocation plumbing, which is framework wiring rather
than logic with a right answer, and is genuinely not covered by this suite.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

discord = pytest.importorskip("discord")


# ---- _toggle_list: pure add/remove, no Discord


def test_toggle_add_appends_once():
    from jevmod.adapters.discord_bot import _toggle_list

    out = _toggle_list(["a"], "b", "add")
    assert out == ["a", "b"]


def test_toggle_add_is_idempotent():
    from jevmod.adapters.discord_bot import _toggle_list

    out = _toggle_list(["a", "b"], "b", "add")
    assert out == ["a", "b"]


def test_toggle_remove_drops_it():
    from jevmod.adapters.discord_bot import _toggle_list

    out = _toggle_list(["a", "b"], "a", "remove")
    assert out == ["b"]


def test_toggle_remove_missing_is_a_noop():
    from jevmod.adapters.discord_bot import _toggle_list

    out = _toggle_list(["a"], "z", "remove")
    assert out == ["a"]


def test_toggle_add_blank_is_a_noop():
    from jevmod.adapters.discord_bot import _toggle_list

    out = _toggle_list(["a"], "   ", "add")
    assert out == ["a"]


def test_toggle_does_not_mutate_the_input_list():
    from jevmod.adapters.discord_bot import _toggle_list

    original = ["a"]
    _toggle_list(original, "b", "add")
    assert original == ["a"]


# ---- _chunked_list: a hundred entries cannot be dumped into one reply without thought


def test_chunked_list_empty_reads_as_none():
    from jevmod.adapters.discord_bot import _chunked_list

    assert _chunked_list([]) == "(none)"


def test_chunked_list_shows_everything_that_fits():
    from jevmod.adapters.discord_bot import _chunked_list

    text = _chunked_list(["one", "two", "three"])
    assert "`one`" in text and "`two`" in text and "`three`" in text
    assert "more not shown" not in text


def test_chunked_list_truncates_and_says_how_many_were_left_off():
    from jevmod.adapters.discord_bot import _chunked_list

    words = [f"word{i}" for i in range(500)]  # far more than fits under any sane limit
    text = _chunked_list(words, limit=200)
    assert len(text) < 400  # comfortably under Discord's 2000-char reply limit, with room for the rest of the reply
    assert "more not shown" in text
    shown = text.split("\n\n")[0].count("`") // 2
    assert shown < len(words)


def test_chunked_list_never_exceeds_the_requested_limit_by_more_than_the_footer():
    from jevmod.adapters.discord_bot import _chunked_list

    words = [f"word{i}" for i in range(50)]
    for limit in (10, 50, 100, 1800):
        text = _chunked_list(words, limit=limit)
        body = text.split("\n\n")[0]
        assert len(body) <= limit


# ---- on_member_join: the join counter and the one-message trip


def _reload_bot(tmp_path):
    os.environ.setdefault("DISCORD_TOKEN", "test")
    os.environ["JEVMOD_DB"] = str(tmp_path / "join.sqlite")
    import importlib

    from jevmod.adapters import discord_bot

    importlib.reload(discord_bot)
    return discord_bot


def _guild_with_log_channel(bot_module):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 42
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    guild.get_channel.return_value = channel
    bot_module.store.set_meta(bot_module.tenant_of(guild.id), log_channel=999)
    return guild, channel


def _member(guild, member_id):
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.guild = guild
    return member


def test_join_below_threshold_sends_nothing(tmp_path):
    bot_module = _reload_bot(tmp_path)
    guild, channel = _guild_with_log_channel(bot_module)
    tenant = bot_module.tenant_of(guild.id)
    policy = bot_module.service.policy(tenant)
    policy.set_raid(joins=3, repeats=0)
    bot_module.service.save_policy(tenant, policy)

    asyncio.run(bot_module.on_member_join(_member(guild, 1)))
    asyncio.run(bot_module.on_member_join(_member(guild, 2)))
    channel.send.assert_not_awaited()


def test_join_at_threshold_plus_one_alerts_exactly_once(tmp_path):
    bot_module = _reload_bot(tmp_path)
    guild, channel = _guild_with_log_channel(bot_module)
    tenant = bot_module.tenant_of(guild.id)
    policy = bot_module.service.policy(tenant)
    policy.set_raid(joins=3, repeats=0)
    bot_module.service.save_policy(tenant, policy)

    for member_id in range(1, 6):  # 5 distinct joins against a threshold of 3
        asyncio.run(bot_module.on_member_join(_member(guild, member_id)))

    channel.send.assert_awaited_once()  # the 4th join trips it; the 5th must not alert again
    (message,), _ = channel.send.call_args
    assert "Possible raid" in message
    assert "does not remove members, kick anyone or lock the server" in message


def test_raid_joins_off_never_counts_or_alerts(tmp_path):
    bot_module = _reload_bot(tmp_path)
    guild, channel = _guild_with_log_channel(bot_module)
    tenant = bot_module.tenant_of(guild.id)
    assert bot_module.service.policy(tenant).raid_joins == 0  # default

    for member_id in range(1, 10):
        asyncio.run(bot_module.on_member_join(_member(guild, member_id)))
    channel.send.assert_not_awaited()
