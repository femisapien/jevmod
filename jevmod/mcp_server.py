"""MCP server over stdio: `jevmod mcp`. Two tools, no state, no database.

    moderate(texts, channel_topic="", rules=None) -> one decision dict per text (action, category, probability, scores)
    categories() -> what each category means and its default action and threshold

Register it in Claude Code, Cursor or Codex as a stdio server with command `jevmod` and args `["mcp"]`; the key
comes from `TYPESAFE_API_KEY`, the OS keyring or `.env`, in that order (see `jevmod init`). Built on the MCP Python SDK
(`mcp>=2`, where FastMCP became `MCPServer`).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import Moderator, Policy
from .core.policy import DEFAULT_ACTIONS, DEFAULT_THRESHOLDS
from .judge import CATEGORIES, Judge

server = MCPServer(
    "jevmod",
    instructions="Moderation decisions for user text: spam, scam, harassment, nsfw, offtopic, selfharm, doxxing, "
    "minors and plain-language rules. Every category is on (flag) with default thresholds; offtopic only when a "
    "channel_topic is given. Nothing is stored.",
)
_judge: Judge | None = None  # one client and one verdict cache per process; policy is rebuilt per call


def _moderator(channel_topic: str, rules: dict[str, str] | None) -> Moderator:
    global _judge
    if _judge is None:
        _judge = Judge()
    policy = Policy()
    for c in CATEGORIES:
        policy.set_category(c, "off" if c == "offtopic" and not channel_topic else "flag")
    for name, text in (rules or {}).items():
        policy.set_rule(name, text)
    return Moderator(policy=policy, judge=_judge)


@server.tool()
def moderate(texts: list[str], channel_topic: str = "", rules: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Judge up to 50 texts in one Jev request. Returns one decision per text, in order: action ("none" | "flag"),
    category (the winning one, or "rule:<name>"), probability, scores for every category, judged (false when a
    pre-filter skipped it: too short, empty) and reason. `rules` maps a name to a rule in plain language, up to 5."""
    if not texts:
        return []
    if len(texts) > 50:
        raise ValueError("up to 50 texts per call")
    mod = _moderator(channel_topic, rules)
    return [d.to_dict() for d in mod.check_many(texts, channel_topic=channel_topic)]


@server.tool()
def categories() -> list[dict[str, Any]]:
    """The moderation categories: name, label, when they are true or false, default action and threshold."""
    return [
        {
            "name": name,
            "label": spec["label"],
            "true_when": spec["criteria"]["true"],
            "false_when": spec["criteria"]["false"],
            "default_action": DEFAULT_ACTIONS.get(name, "flag"),
            "default_threshold": DEFAULT_THRESHOLDS.get(name, 0.8),
        }
        for name, spec in CATEGORIES.items()
    ]


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
