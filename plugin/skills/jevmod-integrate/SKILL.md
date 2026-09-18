---
name: jevmod-integrate
description: Use when a codebase needs content moderation added (user messages, comments, chat, form input, agent tool inputs or outputs) with jevmod, the open-source moderation layer powered by Jev (TypeSafe). Covers picking the surface (Python SDK, npm, HTTP API, MCP), storing the TypeSafe key safely, wiring the call at the right place, and adding a real test. Not for screening text ad hoc while working; that is jevmod-moderate.
---

# jevmod-integrate

Add moderation to an existing codebase in one pass. Every message gets a probability per category
(`spam`, `scam`, `harassment`, `nsfw`, `offtopic`, `selfharm`, `doxxing`, `minors`) plus one per
rule written in plain language; a policy turns probabilities into an action (`none`, `flag`,
`delete`, `timeout`). Flag-only by default. One Jev request per batch, about $0.000045 per message.

If the jevmod repository is available locally, `AGENTS.md` at its root is the authoritative short
reference. This skill is self-contained when it is not.

## Procedure

### 1. Detect the stack and pick the surface

| stack | surface | install |
|---|---|---|
| Python 3.10+ (FastAPI, Django, Flask, bots, agents) | Python SDK: `from jevmod import Moderator, Policy` | `pip install jevmod` |
| Node / TypeScript | npm package `jevmod` (`check`, `checkMany`, HTTP client). Confirm it is published (`npm view jevmod version`) before relying on it; if not, use HTTP | `npm install jevmod` |
| anything else, or a service shared by several apps | HTTP API: `jevmod api` (or the Docker image) and `POST /v1/moderate` | `pip install jevmod` on the host, or `docker compose up` |
| an agent that should moderate through tools | MCP: `jevmod mcp` (stdio); this plugin registers it | `pip install "jevmod[mcp]"` |

Prefer the SDK when the app is Python: no server, no database, no tenant keys. Use the HTTP API
when several services share one policy or the caller is not Python.

### 2. Put the key somewhere safe

The key is `TYPESAFE_API_KEY` (free tier at https://console.typesafe.ai/settings/keys). jevmod
reads it in this order: OS keyring, environment variable, `.env` in the working directory.

- Run `jevmod init` once. It asks for the key without echo, validates it with one small Jev call,
  stores it in the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service; needs the
  `keyring` package, included in `jevmod[all]`) and falls back to `.env` with mode 600, adding `.env`
  to `.gitignore` if a `.gitignore` exists. `jevmod init --env-file` writes `.env` on purpose.
- On servers and CI, set `TYPESAFE_API_KEY` in the environment or the secrets manager.
- Never write the key into source, config files that are committed, Dockerfiles, or tests. Never
  print it. If `.env` is used, check that `.gitignore` lists it.

If `jevmod init` is not in the installed version yet, set the environment variable and move on.

### 3. Wire it at the right place

Find the single point where user text enters the system (request validator, message handler,
tool-call boundary). Insert one call there. Do not call per character stream chunk; call once per
message, or once per batch.

Python, one message:

```python
from jevmod import Moderator, Policy

policy = Policy()  # defaults: flag at the thresholds below
policy.set_category("scam", "delete", 0.75)  # your actions, your thresholds
policy.set_rule("no_politics", "No political discussion. Game news is fine.", action="flag", threshold=0.8)
mod = Moderator(policy=policy)  # reuse this object: it caches verdicts for 24 h

d = mod.check(text, channel_topic="support chat")  # -> Decision
if d.action != "none":
    ...  # d.category ("scam" or "rule:no_politics"), d.probability, d.scores (every probability)
```

Python, a batch (one Jev request for everything that passes the pre-filter; keep batches at 50 or
fewer, the HTTP API enforces that limit and the CLI chunks at 50):

```python
decisions = mod.check_many(texts, channel_topic="support chat", ids=[...])
```

`Moderator` raises `typesafe_sdk.TypeSafeError` (after 3 retries with backoff on 429/5xx, 20 s
timeout) when Jev cannot be reached. Decide fail-open or fail-closed explicitly at the call site:

```python
try:
    d = mod.check(text)
except TypeSafeError:
    log.warning("moderation unavailable, letting the message through")
    d = None  # fail open; the HTTP API does this for you and reports reason="error_open"
```

HTTP, from any language:

```
POST /v1/moderate
Authorization: Bearer jm_...          # a tenant key minted with POST /v1/keys (admin token)
{"messages": [{"id": "a", "text": "...", "channel_topic": "gaming", "author_trusted": false}]}
```

Response: `{"request_id", "decisions": [{"message_id", "action", "category", "probability",
"scores", "judged", "reason"}], "usage": {...}}`. Up to 50 messages per request. Policy per tenant
through `GET/PUT /v1/policy`. Jev unreachable: every decision comes back `action="none"`,
`judged=false`, `reason="error_open"`, and the operator gets one warning in the log.

Where to insert, by kind of app:

| app | insert at | what to send |
|---|---|---|
| web backend with user posts/comments | the request validator (FastAPI dependency, pydantic validator, Express middleware) before the write | the text, `channel_topic` = the section or thread subject |
| chat / community bot | the message handler, before any reply or storage | the text, `channel_topic` = channel description, `author_trusted=True` for moderators |
| LLM agent | a guard on tool inputs and on the final answer | the user turn and the outgoing text; keep `offtopic` off unless you set a topic |
| data ingestion / batch | the loader, in chunks of 50 with `check_many` | one text per row |

### 4. Decision table

| category | true when | default action, threshold |
|---|---|---|
| `spam` | mass promotion, invite farming, bare link drops, mass mentions | flag 0.85 |
| `scam` | fake giveaways, phishing domains, impersonated support, "DM me" deals | flag 0.75 |
| `harassment` | insults, slurs, threats, targeted abuse, any language | flag 0.75 |
| `nsfw` | sexual or gore content for a general audience | flag 0.80 |
| `offtopic` | unrelated to `channel_topic`; meaningless without a topic | off, 0.90 |
| `selfharm` | the author is in crisis or considering self-harm | flag 0.80, flag-only by design |
| `doxxing` | reveals or hunts private data about a real person | flag 0.80 |
| `minors` | sexualises a minor or grooming behaviour | flag 0.70 |
| `rule:<name>` | your rule in plain language, exceptions included, up to 5, 200 chars each | flag 0.80 |

`decide` picks the most severe action whose threshold is crossed; ties go to the higher probability.
Thresholds clamp to 0.50..0.99. `Policy.nudge(category, +0.03)` moves a threshold after a false
positive; that is how communities calibrate.

### 5. Add a real test

No mocks. The test calls Jev and skips when the key is missing. Use the sample messages the
project's own suite uses (`tests/test_judge.py` in the jevmod repo):

```python
import os
import pytest
from jevmod import Moderator

pytestmark = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")

SAMPLES = [
    ("FREE NITRO for the first 100 people!! claim at discord-gifts.ru/nitro", "scam"),
    ("Anyone know if the new patch fixed the inventory bug? Mine still duplicates items.", None),
    ("you're a worthless idiot and everyone here hates you, just leave", "harassment"),
    ("I don't want to be here anymore. nobody would notice if I was gone. sorry everyone", "selfharm"),
    ("my daughter is 12 and loves this game, any tips on parental controls?", None),
]


def test_moderation_is_wired():
    mod = Moderator()
    decisions = mod.check_many([t for t, _ in SAMPLES], channel_topic="gaming community general chat")
    for (text, expected), d in zip(SAMPLES, decisions):
        assert d.judged, (text, d.reason)
        if expected is None:
            assert d.action == "none", (text, d.scores)
        else:
            assert d.category == expected and d.probability >= 0.7, (text, d.scores)
```

Then exercise your own entry point (the endpoint, the handler, the tool guard) with the scam
sample and the clean sample and assert what your code does with `flag` and `none`.

### 6. Verify from the shell

```
jevmod check "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"   # exit 1, scam ~0.97
jevmod check "gg everyone, that raid was clean. same time tomorrow?"             # exit 0
```

## Gotchas (learned from the red team, tests/data/redteam.csv)

- Probabilities move about plus or minus 0.03 between runs. Never assert an exact value; assert
  above or below a threshold with margin, and keep production thresholds at least 0.05 away from
  where your traffic clusters.
- `selfharm` is flag-only on purpose: alert a human, never delete or time out. Do not map it to a
  punitive action.
- `offtopic` is off by default and only means something with `channel_topic`. Turning it on without
  a topic judges against "general chat".
- Messages under 8 letters or digits without a link are never sent (`judged=False`,
  `reason="too short"`); trusted authors are never sent (`reason="trusted author"`). Do not treat
  `judged=False` as clean; treat it as "not judged".
- Only the text and `channel_topic` reach TypeSafe. Never add author names, ids or emails to the
  text you send.
- Batches go to Jev as a dict keyed by position, not a list; with a list, probabilities leaked
  between neighbours in multilingual batches. If you build your own Jev state instead of using
  jevmod, keep it a dict.
- Text is NFKC-normalised, combining marks and zero-width characters removed, HTML entities
  decoded, before judging and caching. Do not pre-clean it yourself; send the raw message.
- Custom rules: at most 5, 200 characters each; write the exception into the rule ("No politics.
  Game news is fine."). Borderline politics is where the suite still misses (2 of 14).
- `Moderator` is stateless apart from the cache: no SQLite, no quota, no audit log. If you need
  per-tenant policy, usage counters and an audit trail, run `jevmod api` and call it over HTTP.
- Do not commit the key. Do not log `Decision` objects with the message text in production
  unless the operator asked for it; the HTTP API keeps 300 characters for 30 days.

## MCP tools (when `jevmod mcp` is registered)

- `moderate(texts: list[str], channel_topic: str = "", rules: dict[str, str] | None = None)` returns one
  decision per text (up to 50) with every probability; actions here are only `none` or `flag`.
- `categories()` returns the category names, their criteria and the default thresholds.

Use them to try a policy on sample messages before writing code; the wiring in the codebase should
still use the SDK or HTTP, not the MCP server.
