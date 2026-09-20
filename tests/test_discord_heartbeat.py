"""Nobody watches the Discord gateway connection today: the hosted monitor
(`jevmod_hosted/monitor.py`, in the private repo) polls the demo API and the web app, but the bot is a
separate container it must not reach into. `_write_heartbeat` closes that gap from the bot's own side: a
small JSON file with a timestamp, written on a loop only while the gateway session is actually up, that the
monitor can read the age of without ever touching this process.

Off by default, on purpose: `JEVMOD_HEARTBEAT_FILE` unset means this writes nothing, costs nothing, and a
self-hosted deployment of the open bot with no monitor next to it never has to know this exists.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import time

import pytest

discord = pytest.importorskip("discord")


def _reload(tmp_path, monkeypatch, heartbeat_file: str | None):
    os.environ.setdefault("DISCORD_TOKEN", "test")
    monkeypatch.setenv("JEVMOD_DB", str(tmp_path / "hb.sqlite"))
    if heartbeat_file is None:
        monkeypatch.delenv("JEVMOD_HEARTBEAT_FILE", raising=False)
    else:
        monkeypatch.setenv("JEVMOD_HEARTBEAT_FILE", heartbeat_file)

    from jevmod.adapters import discord_bot

    importlib.reload(discord_bot)
    return discord_bot


def test_writes_nothing_when_not_configured(tmp_path, monkeypatch):
    discord_bot = _reload(tmp_path, monkeypatch, None)
    assert discord_bot.HEARTBEAT_FILE == ""
    discord_bot.bot.is_ready = lambda: True
    asyncio.run(discord_bot._write_heartbeat())
    assert not (tmp_path / "bot-heartbeat.json").exists()


def test_writes_a_fresh_timestamp_while_ready(tmp_path, monkeypatch):
    path = tmp_path / "bot-heartbeat.json"
    discord_bot = _reload(tmp_path, monkeypatch, str(path))
    discord_bot.bot.is_ready = lambda: True
    before = time.time()

    asyncio.run(discord_bot._write_heartbeat())

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ts"] >= before


def test_writes_nothing_while_the_gateway_is_not_ready(tmp_path, monkeypatch):
    """The whole point: a dropped gateway session must leave the file stale so the monitor's staleness
    check has something to notice, not get a fresh, healthy-looking timestamp anyway."""
    path = tmp_path / "bot-heartbeat.json"
    discord_bot = _reload(tmp_path, monkeypatch, str(path))
    discord_bot.bot.is_ready = lambda: False

    asyncio.run(discord_bot._write_heartbeat())

    assert not path.exists()


def test_a_write_failure_is_swallowed_not_raised(tmp_path, monkeypatch):
    """Mirrors `monitor.py`'s own `_save_state`: a heartbeat writer that crashes trying to report itself
    has turned one problem into two."""
    (tmp_path / "not-a-dir").write_text("i am a file")
    bad_path = str(tmp_path / "not-a-dir" / "deeper" / "heartbeat.json")
    discord_bot = _reload(tmp_path, monkeypatch, bad_path)
    discord_bot.bot.is_ready = lambda: True

    asyncio.run(discord_bot._write_heartbeat())  # must not raise


def test_on_ready_starts_the_heartbeat_loop_only_when_configured(tmp_path, monkeypatch):
    """A self-hosted bot with `JEVMOD_HEARTBEAT_FILE` unset must never start the loop at all -- not just
    skip writing inside it -- so there is truly nothing running for a self-hosted operator to wonder about."""
    discord_bot = _reload(tmp_path, monkeypatch, None)
    assert not discord_bot._write_heartbeat.is_running()
