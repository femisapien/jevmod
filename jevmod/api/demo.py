"""Public demo endpoint for the landing page: one message in, one decision out, with the TypeSafe key kept on the
server and a hard monthly budget so a stranger cannot spend more than you allow.

    JEVMOD_DEMO_BUDGET_USD=0.5 JEVMOD_DEMO_ORIGINS=https://ohernandezdev.github.io jevmod demo

Guards, in order: CORS allow-list → per-IP limits (per minute and per day) → text length → global monthly budget
computed from measured input tokens at Jev's list price → cache (repeats cost nothing). Every judged demo message
is logged (text, scores, hashed IP, country header if a proxy sets one) so you can see what people try:
`GET /demo/stats` and `GET /demo/recent` need the admin token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..core import Policy, decide
from ..judge import CATEGORIES, Judge, Message, normalize

JEV_USD_PER_M = 0.042
BUDGET_USD = float(os.environ.get("JEVMOD_DEMO_BUDGET_USD", "0.5"))
PER_MINUTE = int(os.environ.get("JEVMOD_DEMO_PER_MINUTE", "6"))
PER_DAY = int(os.environ.get("JEVMOD_DEMO_PER_DAY", "40"))
MAX_CHARS = int(os.environ.get("JEVMOD_DEMO_MAX_CHARS", "300"))
ORIGINS = [o.strip() for o in os.environ.get("JEVMOD_DEMO_ORIGINS", "http://localhost:8000").split(",") if o.strip()]
DB_PATH = os.environ.get("JEVMOD_DEMO_DB", "jevmod-demo.sqlite")
SALT = os.environ.get("JEVMOD_DEMO_SALT", "jevmod-demo")
DEMO_RETENTION_DAYS = int(
    os.environ.get("JEVMOD_DEMO_RETENTION_DAYS", "90")
)  # demo log rows older than this are purged
CATS = [c for c in CATEGORIES if c != "offtopic"]

app = FastAPI(title="jevmod demo", version="0.1.0", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["POST", "GET"], allow_headers=["Content-Type"])

_judge: Judge | None = None
_policy = Policy()
for _c in CATS:
    _policy.set_category(_c, "flag")
_lock = threading.Lock()
_minute: dict[str, deque[float]] = defaultdict(deque)
_day: dict[str, deque[float]] = defaultdict(deque)
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS demo (ts REAL, month TEXT, ip_hash TEXT, country TEXT, text TEXT, category TEXT,
        p REAL, action TEXT, scores TEXT, tokens INTEGER, cached INTEGER);
    CREATE INDEX IF NOT EXISTS demo_month ON demo (month);
    """
)
_db.commit()


class In(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHARS)


def judge() -> Judge:
    global _judge
    if _judge is None:
        _judge = Judge()
    return _judge


def month() -> str:
    return time.strftime("%Y-%m")


_last_purge = 0.0


def purge_expired(force: bool = False) -> int:
    """Delete demo rows older than DEMO_RETENTION_DAYS. Spend still counts for the month.

    Every demo endpoint calls this, not only /demo/check, so the retention promise on the privacy page does not
    depend on someone submitting a message. At most one sweep an hour, because /demo/health is polled."""
    global _last_purge
    now = time.time()
    if not force and now - _last_purge < 3600:
        return 0
    _last_purge = now
    with _lock:
        cur = _db.execute("DELETE FROM demo WHERE ts < ?", (now - DEMO_RETENTION_DAYS * 86400,))
        _db.commit()
        return cur.rowcount


def spent_usd() -> float:
    row = _db.execute("SELECT COALESCE(SUM(tokens), 0) FROM demo WHERE month=? AND cached=0", (month(),)).fetchone()
    return float(row[0]) * JEV_USD_PER_M / 1e6


def _ip(request: Request) -> str:
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
    return hashlib.sha256(f"{SALT}|{ip}".encode()).hexdigest()[:16]


def _allow(ip_hash: str) -> str | None:
    now = time.time()
    with _lock:
        for bucket, window, limit in ((_minute[ip_hash], 60, PER_MINUTE), (_day[ip_hash], 86400, PER_DAY)):
            while bucket and now - bucket[0] > window:
                bucket.popleft()
            if len(bucket) >= limit:
                return "per-minute limit, try again in a moment" if window == 60 else "daily limit for this address"
        _minute[ip_hash].append(now)
        _day[ip_hash].append(now)
    return None


@app.get("/demo/health")
def health() -> dict[str, Any]:
    purge_expired()
    spent = spent_usd()
    return {"ok": True, "budget_usd": BUDGET_USD, "spent_usd": round(spent, 4), "open": spent < BUDGET_USD}


@app.post("/demo/check")
def check(body: In, request: Request) -> dict[str, Any]:
    ip_hash = _ip(request)
    purge_expired()
    why = _allow(ip_hash)
    if why:
        raise HTTPException(429, why)
    spent = spent_usd()
    if spent >= BUDGET_USD:
        raise HTTPException(
            503, f"the demo budget for this month (${BUDGET_USD:.2f}) is used up; run the CLI with your own key"
        )
    j = judge()
    before = j.input_tokens
    verdicts = j.judge([Message("demo", normalize(body.text))], CATS)
    v = verdicts[0]
    tokens = j.input_tokens - before
    d = decide(_policy, v)
    with _lock:
        _db.execute(
            "INSERT INTO demo VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                month(),
                ip_hash,
                request.headers.get("cf-ipcountry", ""),
                body.text[:MAX_CHARS],
                d.category,
                d.probability,
                d.action,
                json.dumps({k: round(x, 3) for k, x in d.scores.items()}),
                tokens,
                int(v.reason == "cache"),
            ),
        )
        _db.commit()
    out = d.to_dict()
    out["reason"] = v.reason
    out["budget_left_usd"] = round(max(BUDGET_USD - spent - tokens * JEV_USD_PER_M / 1e6, 0), 4)
    return out


def _admin(authorization: str) -> None:
    admin = os.environ.get("JEVMOD_ADMIN_TOKEN", "")
    given = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not admin or not hmac.compare_digest(given, admin):
        raise HTTPException(403, "admin token required")


@app.get("/demo/stats")
def stats(authorization: str = Header(default="")) -> dict[str, Any]:
    _admin(authorization)
    purge_expired()
    m = month()
    rows = _db.execute(
        "SELECT COUNT(*), COUNT(DISTINCT ip_hash), SUM(cached), COALESCE(SUM(tokens),0) FROM demo WHERE month=?", (m,)
    ).fetchone()
    by_cat = _db.execute(
        "SELECT COALESCE(category,'none'), COUNT(*) FROM demo WHERE month=? GROUP BY 1 ORDER BY 2 DESC", (m,)
    ).fetchall()
    by_country = _db.execute(
        "SELECT country, COUNT(*) FROM demo WHERE month=? AND country!='' GROUP BY 1 ORDER BY 2 DESC LIMIT 15", (m,)
    ).fetchall()
    return {
        "month": m,
        "checks": rows[0],
        "distinct_visitors": rows[1],
        "cache_hits": rows[2] or 0,
        "input_tokens": rows[3],
        "spent_usd": round(rows[3] * JEV_USD_PER_M / 1e6, 4),
        "budget_usd": BUDGET_USD,
        "by_category": dict(by_cat),
        "by_country": dict(by_country),
    }


@app.get("/demo/recent")
def recent(limit: int = 100, authorization: str = Header(default="")) -> list[dict[str, Any]]:
    _admin(authorization)
    purge_expired()
    rows = _db.execute(
        "SELECT ts, country, text, category, p, action, scores FROM demo ORDER BY ts DESC LIMIT ?",
        (max(1, min(limit, 1000)),),
    ).fetchall()
    return [
        {
            "ts": r[0],
            "country": r[1],
            "text": r[2],
            "category": r[3],
            "p": r[4],
            "action": r[5],
            "scores": json.loads(r[6]),
        }
        for r in rows
    ]
