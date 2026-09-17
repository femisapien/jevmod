"""jevmod: moderation for communities and apps, powered by Jev.

Developer API, three lines:

    from jevmod import Moderator
    mod = Moderator()                                  # TYPESAFE_API_KEY in the environment
    d = mod.check("FREE NITRO click discord-gifts.ru")  # -> Decision(action="flag", category="scam", probability=0.97)

`check_many([...])` judges a batch in one request. Thresholds and actions come from a `Policy` you can pass in.
"""

from __future__ import annotations

from collections.abc import Sequence

from .core import ACTIONS, Decision, ModerationService, Policy, Store, decide
from .judge import CATEGORIES, Judge, Message, Verdict

__all__ = [
    "ACTIONS",
    "CATEGORIES",
    "Decision",
    "Judge",
    "Message",
    "ModerationService",
    "Moderator",
    "Policy",
    "Store",
    "Verdict",
    "decide",
]

try:
    from importlib.metadata import version as _v

    __version__ = _v("jevmod")
except Exception:  # pragma: no cover
    __version__ = "0.0.0+local"


class Moderator:
    """Stateless convenience wrapper for developers: no SQLite, no tenants, just judge + policy."""

    def __init__(self, policy: Policy | None = None, judge: Judge | None = None) -> None:
        self.policy = policy or Policy()
        self.judge = judge or Judge()

    def check(self, text: str, *, author: str = "", channel_topic: str = "", author_trusted: bool = False) -> Decision:
        return self.check_many([text], author=author, channel_topic=channel_topic, author_trusted=author_trusted)[0]

    def check_many(
        self,
        texts: Sequence[str],
        *,
        author: str = "",
        channel_topic: str = "",
        author_trusted: bool = False,
        ids: Sequence[str] | None = None,
    ) -> list[Decision]:
        msgs = [
            Message(
                ids[i] if ids else str(i), t, author=author, channel_topic=channel_topic, author_trusted=author_trusted
            )
            for i, t in enumerate(texts)
        ]
        verdicts = self.judge.judge(msgs, self.policy.enabled_categories(), self.policy.rules)
        return [decide(self.policy, v) for v in verdicts]
