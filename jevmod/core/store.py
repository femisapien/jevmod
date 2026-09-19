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
# Hosted plans: judged messages per tenant per month. 0 = unlimited. Plan names: "free", "pro", "unlimited" (comped).
PLAN_QUOTAS: dict[str, int] = {
    "free": FREE_MONTHLY,
    "pro": int(os.environ.get("JEVMOD_PRO_MONTHLY_QUOTA", "50000") or 0),
    "unlimited": 0,
}


class Store:
    def __init__(
        self,
        path: str | Path = "jevmod.sqlite",
        keep_text_chars: int | None = None,
        retention_days: int = 30,
        monthly_quota: int | None = None,
    ) -> None:
        """keep_text_chars=0 stores no message text at all. Decisions older than retention_days are purged on
        every write and by `purge_expired()`, which the service also calls on every batch."""
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.keep_text_chars = (
            int(os.environ.get("JEVMOD_KEEP_TEXT_CHARS", "300")) if keep_text_chars is None else keep_text_chars
        )
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
                CREATE TABLE IF NOT EXISTS subscriptions (
                    tenant TEXT PRIMARY KEY, customer_id TEXT, subscription_id TEXT, price_id TEXT, status TEXT,
                    current_period_end REAL, updated REAL);
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

    def quota_for(self, tenant: str) -> int:
        """Judged messages allowed this month for the tenant's plan; 0 means unlimited."""
        plan = self.plan(tenant)
        if plan == "free":
            return self.monthly_quota
        return PLAN_QUOTAS.get(plan, 0)

    def over_quota(self, tenant: str) -> bool:
        q = self.quota_for(tenant)
        return q > 0 and self.usage(tenant)[0] >= q

    # ---- hosted billing
    def set_subscription(
        self,
        tenant: str,
        *,
        customer_id: str | None,
        subscription_id: str | None,
        price_id: str | None,
        status: str,
        current_period_end: float | None,
    ) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO subscriptions (tenant, customer_id, subscription_id, price_id, status, "
                "current_period_end, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(tenant) DO UPDATE SET customer_id=excluded.customer_id, "
                "subscription_id=excluded.subscription_id, price_id=excluded.price_id, status=excluded.status, "
                "current_period_end=excluded.current_period_end, updated=excluded.updated",
                (tenant, customer_id, subscription_id, price_id, status, current_period_end, time.time()),
            )
            self.db.commit()

    def subscription(self, tenant: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute(
                "SELECT customer_id, subscription_id, price_id, status, current_period_end, updated FROM subscriptions "
                "WHERE tenant=?",
                (tenant,),
            ).fetchone()
        if not row:
            return None
        keys = ("customer_id", "subscription_id", "price_id", "status", "current_period_end", "updated")
        return dict(zip(keys, row, strict=True))

    def tenant_for_subscription(self, subscription_id: str) -> str | None:
        with self.lock:
            row = self.db.execute(
                "SELECT tenant FROM subscriptions WHERE subscription_id=?", (subscription_id,)
            ).fetchone()
        return row[0] if row else None

    def tenants_overview(self) -> list[dict[str, Any]]:
        """Every tenant with plan, this month's usage and subscription status, for the admin panel."""
        m = self.month()
        with self.lock:
            rows = self.db.execute(
                "WITH ids AS (SELECT id FROM tenants UNION SELECT tenant FROM usage WHERE month = ?) "
                "SELECT ids.id, COALESCE(t.plan, 'free'), COALESCE(u.judged, 0), COALESCE(u.requests, 0), "
                "COALESCE(u.tokens, 0), s.status, s.current_period_end, s.customer_id FROM ids "
                "LEFT JOIN tenants t ON t.id = ids.id "
                "LEFT JOIN usage u ON u.tenant = ids.id AND u.month = ? "
                "LEFT JOIN subscriptions s ON s.tenant = ids.id ORDER BY COALESCE(u.judged, 0) DESC",
                (m, m),
            ).fetchall()
        out = []
        for r in rows:
            plan = r[1]
            quota = self.monthly_quota if plan == "free" else PLAN_QUOTAS.get(plan, 0)
            out.append(
                {
                    "tenant": r[0],
                    "plan": plan,
                    "judged": r[2],
                    "requests": r[3],
                    "tokens": r[4],
                    "quota": quota,
                    "subscription_status": r[5],
                    "current_period_end": r[6],
                    "customer_id": r[7],
                }
            )
        return out

    def totals(self) -> dict[str, Any]:
        m = self.month()
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(judged), 0), COALESCE(SUM(tokens), 0) FROM usage WHERE month=?", (m,)
            ).fetchone()
            plans = self.db.execute("SELECT plan, COUNT(*) FROM tenants GROUP BY plan").fetchall()
        return {"month": m, "active_tenants": row[0], "judged": row[1], "tokens": row[2], "plans": dict(plans)}

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
                # author and channel are stored and were never read back, which left /mod recent printing a
                # bare message id that a moderator cannot click, search or act on.
                "SELECT ts, message, category, p, action, scores, text, author, channel FROM decisions "
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
                "author": r[7],
                "channel": r[8],
            }
            for r in rows
        ]

    def export_decisions(self, tenant: str) -> list[dict[str, Any]]:
        return self.recent_decisions(tenant, 100000)

    def delete_tenant(self, tenant: str) -> None:
        """GDPR: forget everything about a community or API tenant."""
        with self.lock:
            for table, col in (
                ("tenants", "id"),
                ("usage", "tenant"),
                ("decisions", "tenant"),
                ("api_keys", "tenant"),
                ("subscriptions", "tenant"),
            ):
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
