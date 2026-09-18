"""Claude Agent SDK hooks backed by jevmod (pattern from https://code.claude.com/docs/en/agent-sdk/hooks).

PreToolUse: deny a tool call when any string in its input triggers moderation.
PostToolUse: add context when the tool's output triggers moderation.
The hooks are plain async functions (dict in, dict out); only `main()` needs `pip install claude-agent-sdk`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from jevmod import Moderator

mod = Moderator()


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _hits(value: Any) -> list[str]:
    texts = _strings(value)
    decisions = mod.check_many(texts) if texts else []
    return [f"{d.category} {d.probability:.2f}" for d in decisions if d.action != "none"]


async def moderate_tool_input(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
    hits = await asyncio.to_thread(_hits, input_data.get("tool_input", {}))
    if not hits:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": input_data["hook_event_name"],
            "permissionDecision": "deny",
            "permissionDecisionReason": f"jevmod flagged the tool input: {', '.join(hits)}",
        }
    }


async def moderate_tool_output(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
    hits = await asyncio.to_thread(_hits, input_data.get("tool_response", ""))
    if not hits:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": input_data["hook_event_name"],
            "additionalContext": f"jevmod flagged this tool output ({', '.join(hits)}); do not repeat it to the user.",
        }
    }


async def main() -> None:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage

    options = ClaudeAgentOptions(
        hooks={
            "PreToolUse": [HookMatcher(matcher="Bash|Write|Edit|WebFetch", hooks=[moderate_tool_input])],
            "PostToolUse": [HookMatcher(matcher="WebFetch|Read", hooks=[moderate_tool_output])],
        }
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Read comments.txt and summarise the complaints")
        async for message in client.receive_response():
            if isinstance(message, (AssistantMessage, ResultMessage)):
                print(message)


if __name__ == "__main__":
    asyncio.run(main())
