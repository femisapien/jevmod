# jevmod: plan to production

Moderation for communities and apps, powered by Jev. One judgment core; many ways in. Open source with a hosted
version (Supabase model). Price ceiling for a community: 5 $/month.

Three users, three surfaces:

| user | surface | how they start |
|---|---|---|
| Community owner, not technical | Discord bot, Telegram bot, Reddit app | one invite link, works in flag-only mode, tune with commands |
| Developer with user content | `pip install jevmod`, HTTP API (`POST /v1/moderate`), webhooks | one function call or one HTTP request with an API key |
| Team that must self-host | Docker image, docker-compose, AWS CDK stack | `docker compose up`, or `cdk deploy` |

Rule of the plan: **a phase is done when its checklist is green and a fresh red team cannot reproduce the previous
phase's findings.** Each phase ends with something a stranger can run.

---

## Phase 0. Core and Discord (done 2026-09-17)

- `Judge`: batch of messages, one Jev request, five categories plus custom rules, pre-filters, cache.
- Discord bot with flag-only default, `/mod` commands, private log channel, ❌ feedback.
- Measured: 0.0012 cents per judged message.

## Phase 1. Architecture for the three users (this session)

- [ ] `jevmod.core`: `Judge` (unchanged), `Policy` (thresholds, actions, rules → `Decision`), `ModerationService`
      (tenant config + quota + audit in one call), `Batcher` (2 s window, per tenant, async).
- [ ] Public Python API: `from jevmod import Moderator; Moderator().check(text)` and `.check_many([...])`.
- [ ] HTTP API (FastAPI): `POST /v1/moderate`, `GET /v1/health`, API keys per tenant, usage counters, OpenAPI docs.
- [ ] Adapters sharing the core: Discord (moved), Telegram (`python-telegram-bot`), Reddit (`praw`, official API),
      generic webhook (any chatbot posts a message, gets a decision).
- [ ] One config surface: environment variables + optional `jevmod.yaml`; secrets never in files.
- [ ] Docker image and `docker-compose.yml` (bot + API), health checks.
- [ ] AWS CDK stack (Python): Fargate service, secrets in Secrets Manager, logs in CloudWatch. Marked optional.
- [ ] Tests: offline for `Policy` and store; real Jev for `Judge`; the red team's adversarial CSV as a regression set
      with a floor on precision/recall per category; CI on GitHub Actions.
- [ ] Observability: structured JSON logs, request ids, per-tenant counters, `/metrics` (Prometheus text).
- [ ] Failure policy written and tested: Jev down → fail open + log; quota exceeded → skip + notify owner once.

## Phase 2. Judgment quality

- [ ] Fix every red-team finding on the judge: evasions (leetspeak, homoglyphs, split links), multilingual, injection
      attempts, false positives on gaming slang, quoted spam, legitimate links, mental-health messages.
- [ ] Per-community calibration: ❌ feedback moves thresholds; `/mod recent` shows drift; export decisions as CSV.
- [ ] Context: judge with the previous 2 messages of the channel when the text alone is ambiguous (sarcasm, replies).
- [ ] Evaluation harness with a labeled set per language; publish precision/recall in the README, honestly.

## Phase 3. Hosted version

- [ ] Multi-tenant: one process serves many communities and API tenants; tenant = Discord guild, Telegram chat,
      subreddit or API key.
- [ ] Billing: Discord native subscriptions for communities, Stripe for API tenants. Free 5,000 judged messages
      per month; 5 $/month unlimited per community; API priced per 1,000 judgments with a cap.
- [ ] Onboarding page for non-technical owners: three buttons (Discord, Telegram, Reddit), what data goes where,
      one paragraph of privacy in plain words.
- [ ] Postgres instead of SQLite when hosted; nightly export; deletion on request (GDPR).
- [ ] Status page and an alert to the operator when Jev error rate rises.

## Phase 4. Distribution

- [ ] Listings: top.gg and discordbotlist; Telegram bot directories; Reddit Developer Platform app.
- [ ] PyPI package and docs site (`docs/`), SKILL.md and AGENTS.md so coding agents can integrate it.
- [ ] Launch post with the measured numbers and the evaluation table, signed by Omar.

---

## Production readiness checklist (applies to every phase)

- Secrets only from environment or a secrets manager; `.env.example` documents them; nothing secret in git.
- Every external call has a timeout and a defined failure behaviour; nothing retries unboundedly.
- Every decision is logged with its probabilities, the policy version and a request id; decisions are explainable
  after the fact.
- Quotas and rate limits per tenant; no tenant can spend another tenant's budget.
- Privacy: what is sent to TypeSafe is listed in one place; message text is never persisted by default; the log
  keeps 300 characters unless the owner opts for full text.
- Tests run without a key (offline) and with one (real); CI blocks on lint, types and tests.
- One command to run locally, one to run in Docker, one to deploy.

## Decisions

- 2026-09-17: name `jevmod`, MIT, repo private until Phase 1 is green and the judgment red team is clean.
- 2026-09-17: flag-only by default; deletion and timeouts are opt-in per category.
- 2026-09-17: batching per tenant with a 2 s window; the judgment core stays synchronous, adapters are async.
