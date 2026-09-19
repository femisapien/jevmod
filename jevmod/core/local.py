"""Local rules: link filtering, word/pattern blocking, anti-raid. Zero cost per message — no Jev call.

`ModerationService.moderate` runs `check()` before every cost gate, so a link filter, a word list or a
pattern keeps working for a tenant that is out of quota, over the shared budget, or never enabled a single
Jev category. A local hit is not a probability: it carries `judged=False`, `probability=1.0` and
`reason="local"`, because pretending a deterministic regex match is a model's confidence would corrupt the
audit log jevmod hands back to a moderator.

Pure apart from `seen` (a `RepeatWindow`, kept by the caller across calls): no network, no database, no
Discord, unit-testable on its own.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from ..judge import LINK_RE, Message, normalize
from .policy import Decision, Policy

# Discord invite hosts, matched case-insensitively against a de-obfuscated copy of the text. `all`/`allowlist`
# modes reuse LINK_RE (judge.py) instead: a second, independent link regex that could disagree with it is a
# support ticket waiting to happen.
_INVITE_HOST_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite|dsc\.gg)", re.I)
_DEFANG_DOT_RE = re.compile(r"\[\.\]")
_DEFANG_HXXP_RE = re.compile(r"hxxps?://", re.I)


def _deobfuscate(text: str) -> str:
    """Undo the two spellings the spec names: `[.]` for a dot, `hxxp(s)` for the scheme."""
    return _DEFANG_HXXP_RE.sub(lambda m: "http" + m.group(0)[4:], _DEFANG_DOT_RE.sub(".", text))


def _fold(text: str) -> str:
    """normalize() (HTML entities, NFKC, zalgo, whitespace) plus an accent fold and a casefold, so the word
    list catches "TÓNTO" and "tonto" as the same word without a second anti-evasion scheme."""
    t = unicodedata.normalize("NFD", normalize(text))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.casefold()


@lru_cache(maxsize=512)
def _word_pattern(word: str) -> re.Pattern[str]:
    return re.compile(r"\b" + re.escape(_fold(word)) + r"\b")


def _host(token: str) -> str:
    t = _deobfuscate(token)
    t = re.sub(r"^\S*?://", "", t)
    t = re.sub(r"^www\.", "", t, flags=re.I)
    t = t.split("/", 1)[0]
    return t.rstrip(".,;:!?)").lower()


def _registrable_domain(host: str) -> str:
    """No public-suffix list here (standard library only): the last two labels, which is exactly right for
    the common case an allowlist is written for (`example.com`) and wrong only for multi-part public
    suffixes (`example.co.uk`), a gap an operator works around by allowlisting the fuller form."""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _link_hit(text: str, policy: Policy) -> bool:
    mode = policy.link_mode
    if mode == "off":
        return False
    if mode == "invites":
        return bool(_INVITE_HOST_RE.search(_deobfuscate(text)))
    if mode == "all":
        return bool(LINK_RE.search(text))
    if mode == "allowlist":
        allow = {d.lower() for d in policy.link_allowlist}
        tokens = [tok for tok in text.split() if LINK_RE.search(tok)]
        return any(_registrable_domain(_host(tok)) not in allow for tok in tokens)
    return False  # an unknown mode never blocks anything; Policy.set_link_mode already refuses writing one


@dataclass
class RepeatWindow:
    """A sliding 60 second window of (timestamp, author) per key, in memory only. A raid is a sixty second
    phenomenon and a disk write per join or per message is the wrong trade; losing the window on restart is
    the correct failure, not a bug to fix."""

    window_s: float = 60.0
    _events: dict[str, list[tuple[float, str]]] = field(default_factory=dict)

    def count(self, key: str, author: str, now: float | None = None) -> int:
        """Record one event for `key` from `author`, drop anything older than `window_s`, and return how many
        distinct authors have posted it (including this one) inside the window."""
        now = time.time() if now is None else now
        events = [(t, a) for t, a in self._events.get(key, []) if now - t < self.window_s]
        events.append((now, author))
        self._events[key] = events
        return len({a for _, a in events})


def check(message: Message, policy: Policy, seen: RepeatWindow) -> Decision | None:
    """The first rule to hit decides — patterns, then words, then links, then raid — because an operator who
    wrote a pattern meant that pattern; the "most severe action wins" rule `decide()` uses for Jev categories
    does not apply to rules an operator wrote by hand."""
    text = message.text or ""

    for name, pattern in policy.patterns.items():
        action = policy.pattern_actions.get(name, "flag")
        if action == "off":
            continue
        try:
            hit = re.compile(pattern).search(text)
        except re.error:
            continue  # a pattern that fails to compile was refused at write time; a stored bad one is skipped
        if hit:
            return _decision(message.id, action, f"local:pattern:{name}")

    if policy.words and policy.word_action != "off":
        folded = _fold(text)
        for word in policy.words:
            if _word_pattern(word).search(folded):
                return _decision(message.id, policy.word_action, "local:word")

    if policy.link_action != "off" and _link_hit(text, policy):
        return _decision(message.id, policy.link_action, "local:link")

    if policy.raid_action != "off" and policy.raid_repeats:
        count = seen.count(normalize(text), message.author)
        if count > policy.raid_repeats:
            return _decision(message.id, policy.raid_action, "local:raid")

    return None


def _decision(message_id: str, action: str, category: str) -> Decision:
    return Decision(message_id, action, category, 1.0, {}, False, "local")
