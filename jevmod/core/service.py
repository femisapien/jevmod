"""ModerationService: one entry point for every adapter and for the HTTP API.

    svc = ModerationService(store)
    decisions = svc.moderate(tenant_id, messages)   # applies policy, quota, audit log, fail-open

Tenant = a Discord guild, a Telegram chat, a subreddit or an API key. The service never knows which.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

from typesafe_sdk import TypeSafeError

from ..judge import Judge, Message
from .policy import Decision, Policy, decide
from .store import Store

log = logging.getLogger("jevmod")

JEV_USD_PER_M_INPUT = 0.042
# The most one check-then-spend window may commit. A quota is checked before a batch and written
# after it, so a batch bigger than this is a ceiling overshot by exactly that much.
MAX_BATCH = int(os.environ.get("JEVMOD_MAX_BATCH", "100") or 100)


class ModerationService:
    def __init__(self, store: Store, judge: Judge | None = None, fail_open: bool = True) -> None:
        self.store = store
        self._judge = judge
        self.fail_open = fail_open

    @property
    def judge(self) -> Judge:
        if self._judge is None:
            self._judge = Judge()
        return self._judge

    def policy(self, tenant: str) -> Policy:
        return self.store.get_policy(tenant)

    def save_policy(self, tenant: str, policy: Policy) -> None:
        self.store.save_policy(tenant, policy)

    def moderate(self, tenant: str, messages: list[Message], request_id: str | None = None) -> list[Decision]:
        rid = request_id or uuid.uuid4().hex[:12]
        policy = self.policy(tenant)
        if not policy.active():
            return [Decision(m.id, "none", None, 0.0, {}, False, "policy inactive") for m in messages]
        self.store.purge_expired()
        if self.store.over_quota(tenant):
            # note_quota_hit is a once-a-month latch, and the adapters use it to decide whether to post the
            # notice. Consuming it here meant the adapter always got False, so the notice never reached anyone.
            return [Decision(m.id, "none", None, 0.0, {}, False, "quota") for m in messages]
        # The tenant is inside its own quota. The question the per-tenant quota cannot answer is whether the
        # service as a whole can still afford to judge: fifty servers each inside their own ceiling still add
        # up to more than one person budgeted for, and that is the success case rather than an attack.
        hit = self.store.over_budget(tenant)
        if hit:
            log.warning({"event": "budget", "tenant": tenant, "rid": rid, "ceiling": hit})
            return [Decision(m.id, "none", None, 0.0, {}, False, hit) for m in messages]
        # A batch is checked once and then spent whole, so its size is the amount any ceiling can be
        # overshot by. Two seconds of a raid is otherwise one batch of whatever arrived.
        if len(messages) > MAX_BATCH:
            head, tail = messages[:MAX_BATCH], messages[MAX_BATCH:]
            return self.moderate(tenant, head, rid) + [
                Decision(m.id, "none", None, 0.0, {}, False, "over_batch") for m in tail
            ]
        j = self.judge
        before = (j.requests, j.input_tokens, j.judged_messages)
        t0 = time.perf_counter()
        try:
            verdicts = j.judge(messages, policy.enabled_categories(), policy.rules)
        except TypeSafeError as exc:
            log.warning(
                {"event": "judge_error", "tenant": tenant, "rid": rid, "error": f"{type(exc).__name__}: {exc}"[:200]}
            )
            if not self.fail_open:
                raise
            return [Decision(m.id, "none", None, 0.0, {}, False, "error_open") for m in messages]
        ms = int((time.perf_counter() - t0) * 1000)
        judged = j.judged_messages - before[2]
        reqs = j.requests - before[0]
        toks = j.input_tokens - before[1]
        self.store.add_usage(tenant, judged, reqs, toks)
        decisions = [decide(policy, v) for v in verdicts]
        for m, d in zip(messages, decisions, strict=True):
            if d.action != "none":
                self.store.log_decision(tenant, m, d, rid)
        log.info(
            {
                "event": "moderate",
                "tenant": tenant,
                "rid": rid,
                "messages": len(messages),
                "judged": judged,
                "requests": reqs,
                "input_tokens": toks,
                "usd": round(toks * JEV_USD_PER_M_INPUT / 1e6, 6),
                "ms": ms,
                "actions": {a: sum(1 for d in decisions if d.action == a) for a in ("flag", "delete", "timeout")},
            }
        )
        return decisions


class Batcher:
    """Collects messages per tenant for `window_s`, then hands the batch to `handler` (async). One Jev request per
    tenant per window instead of one per message."""

    def __init__(self, window_s: float, handler: Callable[[str, list[Any]], Any]) -> None:
        self.window = window_s
        self.handler = handler
        self.pending: dict[str, list[Any]] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    def add(self, tenant: str, item: Any) -> None:
        self.pending.setdefault(tenant, []).append(item)
        t = self.tasks.get(tenant)
        if t is None or t.done():
            self.tasks[tenant] = asyncio.create_task(self._flush(tenant))

    async def _flush(self, tenant: str) -> None:
        await asyncio.sleep(self.window)
        batch = self.pending.pop(tenant, [])
        if batch:
            try:
                await self.handler(tenant, batch)
            except Exception as exc:  # an adapter bug must not stop future batches
                log.exception({"event": "batch_handler_error", "tenant": tenant, "error": str(exc)[:200]})
