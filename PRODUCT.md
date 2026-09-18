# jevmod: productisation checklist (2026-09-18)

Not a SaaS. An open-source moderation layer powered by Jev that humans read without smelling AI slop and that coding
agents integrate in one shot. Launch on Twitter/X and Reddit for reach. Repo stays on Omar's personal GitHub.

Owner of each line is the agent/dir in brackets. Nothing on this list may be dropped silently; if something is
blocked, it is marked blocked with the reason.

## Channels and surfaces (every one needs a working example under `examples/`)

- [x] Discord bot (exists) → `examples/discord/` [B]
- [x] HTTP API (exists) → `examples/api/` curl + Python + Node [B]
- [x] CLI `jevmod check` (exists) → `examples/cli/` incl. a shell script that screens a file and exits non-zero [B]
- [x] Python SDK `Moderator` (exists) → `examples/sdk/` [B]
- [x] MCP server `jevmod mcp` (new, FastMCP): tools `moderate`, `policy` [B]
- [x] Agent harness: guard inputs/outputs of an agent (Claude Agent SDK hook, LangChain callback, generic decorator) → `examples/agent_harness/` [B]
- [x] Input validation for any backend: FastAPI dependency + pydantic validator + Express middleware (npm) → `examples/input_validation/` [B, A]
- [x] npm package `jevmod` (TypeScript): same questions (`jevmod/categories.json`), same policy, `check`/`checkMany`, plus an HTTP client for a deployed API → `packages/jevmod-js/` [A]
- [x] Telegram, Reddit adapters (exist) → mention in README, examples optional

## Key handling (easiest and safest)

- [x] `jevmod init` stores the TypeSafe key in the OS keyring (Windows Credential Manager / macOS Keychain / Secret Service) or writes `.env` with 600 perms, never echoes it; every entry point reads keyring → env → .env [B]
- [x] npm: `JEVMOD_API_KEY`/`TYPESAFE_API_KEY` from env or constructor, never logged [A]
- [x] Docs: one paragraph, one command, keys never in git (`.gitignore` has `.env`) [E]

## Docs, diagrams, landing

- [x] Diagrams (SVG, dark, emerald): architecture (channels → core → Jev), request flow with batching/prefilter/cache, coverage matrix (category × surface), failure policy → `docs/diagrams/` [C]
- [x] GitHub Pages landing `docs/index.html`: same design language as chunkguard (dark, emerald, Geist), mini demo with precomputed results from the benchmark, three doors (community owner / developer / agent), honest numbers [C]
- [x] GIF like chunkguard: terminal demo of `jevmod check` and the API in 15 s → `docs/jevmod.gif` [C]
- [x] README rewritten for humans first, agents second; links to AGENTS.md, SKILL.md, llms.txt, BENCHMARK.md [E]
- [x] `docs/llms.txt` + `AGENTS.md` (how an agent integrates jevmod in a codebase) [D]

## Agents and marketplace

- [x] Claude Code plugin in `plugin/` with skills: `jevmod-integrate` (add moderation to a codebase: pick surface, wire key, add tests), `jevmod-moderate` (use the CLI/MCP to screen text while working) [D]
- [x] The jevmod repo is its own marketplace (`.claude-plugin/marketplace.json` → `./plugin`); Omar decided against the shared marketplace (2026-09-18) [D]
- [x] MCP server registration snippet for Claude Code / Cursor / Codex in README [D]

## Benchmark and launch

- [x] Finish Llama Guard 3 run; `BENCHMARK.md` with the four-system table, cost/latency, what each dataset is, caveats (toxic-bert trained on Civil Comments; YouTube labels loose) [E]
- [x] `launch/twitter.md` thread and `launch/reddit.md` post (r/Discord_Bots, r/selfhosted, r/Python): value, numbers, GIF, repo link [E]
- [x] LICENSE MIT + `DISCLAIMER.md` (no warranty, not affiliated with TypeSafe/Discord/Telegram/Reddit, operator responsible for actions and legal compliance) [E]
- [x] Final anti-slop review 2026-09-18: 30 findings, all applied (quota off by default, key order, honest benchmark claims, calibration measured, mobile landing, init --forget, X-Request-Id header, reddit compose, npm repository field) of README and landing by a fresh agent; fix findings [E]

## Rules for everyone

- Real tests against Jev (`TYPESAFE_API_KEY` in env), no mocks; `ruff`, `mypy` clean; Node: `tsc` strict, vitest.
- Never write a key into any file. Never touch another owner's directory. Do not commit; the coordinator commits.
- English in code and docs. Plain sentences, no marketing adjectives, no emoji walls, no "🚀". Numbers only when measured.

- [x] Public demo endpoint `jevmod demo` (budget cap, per-IP limits, CORS allow-list, visitor log with admin stats) + `deploy/demo/` (Caddy HTTPS on a VPS) 2026-09-18
- [x] Landing redesign 2026-09-18: light theme on the StudioBlank system, value-first hero, cost calculator, live try-it box (data-demo on section#demo)

## Launch gate (do these the day of the launch, in this order)

1. Done 2026-09-18: jevmod 0.2.0 on PyPI (trusted publishing) and npm (NPM_TOKEN secret); `release.yml` publishes both on every `v*` tag.
2. Done 2026-09-18: demo and landing live at jevmod.hernandezbastos.es; repo public. Remaining:  enable Pages (Settings → Pages → main, /docs); replace LINK in launch/*.md with the repo URL.
3. Launch drafts carry the real links (done). Rotate the TypeSafe key if it was ever pasted anywhere; update `gh secret set TYPESAFE_API_KEY`.
4. Post the Twitter thread with docs/jevmod.gif, then r/Discord_Bots; the other subreddits on later days.

## Notes

- The landing is served from https://jevmod.dev (nginx behind Traefik on the VPS). GitHub Pages is optional; the repo went public on 2026-09-18.
- npm package not published to the registry yet (`npm publish` from packages/jevmod-js at launch); PyPI likewise (`python -m build && twine upload`).

## Hosted plan (built 2026-09-18 while Omar was out; decisions to confirm)

- Pricing chosen provisionally: Free 5,000 judged messages per server per month; **Pro $3.99/month per server up to
  50,000** (`JEVMOD_PRO_MONTHLY_QUOTA`). Worst-case Jev cost of a Pro server: 50,000 × 1,005 tokens × $0.042/M ≈ $2.11,
  so the margin is positive even at full use. Change the price in Stripe and `JEVMOD_PRO_MONTHLY_QUOTA` in the VPS `.env`.
- Flow: `/mod upgrade` → signed Checkout link (`/billing/checkout?tenant=&sig=`) → Stripe → webhook → plan `pro`;
  cancel → `free`. Portal for existing subscribers via the same command. Admin panel `/admin?token=...`.
- Needed from Omar (VPS `.env`, then `docker compose ... up -d`): `STRIPE_PRICE_ID`, `STRIPE_SECRET_KEY`,
  `STRIPE_WEBHOOK_SECRET` (endpoint `https://jevmod.dev/billing/stripe/webhook`, events checkout.session.completed,
  customer.subscription.updated, customer.subscription.deleted), `DISCORD_TOKEN` (Message Content Intent), and the
  Discord application id for the invite link (permissions integer includes View Channels, Send Messages, Manage Messages, Embed Links, Add Reactions, Manage Channels, Moderate Members and Read Message History, which the ❌/✅ handler needs) (`data-invite` on `#hosted` in docs/index.html:
  `https://discord.com/oauth2/authorize?client_id=1550544449199800410&scope=bot%20applications.commands&permissions=1099511721040`, set on `#hosted[data-invite]` 2026-09-18).
- Open: Discord verification is required above 100 servers; Stripe tax settings (VAT for EU customers) are Omar's to
  configure in the Stripe dashboard; refunds are manual.

## Blocked on Omar, verified against the live VPS on 2026-09-18

I checked `clawd@65.108.95.94` directly. Two things the site wanted to promise cannot happen yet.

**The hosted Discord bot is not running.** Only `jevmod-demo` and `jevmod-site` are up. There is no
`DISCORD_TOKEN` on the host, and the `bot` service in `deploy/demo/docker-compose.traefik.yml` sits behind
`profiles: ["bot"]`, so `docker compose up` does not start it. Until it runs, an invite link on the site adds an
application that never comes online, so the site now shows the invite as not open yet.

To turn it on: Developer Portal, Bot, Reset Token, enable the Message Content Intent, put `DISCORD_TOKEN` in the
VPS `.env`, then `docker compose -f docker-compose.traefik.yml --profile bot up -d`. Never paste the token into a
chat; set it on the host.

**Stripe is not configured.** `STRIPE_PRICE_ID`, `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are all absent
from the running container, so `_billing_enabled()` is false and `/mod upgrade` answers "This copy of jevmod is
self-hosted: there is nothing to pay." The plans table therefore says Pro is not open yet.

To open it: create the monthly product in Stripe, add the three values to the VPS `.env`, and point a webhook at
`https://jevmod.dev/billing/stripe/webhook` for `checkout.session.completed`, `customer.subscription.updated`
and `customer.subscription.deleted`. `JEVMOD_ADMIN_TOKEN` is already set, which billing links now require.

**What is correct on the host:** `JEVMOD_MONTHLY_QUOTA=5000`, `JEVMOD_PRO_MONTHLY_QUOTA=50000`,
`JEVMOD_PUBLIC_URL=https://jevmod.dev`, role `hosted`.

**The live site is an older build.** `/developers/` and `/img/*` return 404 there, so nothing on this branch is
true of jevmod.dev until `docs/` is copied to the VPS.

**Screenshots are still drawings.** `docs/img/*.svg` are placeholders and the captions now say so.
`scripts/site/shoot.py` produces real captures once the bot is running in a test server.
