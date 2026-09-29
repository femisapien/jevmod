"""What came before a message, bounded so a long-running bot cannot grow without limit.

A moderation question is often not answerable from one message. "shut up already" is banter between
two people who have been joking for ten minutes and a pile-on when it is the fourth person to say it
in twenty seconds. The engine has never been able to tell those apart, because `Message` carries the
text and nothing around it.

This module is the window, and only the window. Whether the window improves a verdict is JEV-18's
question and needs JEV-5's harness; shipping the capability and shipping the claim are separate
things and this file is the first one.

**The window is ten messages.** Not a guess: `benchmark/BATCH_EFFECT.md` section 7 measured spam
recall at the shipped threshold across batch sizes on the same 300 messages, 17.3% at one, 32.0% at
five, 38.7% at ten and 37.3% at twenty-five. It saturates at ten, and twenty-five costs 2.5 times
more per judged message to get slightly less. Ten is where the measurement stops paying.

**Only message text lives here.** No author, no id, no timestamp beyond what the bound needs.
`AGENTS.md` and the privacy notice both promise that only message text and the channel topic reach
TypeSafe, and context is more of the same kind of data rather than a new kind. Adding an author name
to this buffer would quietly break that promise, which is why the buffer physically cannot hold one.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

# Measured, see the module docstring. A server may ask for less; it cannot ask for more without
# changing this number and re-running benchmark/batch_effect.py to justify it.
WINDOW = 10

# A hard cap on what an assembled context may cost, independent of the message count, because ten
# messages of four thousand characters is not ten messages of sixty. Tokens are estimated at four
# characters each rather than tokenised: a tokeniser would mean a dependency on the model's own
# vocabulary, which the open package does not have and should not acquire for a bound whose job is
# to be conservative. The estimate errs low per character, so the cap is applied to a number that is
# never larger than the truth.
MAX_CONTEXT_TOKENS = 600
CHARS_PER_TOKEN = 4

# How long a message stays relevant. A channel that went quiet for an hour is a new conversation,
# and pasting the last thing said before lunch under the first thing said after it would be worse
# than no context at all.
MAX_AGE_S = 900.0

# How many channels the buffer will hold at once before evicting the least recently used. A bot in
# two thousand Discord servers with twenty active channels each would otherwise hold forty thousand
# deques for as long as the process lives. This is the bound that makes the class safe to keep in a
# module-level singleton, which is how every adapter uses it.
MAX_CHANNELS = 500


class ConversationBuffer:
    """The last few messages per channel, oldest first, bounded three ways: per channel, by age, and
    by how many channels are held at all.

    Keyed by `(tenant, channel)` rather than by a joined string. The join used a separator a user
    could type, and `forget_context("acme")` then also emptied a tenant called `acme<sep>evil`. A
    tuple cannot be spoofed by message text or by a tenant name.

    Not persisted, on purpose. A restart losing the last ten messages of a conversation costs one
    slightly worse verdict; a table of everybody's recent messages is a data retention question the
    privacy notice does not currently answer, and JEV-20 to JEV-22 own that decision. In-memory only
    keeps this task inside what is already promised.
    """

    def __init__(self, window: int = WINDOW, max_age_s: float = MAX_AGE_S,
                 max_channels: int = MAX_CHANNELS) -> None:
        self.window = window
        self.max_age_s = max_age_s
        self.max_channels = max_channels
        # OrderedDict rather than dict: eviction needs an order, and `move_to_end` makes the channel
        # cache an LRU in two lines instead of a timestamp scan.
        self._channels: OrderedDict[tuple[str, str], deque[tuple[float, str]]] = OrderedDict()
        # Every adapter calls `ModerationService.moderate` through `asyncio.to_thread`, so this is
        # touched from the thread pool and two tenants are two threads. Without the lock, `add`
        # appending while `window_for` iterates raises "deque mutated during iteration", and two
        # threads racing the insert-then-evict in `add` raise KeyError on `move_to_end` for a
        # channel the other one just evicted. Both were reproduced before this existed.
        self._lock = threading.Lock()

    def add(self, channel: tuple[str, str], text: str, now: float | None = None) -> None:
        """Record a message as having been said. Called for every message that arrives, judged or
        not: a pre-filtered "lol" is still part of what the conversation looked like."""
        if not text:
            return
        t = time.time() if now is None else now
        with self._lock:
            q = self._channels.get(channel)
            if q is None:
                q = self._channels[channel] = deque(maxlen=self.window)
                while len(self._channels) > max(1, self.max_channels):
                    evicted, _ = self._channels.popitem(last=False)
                    if evicted == channel:  # max_channels below 1: never evict what was just added
                        break
            if channel in self._channels:
                self._channels.move_to_end(channel)
            q.append((t, text))

    def window_for(self, channel: tuple[str, str], exclude: str = "",
                   now: float | None = None) -> tuple[str, ...]:
        """The recent messages in this channel, oldest first, dropping anything older than the age
        bound.

        `exclude` drops one text, because the message being judged is usually already in the buffer
        by the time it is judged, and showing a message its own text as context would tell the model
        it was said twice.
        """
        t = time.time() if now is None else now
        with self._lock:
            q = self._channels.get(channel)
            if not q:
                return ()
            self._channels.move_to_end(channel)
            # Materialised inside the lock: the generator used to escape it and iterate the deque
            # while another thread was appending to it.
            return tuple(text for at, text in list(q) if t - at <= self.max_age_s and text != exclude)

    def forget(self, channel: tuple[str, str]) -> None:
        """Drop a channel. `/mod forget` and leaving a server both have to reach this, or the thing
        a server owner was told is deleted is still sitting in a deque."""
        with self._lock:
            self._channels.pop(channel, None)

    def forget_all(self) -> None:
        with self._lock:
            self._channels.clear()

    def channels(self) -> tuple[tuple[str, str], ...]:
        """The channel keys currently held. Exists so an erasure request can find every window
        belonging to a tenant without reaching into the buffer's internals, and so a test can prove
        the eviction bound by counting."""
        with self._lock:
            return tuple(self._channels)

    def __len__(self) -> int:
        return len(self._channels)


def assemble(window: tuple[str, ...], max_tokens: int = MAX_CONTEXT_TOKENS) -> tuple[str, ...]:
    """Trim a window to fit the budget, keeping the most recent messages.

    Newest-first is the direction that matters: if only three of ten fit, the three immediately
    before this message are worth more than the three from the start of the window. The result is
    returned oldest-first again, because that is the order a reader, and the model, expects.

    A single message longer than the whole budget is dropped rather than cut. Half a sentence is
    worse than no sentence: it changes what the text says instead of leaving it out.
    """
    out: list[str] = []
    spent = 0
    for text in reversed(window):
        cost = max(1, len(text) // CHARS_PER_TOKEN)
        if spent + cost > max_tokens:
            # `continue`, not `break`. It was `break`, and that dropped the entire window whenever
            # the newest message was oversized: a wall of pasted spam arrives, the next message is
            # judged with no context at all, and the feature turns itself off exactly when it would
            # have helped. Skipping the one that does not fit and carrying on is what the docstring
            # always said this did.
            continue
        out.append(text)
        spent += cost
    return tuple(reversed(out))


# ---------------------------------------------------------------- community state (JEV-30)
#
# What is happening in the channel right now, as one short line beside the conversation window: the rate
# against the channel's usual rate, newcomers, what was flagged, any open incident (JEV-28's events), and
# for the message itself how many near-identical copies of it were just posted and how much its target
# has just received. The window cannot carry these: it drops any line identical to the one judged, so a
# spam wave reaches the model with its copies removed, and it has no authors, so six people telling one
# person to leave reads like one friend teasing another.
#
# Numbers and fixed words only. Every field is a count, a ratio, a known category or a known event type;
# nothing a user typed can reach the line, so it cannot carry text past the pre-filter or the privacy
# promise, and it cannot be used to write instructions to the model.
#
# The budget is JEV-19's: 50 estimated tokens (characters / 4, the unit `assemble` enforces), out of the
# 550 a judged message may add. Measured in `benchmark/community_state/REPORT.md`.
STATE_TOKENS = 50
EVENT_TYPES = ("raid", "spam_wave", "pile_on", "escalation", "conflict")
EVENT_LEVELS = ("E1", "E2", "E3")
_COUNT_CAP = 999
# Whether the line carries the message's own part (its copies and its target) as well as the channel's.
# Decided by the measurement in `benchmark/community_state/REPORT.md`, which compares the two.
STATE_MESSAGE_PART = True


def _flag(name: str, default: bool) -> bool:
    """An on/off environment switch that says so when it does not understand a value, the way
    `JEVMOD_PAD_BATCH` does in `service.py` (`off` once meant on there)."""
    raw = os.environ.get(name)
    no, yes = {"0", "false", "no", "off", "n", ""}, {"1", "true", "yes", "on", "y"}
    if raw is None:
        return default
    v = raw.strip().lower()
    if v not in no | yes:
        logging.getLogger("jevmod").warning({"event": "flag_unrecognised", "flag": name, "value": raw[:20],
                                             "using": "on" if default else "off"})
        return default
    return v in yes


# JEV-19's switch for everything beyond the conversation window. On by default (Omar's rule of 2026-09-27
# night: full context is built on, with a flag to turn it off); off, a message goes out with the window only,
# byte for byte what it was before this existed.
FULL_CONTEXT = _flag("JEVMOD_FULL_CONTEXT", True)


@dataclass(frozen=True)
class CommunityState:
    """The channel's state when a message arrived, filled by whoever computes it (the hosted service's event
    detectors, JEV-26, JEV-27, JEV-70). Every field defaults to "nothing to say"."""

    rate_x: float = 0.0  # messages per minute now, divided by the channel's usual rate; 0 = unknown
    newcomers_5m: int = 0  # messages in the last 5 min from accounts under 7 days or new to the channel
    flagged_5m: tuple[tuple[str, int], ...] = ()  # (category, messages flagged in the last 5 min)
    event: str = ""  # an open incident, one of EVENT_TYPES, or ""
    event_level: str = ""  # one of EVENT_LEVELS
    copies_60s: int = 0  # near-identical copies of this message in the last 60 s
    copies_accounts: int = 0  # posted by how many accounts
    target_5m: int = 0  # messages the person this one addresses received in the last 5 min
    target_users: int = 0  # from how many users


def _n(x: int) -> str:
    x = max(0, int(x))
    return f"{_COUNT_CAP}+" if x > _COUNT_CAP else str(x)


def render_state(state: CommunityState | None, known_categories: tuple[str, ...] = (),
                 message_part: bool | None = None, max_tokens: int = STATE_TOKENS) -> str:
    """The line the model reads, or "" when there is nothing to send.

    Parts are admitted in order of what they are worth (the open event, the message's own copies and its
    target, then the rate, the flags, the newcomers) while they fit the budget, and printed in a fixed order.
    A category outside `known_categories` is dropped rather than printed, so a caller cannot put words in
    the line through a category name; with no list given, only the event types' fixed words and numbers
    appear.
    """
    if state is None:
        return ""
    if message_part is None:
        message_part = STATE_MESSAGE_PART
    chan: dict[str, str] = {}
    msg: dict[str, str] = {}
    if state.event in EVENT_TYPES and state.event_level in EVENT_LEVELS:
        chan["event"] = f"open event {state.event.replace('_', ' ')} {state.event_level}"
    elif state.rate_x > 0:
        chan["event"] = "no open event"
    if message_part and state.copies_60s > 0:
        msg["copies"] = f"{_n(state.copies_60s)} copies by {_n(max(1, state.copies_accounts))} accounts/60s"
    if message_part and state.target_5m > 0:
        msg["target"] = f"its target got {_n(state.target_5m)} msgs from {_n(max(1, state.target_users))} users/5min"
    if state.rate_x > 0:
        r = min(state.rate_x, 999.0)
        chan["rate"] = f"{r:.1f}x usual rate" if r < 10 else f"{r:.0f}x usual rate"
    flags = sorted(((c, k) for c, k in state.flagged_5m if c in known_categories and k > 0),
                   key=lambda ck: (-ck[1], ck[0]))[:2]
    if flags:
        chan["flagged"] = "flagged/5min " + " ".join(f"{c} {_n(k)}" for c, k in flags)
    if state.newcomers_5m > 0:
        chan["newcomers"] = f"{_n(state.newcomers_5m)} new accounts/5min"

    budget = max_tokens * CHARS_PER_TOKEN
    kept: set[str] = set()

    def line() -> str:
        c = ", ".join(chan[k] for k in ("rate", "newcomers", "flagged", "event") if k in kept and k in chan)
        m = ", ".join(msg[k] for k in ("copies", "target") if k in kept and k in msg)
        return "; ".join(p for p in (f"channel: {c}" if c else "", f"this message: {m}" if m else "") if p)

    for k in ("event", "copies", "target", "rate", "flagged", "newcomers"):
        if k in chan or k in msg:
            kept.add(k)
            if len(line()) > budget:
                kept.discard(k)
    return line()
