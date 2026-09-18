"""`@guarded`: moderate string arguments before a function runs and its string result after. Sync or async."""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any

from jevmod import Decision, Moderator, Policy


class ModerationError(RuntimeError):
    def __init__(self, where: str, d: Decision) -> None:
        super().__init__(f"{where}: {d.category} {d.probability:.2f}")
        self.where, self.decision = where, d


def guarded(fn: Callable[..., Any] | None = None, *, policy: Policy | None = None, topic: str = "") -> Any:
    """Decorator. `@guarded` or `@guarded(policy=..., topic=...)`. Strings in args/kwargs and a string return
    value are judged; anything that triggers an action raises ModerationError instead of reaching the tool/model."""
    mod = Moderator(policy=policy)

    def check(where: str, values: list[Any]) -> None:
        texts = [v for v in values if isinstance(v, str)]
        for text, d in zip(texts, mod.check_many(texts, channel_topic=topic) if texts else [], strict=True):
            if d.action != "none":
                raise ModerationError(f"{where} {text[:40]!r}", d)

    def wrap(f: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(f):

            @functools.wraps(f)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                check("input", [*args, *kwargs.values()])
                out = await f(*args, **kwargs)
                check("output", [out])
                return out

            return awrapper

        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            check("input", [*args, *kwargs.values()])
            out = f(*args, **kwargs)
            check("output", [out])
            return out

        return wrapper

    return wrap(fn) if fn is not None else wrap


@guarded
def post_comment(user: str, text: str) -> str:
    return f"{user} wrote: {text}"


@guarded(topic="customer support")
async def reply(text: str) -> str:
    return "Thanks, a human agent will follow up."


if __name__ == "__main__":
    print(post_comment("ana", "does the new patch fix the inventory bug?"))
    try:
        post_comment("bot", "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro")
    except ModerationError as exc:
        print("blocked:", exc)
    print(asyncio.run(reply("my order never arrived, can you check?")))
