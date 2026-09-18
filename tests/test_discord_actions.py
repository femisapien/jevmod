"""`timeout` and `delete` used to share a branch, so a category set to time a member out also deleted their
message, which is not what the site promises and not what `/mod set <cat> timeout` reads as."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

discord = pytest.importorskip("discord")


def run_act(action: str, tmp_path):
    os.environ.setdefault("DISCORD_TOKEN", "test")
    os.environ["JEVMOD_DB"] = str(tmp_path / "act.sqlite")
    import importlib

    from jevmod.adapters import discord_bot

    importlib.reload(discord_bot)
    from jevmod.core.policy import Decision

    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.name = "test"
    guild.text_channels = []
    guild.get_channel.return_value = None
    guild.create_text_channel = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no"))

    msg = MagicMock(spec=discord.Message)
    msg.content = "hello"
    msg.delete = AsyncMock()
    msg.author = MagicMock(spec=discord.Member)
    msg.author.timeout = AsyncMock()
    msg.author.send = AsyncMock()

    d = Decision(
        message_id="m1",
        action=action,
        category="harassment",
        probability=0.99,
        scores={"harassment": 0.99},
        judged=True,
        reason="jev",
    )
    asyncio.run(discord_bot.act(guild, msg, d))
    return msg


def test_timeout_times_out_without_deleting(tmp_path):
    msg = run_act("timeout", tmp_path)
    msg.author.timeout.assert_awaited_once()
    msg.delete.assert_not_awaited()


def test_delete_deletes_without_timing_out(tmp_path):
    msg = run_act("delete", tmp_path)
    msg.delete.assert_awaited_once()
    msg.author.timeout.assert_not_awaited()


def test_flag_touches_neither(tmp_path):
    msg = run_act("flag", tmp_path)
    msg.delete.assert_not_awaited()
    msg.author.timeout.assert_not_awaited()
    msg.author.send.assert_not_awaited()
