"""The HTTP limits are stated in README.md, AGENTS.md and the MCP tool's description, and enforced in code.

JEV-63. The limits were literals in `Field(...)` calls and the documents repeated them by hand, so a change
to one left the others saying the old number with nothing to notice. The numbers now live in
`jevmod/api/limits.py`; these tests fail when a document or an enforcing call stops agreeing with it.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from jevmod.api import limits
from jevmod.core import store as store_mod

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("doc", "phrase"),
    [
        ("README.md", "`POST /v1/moderate` | up to {MAX_MESSAGES} messages"),
        ("AGENTS.md", "max {MAX_MESSAGES}, bearer tenant key"),
        ("AGENTS.md", "/v1/decisions?limit={DECISIONS_DEFAULT}`"),
        ("AGENTS.md", "(up to {MAX_MESSAGES} texts, actions"),
        ("AGENTS.md", "`POST /v1/moderate`, up to {MAX_MESSAGES} messages a request"),
    ],
)
def test_documents_state_the_limit(doc: str, phrase: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    wanted = phrase.format(**{k: getattr(limits, k) for k in dir(limits) if k.isupper()})
    assert wanted in text, f"{doc} should say {wanted!r}; jevmod/api/limits.py is the source"


def test_mcp_description_states_the_limit() -> None:
    src = (ROOT / "jevmod" / "mcp_server.py").read_text(encoding="utf-8")
    assert f'"""Judge up to {limits.MAX_MESSAGES} texts in one call' in src


def test_server_enforces_the_named_limits() -> None:
    """Read from the source rather than imported: importing server.py opens a SQLite file."""
    src = (ROOT / "jevmod" / "api" / "server.py").read_text(encoding="utf-8")
    assert "max_length=MAX_MESSAGES" in src
    assert "max_length=MAX_TEXT_CHARS" in src
    assert "limit: int = DECISIONS_DEFAULT" in src
    assert "min(limit, DECISIONS_MAX)" in src
    # And no literal copy of any of them is left beside the names.
    assert not re.search(r"max_length=(50|8000)\b", src)


def test_store_default_retention_is_the_named_constant() -> None:
    default = inspect.signature(store_mod.Store.__init__).parameters["retention_days"].default
    assert default == store_mod.RETENTION_DAYS
