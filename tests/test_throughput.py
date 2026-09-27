"""A busy stream through the real pipeline. JEV-68, `benchmark/throughput_stream/REPORT.md`.

The API refuses a request over about 65,000 input tokens (`400 max_tokens_exceeded`), and nothing
split a batch before 2026-09-27: sixty chat messages in one Twitch window came back `error_open`,
every one of them unjudged. These tests hold the fix to that and to the three things that came with
it: identical lines asked once, a cap on requests in flight, and usage billed to the tenant that
spent it when several streams judge at the same time.

The offline tests at the top are pure code. The rest call Jev and skip without a key; together
they send about 200 chat-sized messages, a little under a cent.
"""

from __future__ import annotations

import asyncio
import csv
import threading
from pathlib import Path

import pytest
from conftest import KEY, NO_KEY_REASON

from jevmod.core import service as service_mod
from jevmod.core.service import Batcher, ModerationService, within_cap
from jevmod.core.store import Store
from jevmod.judge import (
    CATEGORIES,
    MAX_REQUEST_MESSAGES,
    REQUEST_TOKEN_BUDGET,
    Judge,
    Message,
    Verdict,
    estimate_tokens,
    prefilter,
    split_for_request,
    text_tokens,
)

CATS = ["spam", "scam", "harassment", "nsfw", "selfharm", "doxxing", "minors"]
YT = Path(__file__).resolve().parents[1] / "benchmark" / "data" / "youtube_spam"


def _chat(n: int, offset: int = 0) -> list[str]:
    """Real YouTube comments, cut to chat length, all distinct."""
    out: list[str] = []
    for f in sorted(YT.glob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            out += [r["CONTENT"][:200] for r in csv.DictReader(fh) if len(r["CONTENT"].strip()) > 20]
    out = list(dict.fromkeys(out))
    return out[offset : offset + n]


def _items(texts: list[str], context: tuple[str, ...] = ()) -> list[tuple[Message, str]]:
    return [(Message(f"m{i}", t, context=context), t) for i, t in enumerate(texts)]


# ---------------------------------------------------------------- offline


def test_a_chat_batch_of_fifty_is_one_request():
    chunks = split_for_request(_items(["x" * 60] * 50), CATS, {})
    assert [len(c) for c in chunks] == [50]


def test_a_batch_over_fifty_splits_evenly_not_greedily():
    """55 is 28 and 27, never 50 and 5: a request of five is the small request that loses recall."""
    chunks = split_for_request(_items(["x" * 60] * 55), CATS, {})
    assert sorted(len(c) for c in chunks) == [27, 28]


def test_every_request_fits_the_budget_when_messages_are_long():
    ctx = tuple("y" * 200 for _ in range(10))
    items = _items(["z" * 2000] * 120, context=ctx)
    chunks = split_for_request(items, CATS, {"ads": "no advertising of other channels " * 5})
    assert sum(len(c) for c in chunks) == 120
    for c in chunks:
        assert len(c) <= MAX_REQUEST_MESSAGES
        est = sum(estimate_tokens(t, m.context, len(CATS), {"ads": "no advertising of other channels " * 5})
                  for m, t in c)
        assert est <= REQUEST_TOKEN_BUDGET
    sizes = [len(c) for c in chunks]
    assert max(sizes) - min(sizes) <= 1, "balanced"


def test_one_message_bigger_than_the_budget_still_goes_alone():
    chunks = split_for_request(_items(["q" * 400_000]), CATS, {})
    assert [len(c) for c in chunks] == [1]


def test_the_estimate_errs_high_against_what_the_api_billed():
    """Calibrated against `benchmark/throughput_stream/results.jsonl`: fifty chat messages with a
    ten-line window were billed 51,267 input tokens and the same fifty bare 46,600. The estimate has
    to sit above both, or the split would let a refused request through."""
    avg = "w" * 80
    bare = sum(estimate_tokens(avg, (), len(CATS), {}) for _ in range(51))
    ctx = tuple("c" * 48 for _ in range(10))
    windowed = sum(estimate_tokens(avg, ctx, len(CATS), {}) for _ in range(50)) + estimate_tokens(avg, (), 7, {})
    assert bare >= 46_600
    assert windowed >= 51_267


def test_batcher_flushes_what_arrived_while_the_handler_ran():
    """Before: messages added while a batch was being judged waited for the next message to arrive.
    A chat that went quiet after a raid kept the end of the raid unjudged indefinitely."""
    seen: list[list[int]] = []
    holder: list[Batcher] = []

    async def handler(tenant, batch):
        seen.append(list(batch))
        if len(seen) == 1:
            holder[0].add("t", 2)  # arrives while the first batch is being handled; nothing follows it
            await asyncio.sleep(0.05)

    async def main():
        holder.append(Batcher(0.01, handler))
        holder[0].add("t", 1)
        await asyncio.sleep(0.3)

    asyncio.run(main())
    assert seen == [[1], [2]]


def test_the_cap_counts_distinct_texts_so_a_raid_of_copies_is_judged_whole():
    """Three hundred copies of one line plus fifty other lines is 51 positions, not 350 messages."""
    raid = [Message(f"r{i}", "FOLLOW twitch.tv/freesubs4u") for i in range(300)]
    other = [Message(f"o{i}", f"line {i}") for i in range(50)]
    keep, shed = within_cap(raid[:150] + other + raid[150:], 100)
    assert shed == [] and keep == list(range(350))


def test_copies_in_different_channels_are_different_positions():
    msgs = [Message(f"m{i}", "same", channel=f"c{i}") for i in range(5)]
    keep, shed = within_cap(msgs, 3)
    assert len(keep) == 3 and len(shed) == 2


def test_over_the_cap_the_kept_texts_are_spread_across_the_batch_not_its_start():
    msgs = [Message(f"m{i}", f"text {i}") for i in range(300)]
    keep, shed = within_cap(msgs, 100)
    assert len(keep) == 100 and len(shed) == 200
    assert keep == sorted(keep), "the batch order is kept"
    assert max(keep) >= 297, "the end of the window is looked at too"
    assert sorted(keep + shed) == list(range(300))


def test_lines_that_never_reach_the_model_do_not_use_the_cap():
    """Emote chat: 150 lines the pre-filter drops and 50 real sentences. Only the 50 cost anything, so
    none of them is shed. Counting every line shed half of the real ones."""
    lines = [Message(f"e{i}", f"lol{i}") for i in range(150)]
    real = [Message(f"r{i}", f"this is a real sentence number {i} in chat") for i in range(50)]
    msgs = lines[:75] + real + lines[75:]
    keep, shed = within_cap(msgs, 100, lambda m: prefilter(m) is None)
    assert shed == [] and len(keep) == 200


def test_the_estimate_errs_high_for_chinese_and_emoji():
    """Measured on the live API 2026-09-27: Chinese 1.08 tokens a character, emoji 2.06 each. The
    first estimate counted a third of a token for each, and fifty Twitch-length Chinese lines went out
    as one request the API refused."""
    assert text_tokens("直" * 500) >= 540
    assert text_tokens("😂" * 469) >= 966
    assert text_tokens("a" * 300) == 100
    items = _items([f"{i:03d}" + "今天的直播真的很精彩" * 50 for i in range(49)])
    assert len(split_for_request(items, CATS, {})) >= 2


class _CountingJudge:
    """No network: records what it was asked, answers nothing flagged. The cap is about which messages
    reach the judge, which is pure code."""

    def __init__(self):
        self.requests = self.input_tokens = self.judged_messages = 0
        self.asked: list[str] = []
        self.asked_texts: list[str] = []

    def judge(self, messages, categories, custom_rules=None, padding=()):
        self.asked += [m.id for m in messages]
        self.asked_texts += [m.text for m in messages]
        self.requests += 1
        self.judged_messages += len({m.text for m in messages})
        return [Verdict(m.id, {}, True, "jev") for m in messages]


def test_the_service_returns_every_decision_in_order_when_it_sheds(tmp_path, monkeypatch):
    monkeypatch.setattr(service_mod, "MAX_BATCH", 100)
    judge = _CountingJudge()
    svc = ModerationService(Store(tmp_path / "s.sqlite"), judge=judge)  # type: ignore[arg-type]
    msgs = [Message(f"m{i}", f"a distinct chat line number {i}") for i in range(250)]
    decisions = svc.moderate("t", msgs)
    assert [d.message_id for d in decisions] == [m.id for m in msgs]
    shed = [d for d in decisions if d.reason == "over_batch"]
    assert len(shed) == 150 and not any(d.judged for d in shed)
    assert len(judge.asked) == 100 and set(judge.asked).isdisjoint(d.message_id for d in shed)


def test_a_judged_decision_is_not_overwritten_by_a_shed_message_with_the_same_id(tmp_path, monkeypatch):
    monkeypatch.setattr(service_mod, "MAX_BATCH", 2)
    judge = _CountingJudge()
    svc = ModerationService(Store(tmp_path / "s.sqlite"), judge=judge)  # type: ignore[arg-type]
    msgs = [Message("dup", "first distinct line here"), Message("a", "second distinct line here"),
            Message("b", "third distinct line here"), Message("dup", "fourth distinct line here")]
    reasons = [d.reason for d in svc.moderate("t", msgs)]
    assert reasons.count("over_batch") == 2
    assert [r == "over_batch" for r in reasons] == [m.text not in judge.asked_texts for m in msgs]


def test_the_window_is_counted_from_the_oldest_message_not_from_the_last_batch():
    """A message that arrived while a batch was judged is flushed as soon as that batch is done,
    because it has already waited longer than the window. Before, it waited a full window more, so
    a busy stream's cycle was the window plus the judge instead of the longer of the two."""
    flushed: list[tuple[float, list[int]]] = []
    holder: list[Batcher] = []

    async def handler(tenant, batch):
        loop = asyncio.get_running_loop()
        flushed.append((loop.time(), list(batch)))
        if len(flushed) == 1:
            holder[0].add("t", 2)
            await asyncio.sleep(0.8)  # the judge, longer than the window

    async def main():
        holder.append(Batcher(0.3, handler))
        t0 = asyncio.get_running_loop().time()
        holder[0].add("t", 1)
        await asyncio.sleep(1.6)
        return t0

    t0 = asyncio.run(main())
    assert [b for _, b in flushed] == [[1], [2]]
    first, second = flushed[0][0] - t0, flushed[1][0] - t0
    assert 0.28 <= first < 0.6, "the first message still waits one window"
    # Before, the second batch went a full window after the first finished: 0.8 + 0.3 = 1.1 s.
    assert 0.78 <= second - first < 0.95, "the second went as soon as the first batch was done"


def test_a_quiet_stream_still_waits_one_window_per_batch():
    flushed: list[float] = []

    async def handler(tenant, batch):
        flushed.append(asyncio.get_running_loop().time())

    async def main():
        b = Batcher(0.2, handler)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        b.add("t", 1)
        await asyncio.sleep(0.5)
        t1 = loop.time()
        b.add("t", 2)
        await asyncio.sleep(0.5)
        return t0, t1

    t0, t1 = asyncio.run(main())
    assert len(flushed) == 2
    assert flushed[0] - t0 >= 0.18 and flushed[1] - t1 >= 0.18


def test_a_cancelled_batch_does_not_strand_what_arrived_during_it():
    flushed: list[list[int]] = []
    holder: list[Batcher] = []

    async def handler(tenant, batch):
        flushed.append(list(batch))
        if len(flushed) == 1:
            holder[0].add("t", 2)
            await asyncio.sleep(10)

    async def main():
        holder.append(Batcher(0.05, handler))
        holder[0].add("t", 1)
        await asyncio.sleep(0.15)
        holder[0].tasks["t"].cancel()
        await asyncio.sleep(0.2)

    asyncio.run(main())
    assert flushed == [[1], [2]]


# ---------------------------------------------------------------- real Jev

needs_key = pytest.mark.skipif(not KEY, reason=NO_KEY_REASON)


class _Spy:
    """The real client, counted. Every call goes to Jev; this only records how many were in flight."""

    def __init__(self, client):
        self.client, self.lock, self.now, self.peak, self.calls = client, threading.Lock(), 0, 0, 0

    def system_one(self, **kw):
        with self.lock:
            self.now += 1
            self.calls += 1
            self.peak = max(self.peak, self.now)
        try:
            return self.client.system_one(**kw)
        finally:
            with self.lock:
                self.now -= 1


@needs_key
def test_a_window_of_120_chat_messages_is_judged_not_failed_open(tmp_path):
    """The bug itself, through `ModerationService` with the conversation window on: 120 messages in
    one batch. Before the split this was one refused request and 100 `error_open` decisions plus 20
    `over_batch`; now it is judged in requests of at most fifty."""
    judge = Judge(cache_ttl_s=0)
    spy = _Spy(judge.client)
    judge.client = spy  # type: ignore[assignment]
    svc = ModerationService(Store(tmp_path / "s.sqlite"), judge=judge)
    svc.moderate("stream", [Message(f"w{i}", t) for i, t in enumerate(_chat(15, offset=300))])
    before = spy.calls
    import jevmod.core.service as service_mod

    cap = service_mod.MAX_BATCH
    service_mod.MAX_BATCH = 200
    try:
        batch = [Message(f"b{i}", t) for i, t in enumerate(_chat(120))]
        decisions = svc.moderate("stream", batch)
    finally:
        service_mod.MAX_BATCH = cap
    reasons = [d.reason for d in decisions]
    assert "error_open" not in reasons
    assert sum(1 for d in decisions if d.judged) >= 100
    assert spy.calls - before >= 3, "120 messages cannot fit in fewer than three requests of fifty"
    assert spy.peak <= judge.max_inflight


@needs_key
def test_identical_lines_in_one_window_are_asked_once():
    judge = Judge(cache_ttl_s=0)
    raid = "FOLLOW MY CHANNEL for free subs!!! twitch.tv/freesubs4u"
    others = _chat(5, offset=500)
    msgs = [Message(f"r{i}", raid) for i in range(30)] + [Message(f"o{i}", t) for i, t in enumerate(others)]
    verdicts = judge.judge(msgs, CATS)
    assert judge.requests == 1
    assert judge.judged_messages == 6, "thirty copies are one question, plus five other messages"
    raid_scores = {tuple(sorted(v.scores.items())) for v in verdicts[:30]}
    assert len(raid_scores) == 1, "every copy carries the same answer"
    assert verdicts[0].scores["spam"] >= 0.5 or verdicts[0].scores["scam"] >= 0.5


@needs_key
def test_two_streams_at_once_are_each_billed_their_own_usage(tmp_path):
    """Two tenants judging on two threads through one shared judge. With the shared before/after
    totals each one's usage included whatever the other spent while it was waiting."""
    svc = ModerationService(Store(tmp_path / "s.sqlite"), judge=Judge(cache_ttl_s=0))
    small = [Message(f"a{i}", t) for i, t in enumerate(_chat(12, offset=700))]
    big = [Message(f"b{i}", t) for i, t in enumerate(_chat(45, offset=800))]
    barrier = threading.Barrier(2)

    def run(tenant, msgs):
        barrier.wait()
        svc.moderate(tenant, msgs)

    threads = [threading.Thread(target=run, args=("small", small)), threading.Thread(target=run, args=("big", big))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    judged_small, requests_small, _ = svc.store.usage("small")
    judged_big, requests_big, _ = svc.store.usage("big")
    assert (judged_small, requests_small) == (12, 1)
    assert (judged_big, requests_big) == (45, 1)


def test_categories_used_here_are_the_shipped_ones():
    assert all(c in CATEGORIES for c in CATS)


@needs_key
def test_fifty_twitch_length_chinese_lines_are_judged_not_refused():
    """The red-team's reproduction: 49 distinct 500-character Chinese lines. Estimated at a third of a
    token a character they were one request, and the API refused it."""
    judge = Judge(cache_ttl_s=0)
    msgs = [Message(f"z{i}", f"{i:03d}" + "今天的直播真的很精彩大家好" * 38) for i in range(49)]
    verdicts = judge.judge(msgs, CATS)
    assert all(v.judged for v in verdicts)
    assert judge.requests >= 2


@needs_key
def test_a_request_the_api_refuses_as_too_big_is_halved_and_judged():
    """The estimate switched off: fifty long chat lines with a ten-line window go out as one request,
    over the limit. The refusal is not billed; the two halves are judged."""
    judge = Judge(cache_ttl_s=0)
    spy = _Spy(judge.client)
    judge.client = spy  # type: ignore[assignment]
    judge.request_token_budget = 10**9
    long = [t for t in _chat(1200) if len(t) >= 150]
    ctx = tuple(long[:10])
    msgs = [Message(f"h{i}", t, context=ctx) for i, t in enumerate(long[10:60])]
    assert len(msgs) == 50
    verdicts = judge.judge(msgs, CATS)
    assert all(v.judged for v in verdicts)
    assert judge.requests == 2, "two halves answered"
    assert spy.calls == 3, "one refused request, then the two halves"
