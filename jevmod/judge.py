"""The judgment core: a batch of messages in, one Jev request, a probability per category per message out.

Cost controls live here, not in the bot: local pre-filters decide what is worth judging, a cache reuses verdicts
for repeated text, and only the categories a server enabled are asked.

Findings from the adversarial red team that shaped this file (tests/data/redteam.csv):
- Messages go to Jev as a dict keyed by position (`messages.m3.text`), not a list. With a list, probabilities
  leaked between neighbouring positions in multilingual batches (a clean German message inherited harassment 0.95).
- Text is NFKC-normalised and stripped of combining marks before judging and caching: fullwidth, enclosed
  alphanumerics and zalgo were slipping under the thresholds or the pre-filter.
- The pre-filter counts characters, not space-separated words: Japanese and Chinese never have spaces.
- Every question carries `criteria`, otherwise "offtopic" measured "undesirable" and "spam" caught one-off sales.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from typesafe_sdk import Noul, NoulAnswer, TypeSafeClient

CATEGORIES: dict[str, dict[str, Any]] = {
    "spam": {
        "label": "spam / advertising",
        "instructions": "Is `{m}.text` spam: unsolicited mass promotion, referral or invite farming, repeated offers, "
        "link drops with no conversational purpose, or mass mentions to get attention?",
        "criteria": {
            "true": "advertising or promotion pushed at the community, repeated or copy-pasted offers, "
            "referral/affiliate/invite links, mass @mentions, bare shortened links with no context",
            "false": "a normal conversational message; a one-off personal sale or trade between members; sharing a "
            "guide, video or project once; quoting spam in order to report it",
        },
    },
    "scam": {
        "label": "scam / phishing",
        "instructions": "Is `{m}.text` a scam or phishing attempt aimed at the reader's money, account or credentials?",
        "criteria": {
            "true": "fake giveaways (free Nitro, free skins, crypto doubling), links to domains imitating a service "
            "(discord-gifts, steampowerd, discord-secure), impersonation of staff or support, 'DM me for a deal', "
            "urgent account-verification threats, requests for money or credentials under false pretenses, in any "
            "language or script",
            "false": "a legitimate link to a well-known site, a genuine question about a deal or price, warning "
            "others about a scam, ordinary trading between members",
        },
    },
    "harassment": {
        "label": "harassment / abuse",
        "instructions": "Does `{m}.text` harass, insult, threaten or demean a person or group?",
        "criteria": {
            "true": "insults, slurs, threats, telling someone to leave or hurt themselves, dehumanising or targeted "
            "abuse, in any language (judge the meaning of the words, not the language they are written in)",
            "false": "friendly banter, competitive trash talk with no target, disagreement, criticism of ideas, an "
            "ordinary question or invitation to play",
        },
    },
    "nsfw": {
        "label": "adult / graphic content",
        "instructions": "Does `{m}.text` contain sexual or graphically violent content inappropriate for a general "
        "audience community?",
        "criteria": {
            "true": "explicit sexual content or solicitation (trading nudes, 'DM for pics'), sexual content involving "
            "minors, graphic gore",
            "false": "insults or profanity with no sexual content, romance or dating talk, medical or health talk, "
            "game violence",
        },
    },
    "offtopic": {
        "label": "off-topic for the channel",
        "instructions": "Given `{m}.channel_topic`, is `{m}.text` clearly about something unrelated to that topic?",
        "criteria": {
            "true": "a message whose subject has nothing to do with the channel topic (a recipe in a gaming channel, "
            "job hunting in a support channel) and is not a brief aside",
            "false": "on-topic content, greetings, questions, short asides and reactions. Spam, insults or rule "
            "violations are NOT off-topic by themselves: judge only the subject",
        },
    },
}

LINK_RE = re.compile(
    r"(https?://|hxxps?://|www\.|\S+\[\.\]\S+|\b[\w-]+\.(?:gg|com|net|org|ru|io|xyz|fr|de|jp|br)\b/?)", re.I
)


# Enclosed Alphanumeric Supplement (🄰 🅐 🅰 …) has no NFKC decomposition; map the three A-Z rows by hand.
_ENCLOSED = {cp + k: chr(ord("A") + k) for cp in (0x1F130, 0x1F150, 0x1F170) for k in range(26)}


def normalize(text: str) -> str:
    """NFKC (fullwidth, enclosed letters, ligatures → plain), drop combining marks (zalgo), collapse whitespace."""
    t = unicodedata.normalize("NFKC", text.translate(_ENCLOSED))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(t.split())


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


def prefilter(m: Message, min_chars: int = 8) -> str | None:
    """Return a reason to skip judging, or None to judge. Counts letters/digits in any script, not words."""
    if m.author_trusted:
        return "trusted author"
    text = normalize(m.text)
    if not text:
        return "empty"
    if LINK_RE.search(text):
        return None  # a link is never too short
    letters = sum(1 for ch in text if ch.isalnum())
    if letters < min_chars:
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
        to_judge: list[tuple[Message, str]] = []
        now = time.time()
        for m in messages:
            why = prefilter(m)
            if why:
                out[m.id] = Verdict(m.id, {}, False, why)
                continue
            text = normalize(m.text)
            key = _key(text, m.channel_topic, cats, custom_rules)
            hit = self.cache.get(key)
            if hit and now - hit[0] < self.cache_ttl:
                out[m.id] = Verdict(m.id, dict(hit[1]), True, "cache", dict(hit[2]))
                continue
            to_judge.append((m, text))

        if to_judge and (cats or custom_rules):
            # only the text and the channel topic reach Jev: no author names, no ids beyond the position
            state: dict[str, Any] = {
                "messages": {
                    f"m{i}": {"text": text, "channel_topic": m.channel_topic or "general chat"}
                    for i, (m, text) in enumerate(to_judge)
                },
                "custom_rules": custom_rules,
            }
            questions: dict[str, Noul] = {}
            for i, _ in enumerate(to_judge):
                path = f"messages.m{i}"
                for c in cats:
                    questions[f"{c}_{i}"] = Noul(
                        instructions=CATEGORIES[c]["instructions"].format(m=path), criteria=CATEGORIES[c]["criteria"]
                    )
                for name, rule in custom_rules.items():
                    questions[f"custom__{name}_{i}"] = Noul(
                        instructions=f"Does `{path}.text` break this community rule: `custom_rules.{name}` ({rule!r})?",
                        criteria={
                            "true": "the message does what the rule forbids, as a moderator who wrote it would read it",
                            "false": "the message is ordinary conversation, or the rule does not clearly cover it; "
                            "when the rule lists exceptions, those are allowed",
                        },
                    )
            resp = self.client.system_one(state=state, questions=questions)
            self.requests += 1
            self.input_tokens += getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0
            self.judged_messages += len(to_judge)
            for i, (m, text) in enumerate(to_judge):
                scores = {c: _p(resp.answers[f"{c}_{i}"]) for c in cats}
                custom = {name: _p(resp.answers[f"custom__{name}_{i}"]) for name in custom_rules}
                self.cache[_key(text, m.channel_topic, cats, custom_rules)] = (now, scores, custom)
                out[m.id] = Verdict(m.id, scores, True, "jev", custom)
        elif to_judge:
            for m, _ in to_judge:
                out[m.id] = Verdict(m.id, {}, False, "no categories enabled")
        return [out[m.id] for m in messages]


def _p(answer: Any) -> float:
    if not isinstance(answer, NoulAnswer):
        raise TypeError(f"expected a Noul answer, got {type(answer).__name__}")
    return float(answer.noul)


def _key(text: str, topic: str, cats: list[str], rules: dict[str, str]) -> str:
    norm = text.lower()
    h = hashlib.sha256(f"{norm}|{topic}|{','.join(cats)}|{sorted(rules.items())}".encode()).hexdigest()
    return h[:32]
