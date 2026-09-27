"""HTTP API for developers and for any chatbot: POST a batch of messages, get decisions.

    JEVMOD_KEYMINT_TOKEN=... TYPESAFE_API_KEY=... uvicorn jevmod.api.server:app --port 8080

Auth: `Authorization: Bearer <api key>`. Keys are minted with JEVMOD_KEYMINT_TOKEN (`POST /v1/keys`) and stored
hashed. That token does one job: minting keys. It used to be JEVMOD_ADMIN_TOKEN, which also authenticated the
operator's panel and signed every billing link, so a leak of it handed over all three at once.
Every response carries the request id; every judged decision is in the tenant's audit log.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import time
import uuid
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ..core import ModerationService, Store
from ..core.surrogates import contains_lone_surrogate
from ..judge import CATEGORIES, Message

app = FastAPI(
    title="jevmod",
    version="0.2.0",
    description="Moderation decisions for user content: spam, scam, harassment, adult, off-topic and your own rules. "
    "Powered by Jev (TypeSafe). Probabilities, thresholds you own, decisions you can audit.",
)
store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
service = ModerationService(store)
STARTED = time.time()
_metrics = {"requests": 0, "messages": 0, "errors": 0}


# ------------------------------------------------------------------ validation errors
class AsciiJSONResponse(JSONResponse):
    """JSON with every non-ASCII character escaped, which is still valid JSON and cannot fail to encode."""

    def render(self, content: Any) -> bytes:
        return json.dumps(_finite(content), ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def _finite(value: Any) -> Any:
    """NaN and the infinities as strings. `json.loads` accepts them in a request, the 422 echoes them back, and
    strict JSON has no way to write them: `allow_nan=False` raised and the 422 became a 500 (red-team, JEV-83)."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


async def validation_error(request: Request, exc: Exception) -> Response:
    """FastAPI's own 422, rendered so that it can always be sent (JEV-83).

    The default handler echoes each failing field's `input` back and encodes the body as UTF-8. When the
    input is the lone surrogate that made it fail, that encode raises, and the caller gets a bare 500 in
    place of the error that names its field. Same status, same `{"detail": [...]}` shape, ASCII-escaped.
    Public so that an app mounting these routes on another FastAPI app installs it there too: exception
    handlers belong to the app, not to the route."""
    assert isinstance(exc, RequestValidationError)
    return AsciiJSONResponse({"detail": jsonable_encoder(exc.errors())}, status_code=422)


app.add_exception_handler(RequestValidationError, validation_error)


def _utf8(s: str) -> str:
    # 422 before anything is judged, rather than a UnicodeEncodeError after: `id` and `author` are first
    # written to SQLite once Jev has answered, so a request carrying one used to be paid for and then
    # answered 502 (JEV-83). Rejected rather than replaced because the caller can be told, and an `id`
    # quietly rewritten would come back as a decision for a message the caller never sent.
    if contains_lone_surrogate(s):
        raise ValueError(
            "contains a lone UTF-16 surrogate (U+D800 to U+DFFF), which is not text and cannot be stored; "
            "send the whole surrogate pair or drop the character"
        )
    return s


# Every string a request can carry. `text` also has a length limit, and pydantic refuses a surrogate there
# on its own (`string_unicode`); the validator is what covers the fields with no constraint, where pydantic
# passes the string through untouched.
Utf8 = Annotated[str, AfterValidator(_utf8)]


# ------------------------------------------------------------------ models
class InMessage(BaseModel):
    id: Utf8 = Field(default="", description="your id for the message; echoed back")
    text: Utf8 = Field(..., max_length=8000)
    author: Utf8 = ""
    channel_topic: Utf8 = Field(default="", description="what the channel/thread is about; used by offtopic")
    author_trusted: bool = Field(default=False, description="true skips judgment (moderators, verified staff)")


class ModerateRequest(BaseModel):
    messages: list[InMessage] = Field(..., min_length=1, max_length=50)


class DecisionOut(BaseModel):
    message_id: str
    action: str
    category: str | None
    probability: float
    scores: dict[str, float]
    judged: bool
    reason: str


class ModerateResponse(BaseModel):
    request_id: str
    decisions: list[DecisionOut]
    usage: dict[str, int]


class PolicyIn(BaseModel):
    # `extra="forbid"` because this model used to have no `rule_thresholds` field: a PUT carrying one returned
    # 200 with a policy object that quietly did not contain it. On a write path, silence is the worst answer.
    model_config = ConfigDict(extra="forbid")

    # Keys as well as values: a rule name is stored, echoed back and put in every request to Jev. A policy
    # saved with a surrogate in it used to answer 500 to the PUT that saved it and 502 to every
    # `/v1/moderate` after, because the rules are part of every cache key (JEV-83).
    thresholds: dict[Utf8, float] | None = None
    actions: dict[Utf8, Utf8] | None = None
    rules: dict[Utf8, Utf8] | None = None
    rule_actions: dict[Utf8, Utf8] | None = None
    rule_thresholds: dict[Utf8, float] | None = None
    timeout_minutes: int | None = None


class KeyRequest(BaseModel):
    tenant: Utf8 = Field(..., min_length=1, max_length=80)
    label: Utf8 = ""


# ------------------------------------------------------------------ auth
def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def tenant_from_auth(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    tenant = store.tenant_for_key(_hash(authorization[7:].strip()))
    if not tenant:
        raise HTTPException(401, "unknown api key")
    return tenant


def keymint_only(authorization: str = Header(default="")) -> None:
    """Minting a key for a tenant is the one thing this token does. Header only: a credential in a query
    string ends up in the proxy log and the browser history."""
    want = os.environ.get("JEVMOD_KEYMINT_TOKEN", "")
    given = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not want or not hmac.compare_digest(given, want):
        raise HTTPException(403, "key-minting token required")


# ------------------------------------------------------------------ routes
@app.get("/v1/health")
def health() -> dict[str, Any]:
    return {"ok": True, "uptime_s": int(time.time() - STARTED), "categories": list(CATEGORIES)}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    j = service.judge if service._judge else None
    lines = [
        f"jevmod_http_requests_total {_metrics['requests']}",
        f"jevmod_messages_total {_metrics['messages']}",
        f"jevmod_http_errors_total {_metrics['errors']}",
        f"jevmod_jev_requests_total {j.requests if j else 0}",
        f"jevmod_jev_input_tokens_total {j.input_tokens if j else 0}",
    ]
    return "\n".join(lines) + "\n"


@app.post("/v1/moderate", response_model=ModerateResponse)
def moderate(
    req: ModerateRequest, request: Request, response: Response, tenant: str = Depends(tenant_from_auth)
) -> ModerateResponse:
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    response.headers["X-Request-Id"] = rid
    _metrics["requests"] += 1
    _metrics["messages"] += len(req.messages)
    msgs = [
        Message(m.id or str(i), m.text, author=m.author, channel_topic=m.channel_topic, author_trusted=m.author_trusted)
        for i, m in enumerate(req.messages)
    ]
    try:
        decisions = service.moderate(tenant, msgs, request_id=rid)
    except Exception as exc:
        _metrics["errors"] += 1
        raise HTTPException(502, f"judgment failed: {type(exc).__name__}") from exc
    judged, requests, tokens = store.usage(tenant)
    return ModerateResponse(
        request_id=rid,
        decisions=[DecisionOut(**{k: v for k, v in d.to_dict().items() if k != "policy_version"}) for d in decisions],
        usage={"judged_this_month": judged, "jev_requests_this_month": requests, "input_tokens_this_month": tokens},
    )


@app.get("/v1/policy")
def get_policy(tenant: str = Depends(tenant_from_auth)) -> dict[str, Any]:
    return service.policy(tenant).to_dict()


@app.put("/v1/policy")
def put_policy(body: PolicyIn, tenant: str = Depends(tenant_from_auth)) -> dict[str, Any]:
    p = service.policy(tenant)
    try:
        for c, a in (body.actions or {}).items():
            p.set_category(c, a, (body.thresholds or {}).get(c))
        for c, t in (body.thresholds or {}).items():
            if c in CATEGORIES and c not in (body.actions or {}):
                p.set_category(c, p.actions.get(c, "flag"), t)
        for n, text in (body.rules or {}).items():
            p.set_rule(
                n,
                text,
                (body.rule_actions or {}).get(n, p.rule_actions.get(n, "flag")),
                (body.rule_thresholds or {}).get(n),
            )
        # a threshold for a rule whose text is not being changed in the same request
        for n, t in (body.rule_thresholds or {}).items():
            if n in p.rules and n not in (body.rules or {}):
                p.set_rule(n, p.rules[n], p.rule_actions.get(n, "flag"), t)
        if body.timeout_minutes is not None:
            p.timeout_minutes = max(1, min(int(body.timeout_minutes), 1440))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    service.save_policy(tenant, p)
    return p.to_dict()


@app.get("/v1/decisions")
def decisions(limit: int = 50, tenant: str = Depends(tenant_from_auth)) -> list[dict[str, Any]]:
    return store.recent_decisions(tenant, max(1, min(limit, 500)))


@app.delete("/v1/tenant")
def delete_tenant(tenant: str = Depends(tenant_from_auth)) -> dict[str, bool]:
    """GDPR: forget this tenant's policy, usage and decision log.

    `leave_tenant` rather than `delete_tenant`, because this call deletes the subscription row too and the
    card would otherwise keep being charged for a tenant that no longer exists. It reads the subscription id
    first and queues it after, and a deployment with nobody draining that queue - a self-hosted copy, which
    has no Stripe at all - is left with one harmless row.

    This is the same hole `on_guild_remove` had. The difference here is that nobody is present to read a
    warning: `/mod forget` is typed by a person who can be told to cancel, and an API call is not."""
    store.leave_tenant(tenant)
    # The conversation window lives in memory, not in the store, so deleting rows does not reach it.
    # An erasure that leaves the last ten messages of every channel sitting in a deque has not done
    # what it told the caller it did.
    service.forget_context(tenant)
    return {"deleted": True}


@app.post("/v1/keys", dependencies=[Depends(keymint_only)])
def create_key(body: KeyRequest) -> dict[str, str]:
    key = "jm_" + secrets.token_urlsafe(32)
    store.create_api_key(body.tenant, _hash(key), body.label)
    return {"tenant": body.tenant, "api_key": key, "note": "shown once; stored hashed"}
