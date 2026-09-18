"""`python -m jevmod` / `jevmod`: `check` judges text from the terminal, `init` stores the key, `mcp` serves the
MCP tools over stdio; `api`, `discord`, `telegram`, `reddit` start that role (default role from JEVMOD_ROLE, then
`api`)."""

from __future__ import annotations

import os
import sys


def run_role(role: str) -> None:
    role = role.lower()
    if role == "api":
        import uvicorn

        uvicorn.run("jevmod.api.server:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="info")
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

        uvicorn.run("jevmod.api.demo:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="info")
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
