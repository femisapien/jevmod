# Split jevmod into an open core and a private commercial repo

## Objective

Omar's business model is Supabase-shaped: the core is free and auditable, the hosted
infrastructure and the commercial surface are his. Today everything lives in one public repo,
so anyone can stand up the whole product, billing and marketing site included, in an
afternoon.

## Why the earlier objection does not hold

The site carries 167 verifiable claims. Counting their sources:

- **210 citations point at core**: `discord_bot.py`, `core/policy.py`, `core/store.py`,
  `judge.py`, `core/service.py`, `api/server.py`, the benchmark.
- **39 point at commercial code**, and 16 of those are `billing.py`, which are promises about
  Stripe rather than about anybody's messages.

Every privacy promise, what reaches the model, what is stored, how long it is kept, rests on
core files that stay public. So the split does not cost the product its auditability.

## What Omar accepts by doing this

39 sentences on the site stop being publicly checkable. They concern billing and the demo.
This is ordinary for open core, but it ends the absolute claim that everything the page
promises can be verified in the open. The claims registry has to say which repository backs
each one.

## Scope

**Stays public in `ohernandezdev/jevmod`:** `jevmod/core/`, `judge.py`, `categories.json`,
`cli.py`, `keys.py`, `__main__.py`, `api/server.py`, the three adapters, `mcp_server.py`,
`packages/jevmod-js/`, `benchmark/`, `tests/`, `examples/`, `plugin/`, `README.md`,
`BENCHMARK.md`, `DISCLAIMER.md`, `CHANGELOG.md`, `LICENSE`.

**Moves to the private repo:** `jevmod/api/billing.py`, `api/hosted.py`, `api/demo.py`,
`api/admin.html`, `deploy/`, `docs/`, `PLANS.md`, `brand/`, `scripts/site/`, `postman/`.

## Constraints

- jevmod.dev must not go down, and the Discord bot must keep running.
- The published pip and npm packages must keep working: nothing public may import a private
  module.
- No secret has ever been in git; they live in the VPS `.env`. That does not change.

## Tasks

- [ ] 1. Prove the boundary: nothing that stays public imports anything that becomes private.
- [ ] 2. Create the private repo and move the commercial files with their history.
- [ ] 3. Make the private repo depend on the public package rather than on a sibling path.
- [ ] 4. Rewrite the public repo's history to drop the commercial files and the margin line.
- [ ] 5. Re-point the 39 commercial claims and say in CLAIMS.md which repo backs each.
- [ ] 6. Redeploy from the private repo and prove the site, the demo and the bot still work.
- [ ] 7. Republish nothing: the version on PyPI and npm is unaffected by the split.

## Evidence

(filled in as each task closes)
