"""Per-guild configuration and usage counters in one SQLite file. No external services."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_THRESHOLDS = {"spam": 0.85, "scam": 0.8, "harassment": 0.75, "nsfw": 0.85, "offtopic": 0.9}
DEFAULT_ACTIONS = {"spam": "flag", "scam": "flag", "harassment": "flag", "nsfw": "flag", "offtopic": "off"}
ACTIONS = ("off", "flag", "delete", "timeout")
FREE_MONTHLY = 5000


@dataclass
class GuildConfig:
    guild_id: int
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    actions: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ACTIONS))
    rules: dict[str, str] = field(default_factory=dict)  # name -> natural-language rule
    rule_actions: dict[str, str] = field(default_factory=dict)  # name -> action (default flag)
    log_channel: int | None = None
    trusted_roles: list[int] = field(default_factory=list)
    channel_topics: dict[str, str] = field(default_factory=dict)  # channel_id -> topic for offtopic checks
    timeout_minutes: int = 10
    plan: str = "free"  # "free" | "pro"

    def enabled_categories(self) -> list[str]:
        return [c for c, a in self.actions.items() if a != "off"]


class Store:
    def __init__(self, path: str | Path = "jevmod.sqlite") -> None:
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS guilds (id INTEGER PRIMARY KEY, cfg TEXT NOT NULL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS usage (guild INTEGER, month TEXT, judged INTEGER, requests INTEGER, tokens INTEGER, "
            "PRIMARY KEY (guild, month))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS decisions (ts REAL, guild INTEGER, channel INTEGER, message INTEGER, author INTEGER, "
            "category TEXT, p REAL, action TEXT, text TEXT)"
        )
        self.db.commit()

    def get(self, guild_id: int) -> GuildConfig:
        row = self.db.execute("SELECT cfg FROM guilds WHERE id=?", (guild_id,)).fetchone()
        if not row:
            return GuildConfig(guild_id)
        d = json.loads(row[0])
        cfg = GuildConfig(guild_id)
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    def save(self, cfg: GuildConfig) -> None:
        d = {k: v for k, v in cfg.__dict__.items() if k != "guild_id"}
        self.db.execute("INSERT OR REPLACE INTO guilds (id, cfg) VALUES (?, ?)", (cfg.guild_id, json.dumps(d)))
        self.db.commit()

    @staticmethod
    def month() -> str:
        return time.strftime("%Y-%m")

    def add_usage(self, guild_id: int, judged: int, requests: int, tokens: int) -> None:
        self.db.execute(
            "INSERT INTO usage (guild, month, judged, requests, tokens) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild, month) DO UPDATE SET judged=judged+excluded.judged, requests=requests+excluded.requests, "
            "tokens=tokens+excluded.tokens",
            (guild_id, self.month(), judged, requests, tokens),
        )
        self.db.commit()

    def usage(self, guild_id: int) -> tuple[int, int, int]:
        row = self.db.execute(
            "SELECT judged, requests, tokens FROM usage WHERE guild=? AND month=?", (guild_id, self.month())
        ).fetchone()
        return tuple(row) if row else (0, 0, 0)

    def over_quota(self, cfg: GuildConfig) -> bool:
        return cfg.plan == "free" and self.usage(cfg.guild_id)[0] >= FREE_MONTHLY

    def log_decision(self, guild: int, channel: int, message: int, author: int, category: str, p: float, action: str, text: str) -> None:
        self.db.execute(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), guild, channel, message, author, category, p, action, text[:300]),
        )
        self.db.commit()

    def recent_decisions(self, guild: int, n: int = 10) -> list[tuple]:
        return self.db.execute(
            "SELECT ts, category, p, action, text FROM decisions WHERE guild=? ORDER BY ts DESC LIMIT ?", (guild, n)
        ).fetchall()
