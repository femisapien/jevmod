"""Tenant policies, usage counters, an optional monthly quota and the audit log, in SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..judge import Message
from .policy import Decision, Policy

# Optional cost guard per tenant per month. 0 (the default) means unlimited; set JEVMOD_MONTHLY_QUOTA=5000 to pause
# judging for a tenant after 5,000 judged messages in a calendar month (nothing is deleted while paused).
FREE_MONTHLY = int(os.environ.get("JEVMOD_MONTHLY_QUOTA", "0") or 0)


class Store:
    def __init__(
        self,
        path: str | Path = "jevmod.sqlite",
        keep_text_chars: int = 300,
        retention_days: int = 30,
        monthly_quota: int | None = None,
    ) -> None:
        """keep_text_chars=0 stores no message text at all. Decisions older than retention_days are purged on
        every write and by `purge_expired()`, which the service also calls on every batch."""
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.keep_text_chars = keep_text_chars
        self.retention_days = retention_days
        self.monthly_quota = FREE_MONTHLY if monthly_quota is None else monthly_quota  # 0 = unlimited
        with self.lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY, policy TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free',
                    meta TEXT NOT NULL DEFAULT '{}', quota_notified TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS usage (
                    tenant TEXT, month TEXT, judged INTEGER, requests INTEGER, tokens INTEGER,
                    PRIMARY KEY (tenant, month));
                CREATE TABLE IF NOT EXISTS decisions (
                    ts REAL, tenant TEXT, rid TEXT, message TEXT, author TEXT, channel TEXT,
                    category TEXT, p REAL, action TEXT, scores TEXT, text TEXT);
                CREATE INDEX IF NOT EXISTS decisions_tenant_ts ON decisions (tenant, ts);
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash TEXT PRIMARY KEY, tenant TEXT NOT NULL, created REAL, label TEXT);
                """
            )
            self.db.commit()

    # ---- policy
    def get_policy(self, tenant: str) -> Policy:
        with self.lock:
            row = self.db.execute("SELECT policy FROM tenants WHERE id=?", (tenant,)).fetchone()
        return Policy.from_dict(json.loads(row[0])) if row else Policy()

    def save_policy(self, tenant: str, policy: Policy) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO tenants (id, policy) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET policy=excluded.policy",
                (tenant, json.dumps(policy.to_dict())),
            )
            self.db.commit()

    def get_meta(self, tenant: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT meta FROM tenants WHERE id=?", (tenant,)).fetchone()
        return json.loads(row[0]) if row else {}

    def set_meta(self, tenant: str, **kw: Any) -> None:
        meta = {**self.get_meta(tenant), **kw}
        with self.lock:
            self.db.execute(
                "INSERT INTO tenants (id, policy, meta) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET meta=excluded.meta",
                (tenant, json.dumps(Policy().to_dict()), json.dumps(meta)),
            )
            self.db.commit()

    def plan(self, tenant: str) -> str:
        with self.lock:
            row = self.db.execute("SELECT plan FROM tenants WHERE id=?", (tenant,)).fetchone()
        return row[0] if row else "free"

    def set_plan(self, tenant: str, plan: str) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO tenants (id, policy, plan) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET plan=excluded.plan",
                (tenant, json.dumps(Policy().to_dict()), plan),
            )
            self.db.commit()

    # ---- usage and quota
    @staticmethod
    def month() -> str:
        return time.strftime("%Y-%m")

    def add_usage(self, tenant: str, judged: int, requests: int, tokens: int) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO usage (tenant, month, judged, requests, tokens) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(tenant, month) DO UPDATE SET judged=judged+excluded.judged, "
                "requests=requests+excluded.requests, tokens=tokens+excluded.tokens",
                (tenant, self.month(), judged, requests, tokens),
            )
            self.db.commit()

    def usage(self, tenant: str) -> tuple[int, int, int]:
        with self.lock:
            row = self.db.execute(
                "SELECT judged, requests, tokens FROM usage WHERE tenant=? AND month=?", (tenant, self.month())
            ).fetchone()
        return tuple(row) if row else (0, 0, 0)

    def over_quota(self, tenant: str) -> bool:
        return self.monthly_quota > 0 and self.plan(tenant) == "free" and self.usage(tenant)[0] >= self.monthly_quota

    def note_quota_hit(self, tenant: str) -> bool:
        """True the first time this month the tenant hits the quota (so the adapter can notify the owner once)."""
        with self.lock:
            row = self.db.execute("SELECT quota_notified FROM tenants WHERE id=?", (tenant,)).fetchone()
            if row and row[0] == self.month():
                return False
            self.db.execute(
                "INSERT INTO tenants (id, policy, quota_notified) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET quota_notified=excluded.quota_notified",
                (tenant, json.dumps(Policy().to_dict()), self.month()),
            )
            self.db.commit()
            return True

    # ---- audit
    def purge_expired(self) -> int:
        cutoff = time.time() - self.retention_days * 86400
        with self.lock:
            cur = self.db.execute("DELETE FROM decisions WHERE ts < ?", (cutoff,))
            self.db.commit()
            return cur.rowcount

    def delete_user(self, tenant: str, author: str) -> int:
        """Right to erasure for one member of a community."""
        with self.lock:
            cur = self.db.execute("DELETE FROM decisions WHERE tenant=? AND author=?", (tenant, author))
            self.db.commit()
            return cur.rowcount

    def log_decision(self, tenant: str, m: Message, d: Decision, rid: str) -> None:
        self.purge_expired()
        with self.lock:
            self.db.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    tenant,
                    rid,
                    m.id,
                    m.author,
                    m.channel_topic[:80],
                    d.category,
                    d.probability,
                    d.action,
                    json.dumps({k: round(v, 3) for k, v in d.scores.items()}),
                    m.text[: self.keep_text_chars],
                ),
            )
            self.db.commit()

    def recent_decisions(self, tenant: str, n: int = 10) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT ts, message, category, p, action, scores, text FROM decisions "
                "WHERE tenant=? ORDER BY ts DESC LIMIT ?",
                (tenant, n),
            ).fetchall()
        return [
            {
                "ts": r[0],
                "message_id": r[1],
                "category": r[2],
                "p": r[3],
                "action": r[4],
                "scores": json.loads(r[5]),
                "text": r[6],
            }
            for r in rows
        ]

    def export_decisions(self, tenant: str) -> list[dict[str, Any]]:
        return self.recent_decisions(tenant, 100000)

    def delete_tenant(self, tenant: str) -> None:
        """GDPR: forget everything about a community or API tenant."""
        with self.lock:
            for table, col in (("tenants", "id"), ("usage", "tenant"), ("decisions", "tenant"), ("api_keys", "tenant")):
                self.db.execute(f"DELETE FROM {table} WHERE {col}=?", (tenant,))
            self.db.commit()

    # ---- API keys (developers)
    def create_api_key(self, tenant: str, key_hash: str, label: str = "") -> None:
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO api_keys (key_hash, tenant, created, label) VALUES (?, ?, ?, ?)",
                (key_hash, tenant, time.time(), label),
            )
            self.db.commit()

    def tenant_for_key(self, key_hash: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT tenant FROM api_keys WHERE key_hash=?", (key_hash,)).fetchone()
        return row[0] if row else None
