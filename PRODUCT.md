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
- [ ] Final anti-slop review (in progress 2026-09-18) of README and landing by a fresh agent; fix findings [E]

## Rules for everyone

- Real tests against Jev (`TYPESAFE_API_KEY` in env), no mocks; `ruff`, `mypy` clean; Node: `tsc` strict, vitest.
- Never write a key into any file. Never touch another owner's directory. Do not commit; the coordinator commits.
- English in code and docs. Plain sentences, no marketing adjectives, no emoji walls, no "🚀". Numbers only when measured.

## Notes

- GitHub Pages cannot be enabled while the repo is private on a free personal plan; enable it at launch when the repo goes public (Settings → Pages → branch main, folder /docs).
- npm package not published to the registry yet (`npm publish` from packages/jevmod-js at launch); PyPI likewise (`python -m build && twine upload`).
