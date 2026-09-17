"""The judgment core: a batch of messages in, one Jev request, a probability per category per message out.

Cost controls live here, not in the bot: local pre-filters decide what is worth judging, a cache reuses verdicts
for repeated text, and only the categories a server enabled are asked.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from typesafe_sdk import Noul, TypeSafeClient

CATEGORIES: dict[str, dict[str, str]] = {
    "spam": {
        "instructions": "Is `messages[{i}].text` spam or unsolicited advertising (mass promotion, referral links, "
        "repeated offers, invite farming), rather than a normal conversational message?",
        "label": "spam / advertising",
    },
    "scam": {
        "instructions": "Is `messages[{i}].text` a scam attempt: crypto giveaways, fake support, phishing links, "
        "'DM me for a deal', impersonation of staff, or requests for money or credentials under false pretenses?",
        "label": "scam / phishing",
    },
    "harassment": {
        "instructions": "Does `messages[{i}].text` harass, insult, threaten or demean a person or group (including "
        "slurs and targeted abuse), beyond ordinary banter or disagreement?",
        "label": "harassment / abuse",
    },
    "nsfw": {
        "instructions": "Does `messages[{i}].text` contain sexually explicit or graphically violent content that "
        "would be inappropriate in a general audience community?",
        "label": "adult / graphic content",
    },
    "offtopic": {
        "instructions": "Given `channel_topic`, is `messages[{i}].text` clearly off-topic for this channel "
        "(not a greeting, question, or reasonable aside)?",
        "label": "off-topic for the channel",
    },
}


@dataclass
class Message:
    id: str
    text: str
    author: str = ""
    channel_topic: str = ""
    author_trusted: bool = False


@dataclass
class Verdict:
    message_id: str
    scores: dict[str, float]  # category -> probability
    judged: bool  # False when a pre-filter skipped Jev
    reason: str = ""  # why it was skipped, or "cache" / "jev"
    custom: dict[str, float] = field(default_factory=dict)  # server-defined rules -> probability

    def top(self) -> tuple[str, float] | None:
        allscores = {**self.scores, **self.custom}
        if not allscores:
            return None
        k = max(allscores, key=lambda c: allscores[c])
        return k, allscores[k]


def prefilter(m: Message, min_words: int = 3) -> str | None:
    """Return a reason to skip judging, or None to judge."""
    if m.author_trusted:
        return "trusted author"
    text = m.text.strip()
    if not text:
        return "empty"
    words = [w for w in text.split() if any(ch.isalnum() for ch in w)]
    if len(words) < min_words and "http" not in text.lower():
        return "too short"
    return None


class Judge:
    def __init__(self, client: TypeSafeClient | None = None, cache_ttl_s: int = 86400) -> None:
        self.client = client or TypeSafeClient()
        self.cache: dict[str, tuple[float, dict[str, float], dict[str, float]]] = {}
        self.cache_ttl = cache_ttl_s
        self.requests = 0
        self.input_tokens = 0
        self.judged_messages = 0

    def judge(
        self,
        messages: list[Message],
        categories: list[str],
        custom_rules: dict[str, str] | None = None,
    ) -> list[Verdict]:
        """One Jev request for every message that passes the pre-filter and is not cached."""
        custom_rules = custom_rules or {}
        cats = [c for c in categories if c in CATEGORIES]
        out: dict[str, Verdict] = {}
        to_judge: list[Message] = []
        now = time.time()
        for m in messages:
            why = prefilter(m)
            if why:
                out[m.id] = Verdict(m.id, {}, False, why)
                continue
            key = _key(m.text, m.channel_topic, cats, custom_rules)
            hit = self.cache.get(key)
            if hit and now - hit[0] < self.cache_ttl:
                out[m.id] = Verdict(m.id, dict(hit[1]), True, "cache", dict(hit[2]))
                continue
            to_judge.append(m)

        if to_judge and (cats or custom_rules):
            state: dict[str, Any] = {
                "messages": [{"id": m.id, "text": m.text, "author": m.author} for m in to_judge],
                "channel_topic": to_judge[0].channel_topic or "general chat",
                "custom_rules": custom_rules,
            }
            questions: dict[str, Noul] = {}
            for i, _m in enumerate(to_judge):
                for c in cats:
                    questions[f"{c}_{i}"] = Noul(instructions=CATEGORIES[c]["instructions"].format(i=i))
                for name, rule in custom_rules.items():
                    questions[f"custom__{name}_{i}"] = Noul(
                        instructions=f"Does `messages[{i}].text` violate this community rule: `custom_rules.{name}` "
                        f"(\"{rule}\")?"
                    )
            resp = self.client.system_one(state=state, questions=questions)
            self.requests += 1
            self.input_tokens += getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0
            self.judged_messages += len(to_judge)
            for i, m in enumerate(to_judge):
                scores = {c: float(resp.answers[f"{c}_{i}"].noul) for c in cats}
                custom = {name: float(resp.answers[f"custom__{name}_{i}"].noul) for name in custom_rules}
                self.cache[_key(m.text, m.channel_topic, cats, custom_rules)] = (now, scores, custom)
                out[m.id] = Verdict(m.id, scores, True, "jev", custom)
        elif to_judge:
            for m in to_judge:
                out[m.id] = Verdict(m.id, {}, False, "no categories enabled")
        return [out[m.id] for m in messages]


def _key(text: str, topic: str, cats: list[str], rules: dict[str, str]) -> str:
    norm = " ".join(text.lower().split())
    h = hashlib.sha256(f"{norm}|{topic}|{','.join(cats)}|{sorted(rules.items())}".encode()).hexdigest()
    return h[:32]
