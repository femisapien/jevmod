"""`python -m jevmod` starts the role named by JEVMOD_ROLE: api (default), discord, telegram or reddit."""

from __future__ import annotations

import os
import sys


def main() -> None:
    role = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JEVMOD_ROLE", "api")).lower()
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
    else:
        raise SystemExit(f"unknown role {role!r}; use api | discord | telegram | reddit")


if __name__ == "__main__":
    main()
