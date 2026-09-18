"""`python -m jevmod` / `jevmod`: `check` judges text from the terminal, `init` stores the key, `mcp` serves the
MCP tools over stdio; `api`, `discord`, `telegram`, `reddit` start that role (default role from JEVMOD_ROLE, then
`api`)."""

from __future__ import annotations

import os
import sys

REQUIRED_TOKEN = {"discord": "DISCORD_TOKEN", "telegram": "TELEGRAM_TOKEN", "reddit": "REDDIT_CLIENT_ID"}
TOKEN_HINT = {
    "DISCORD_TOKEN": "Developer Portal → Bot → Reset Token",
    "TELEGRAM_TOKEN": "@BotFather → /newbot",
    "REDDIT_CLIENT_ID": "https://www.reddit.com/prefs/apps (script app)",
}


def run_role(role: str) -> None:
    role = role.lower()
    needed = REQUIRED_TOKEN.get(role)
    if needed and not os.environ.get(needed):  # before the adapter imports and creates its SQLite file
        raise SystemExit(f"set {needed} ({TOKEN_HINT[needed]})")
    if role == "api":
        import uvicorn

        uvicorn.run(
            "jevmod.api.server:app",
            host=os.environ.get("JEVMOD_HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8080")),
            log_level="info",
        )
    elif role == "discord":
        from .adapters.discord_bot import main as run

        run()
    elif role == "telegram":
        from .adapters.telegram_bot import main as run

        run()
    elif role == "reddit":
        from .adapters.reddit_bot import run

        run()
    elif role == "demo":
        import uvicorn

        uvicorn.run(
            "jevmod.api.demo:app",
            host=os.environ.get("JEVMOD_HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8080")),
            log_level="info",
        )
    elif role == "mcp":
        from .mcp_server import main as run

        run()
    else:
        raise SystemExit(f"unknown role {role!r}; use check | init | mcp | api | demo | discord | telegram | reddit")


def main() -> None:
    if len(sys.argv) > 1:
        from .cli import main as cli

        sys.exit(cli(sys.argv[1:]))
    run_role(os.environ.get("JEVMOD_ROLE", "api"))


if __name__ == "__main__":
    main()
