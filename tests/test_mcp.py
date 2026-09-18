"""`jevmod mcp` end to end: spawn the server over stdio with the MCP Python client, list tools, call both. Real Jev."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")

mcp = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SCAM = "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"
CLEAN = "Anyone know if the patch fixed the inventory bug?"
POLITICS = "The left is destroying this country, vote them out next month"


def _payload(result: Any) -> Any:
    """Structured content when the server sends it, else the JSON in the first text block."""
    sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if sc:
        return sc["result"] if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


async def _call(session: ClientSession, name: str, args: dict[str, Any] | None = None) -> Any:
    result = await session.call_tool(name, args or {})
    assert not (getattr(result, "is_error", False) or getattr(result, "isError", False)), result
    return _payload(result)


@pytest.mark.anyio
async def test_stdio_server_lists_and_runs_both_tools() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "jevmod", "mcp"], env=dict(os.environ))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) >= {"moderate", "categories"}
        schema = getattr(tools["moderate"], "input_schema", None) or tools["moderate"].inputSchema
        assert "texts" in schema["properties"]

        cats = await _call(session, "categories")
        names = {c["name"] for c in cats}
        assert {"spam", "scam", "harassment", "nsfw", "offtopic", "selfharm", "doxxing", "minors"} <= names
        assert all({"label", "true_when", "false_when", "default_action", "default_threshold"} <= set(c) for c in cats)

        decisions = await _call(
            session,
            "moderate",
            {"texts": [SCAM, CLEAN, POLITICS, "ok"], "rules": {"no_politics": "No political discussion here."}},
        )
        assert len(decisions) == 4
        assert decisions[0]["action"] == "flag" and decisions[0]["category"] in ("scam", "spam"), decisions[0]
        assert decisions[1]["action"] == "none" and decisions[1]["judged"] is True, decisions[1]
        assert decisions[2]["category"] == "rule:no_politics", decisions[2]
        assert decisions[3]["judged"] is False and decisions[3]["reason"] == "too short"

        empty = await _call(session, "moderate", {"texts": []})
        assert empty == []


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
