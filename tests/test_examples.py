"""The headless Python examples run against the real API: sdk scripts as subprocesses, agent_harness and
input_validation modules imported by path and exercised with one clean and one bad input each."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SCAM = "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"
CLEAN = "does the new patch fix the inventory bug?"


def load(relpath: str) -> ModuleType:
    path = EXAMPLES / relpath
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", ["sdk/moderator_basic.py", "sdk/custom_policy.py", "sdk/batch.py"])
def test_sdk_scripts_run(script: str) -> None:
    r = subprocess.run([sys.executable, str(EXAMPLES / script)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "no output"
    if script.endswith("basic.py"):
        assert r.stdout.startswith("flag "), r.stdout
    if script.endswith("custom_policy.py"):
        assert "delete  scam" in r.stdout and "rule:no_politics" in r.stdout, r.stdout
    if script.endswith("batch.py"):
        assert "reason=too short" in r.stdout and "in 1 request(s)" in r.stdout, r.stdout


def test_guard_decorator_sync_and_async() -> None:
    g = load("agent_harness/guard.py")
    assert g.post_comment("ana", CLEAN) == f"ana wrote: {CLEAN}"
    with pytest.raises(g.ModerationError) as exc:
        g.post_comment("bot", SCAM)
    assert exc.value.where.startswith("input") and exc.value.decision.category in ("scam", "spam")

    @g.guarded
    def leaky_tool(query: str) -> str:
        return "DM me for cheap accounts, paypal only, no refunds"

    with pytest.raises(g.ModerationError, match="output"):
        leaky_tool("find a cheap account")
    assert asyncio.run(g.reply("my order never arrived, can you check?")).startswith("Thanks")


def test_claude_agent_sdk_hooks_deny_and_annotate() -> None:
    h = load("agent_harness/claude_agent_sdk_hook.py")
    pre = {"hook_event_name": "PreToolUse"}
    allow = asyncio.run(h.moderate_tool_input({**pre, "tool_input": {"cmd": CLEAN}}, "t1", None))
    assert allow == {}
    deny = asyncio.run(h.moderate_tool_input({**pre, "tool_input": {"path": "x", "content": SCAM}}, "t2", None))
    out = deny["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and out["hookEventName"] == "PreToolUse"
    assert "scam" in out["permissionDecisionReason"] or "spam" in out["permissionDecisionReason"]
    post = asyncio.run(h.moderate_tool_output({"hook_event_name": "PostToolUse", "tool_response": SCAM}, "t2", None))
    assert "additionalContext" in post["hookSpecificOutput"]


def test_langchain_callback_raises_on_hits() -> None:
    pytest.importorskip("langchain_core")
    from langchain_core.outputs import Generation, LLMResult

    lc = load("agent_harness/langchain_callback.py")
    cb = lc.JevmodCallback()
    cb.on_tool_start({"name": "search"}, CLEAN)
    with pytest.raises(lc.ModerationError, match="tool search input"):
        cb.on_tool_start({"name": "search"}, SCAM)
    cb.on_llm_end(LLMResult(generations=[[Generation(text="The patch notes say the inventory bug is fixed.")]]))
    with pytest.raises(lc.ModerationError, match="model output"):
        cb.on_llm_end(LLMResult(generations=[[Generation(text=SCAM)]]))


def test_fastapi_dependency_rejects_with_422() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(load("input_validation/fastapi_dependency.py").app)
    ok = client.post("/comments", json={"text": CLEAN, "topic": "gaming"})
    assert ok.status_code == 200 and ok.json() == {"stored": CLEAN}
    bad = client.post("/comments", json={"text": SCAM, "topic": "gaming"})
    assert bad.status_code == 422 and bad.json()["detail"]["category"] in ("scam", "spam"), bad.text


def test_pydantic_validator() -> None:
    from pydantic import ValidationError

    pv = load("input_validation/pydantic_validator.py")
    assert pv.Review(author="ana", body="Great headset, the mic is a bit quiet though.").body
    with pytest.raises(ValidationError, match="rejected"):
        pv.Review(author="bot", body=SCAM)
