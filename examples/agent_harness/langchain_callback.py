"""LangChain callback: moderate tool inputs and model outputs with jevmod. `pip install langchain-core`."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from jevmod import Moderator, Policy


class ModerationError(RuntimeError):
    pass


class JevmodCallback(BaseCallbackHandler):
    """Attach with `callbacks=[JevmodCallback()]` on a chain, agent or model. Raises on a hit, which LangChain
    surfaces to the caller; catch ModerationError where you want to answer the user instead."""

    raise_error = True

    def __init__(self, policy: Policy | None = None, topic: str = "") -> None:
        self.mod = Moderator(policy=policy)
        self.topic = topic

    def _check(self, where: str, texts: list[str]) -> None:
        texts = [t for t in texts if t]
        decisions = self.mod.check_many(texts, channel_topic=self.topic) if texts else []
        for text, d in zip(texts, decisions, strict=True):
            if d.action != "none":
                raise ModerationError(f"{where}: {d.category} {d.probability:.2f} in {text[:60]!r}")

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        self._check(f"tool {serialized.get('name', '?')} input", [input_str])

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self._check("model output", [g.text for gens in response.generations for g in gens])


if __name__ == "__main__":
    from langchain_core.outputs import Generation

    cb = JevmodCallback()
    cb.on_tool_start({"name": "search"}, "inventory bug patch notes")
    try:
        cb.on_llm_end(LLMResult(generations=[[Generation(text="DM me for cheap accounts, paypal only, no refunds")]]))
    except ModerationError as exc:
        print("blocked:", exc)
