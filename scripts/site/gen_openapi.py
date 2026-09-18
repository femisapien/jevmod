"""Write docs/openapi.json from the running FastAPI app, so the published schema cannot drift from the code.

The summary line lists the categories from jevmod/categories.json rather than repeating them by hand, which is
how the published description came to name five of the nine. `tests/test_api.py` fails when this is out of date.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "openapi.json"


def schema() -> dict:
    os.environ.setdefault("TYPESAFE_API_KEY", "placeholder-for-schema-generation")
    os.environ.setdefault("JEVMOD_DB", str(ROOT / ".openapi-scratch.sqlite"))
    from jevmod.api.server import app
    from jevmod.judge import CATEGORIES

    s = app.openapi()
    names = ", ".join(CATEGORIES)
    s["info"]["description"] = (
        f"Moderation decisions for user content. One request per batch to Jev (TypeSafe) returns a probability "
        f"for each of {len(CATEGORIES)} categories ({names}) plus any rules you write in your own words. "
        "Thresholds and actions are yours; every decision is logged so you can audit it. "
        "ai_generated is experimental and off by default."
    )
    return s


def main() -> int:
    new = json.dumps(schema(), indent=2, sort_keys=True) + "\n"
    old = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
    OUT.write_text(new, encoding="utf-8")
    print("openapi.json " + ("unchanged" if new == old else "updated"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
