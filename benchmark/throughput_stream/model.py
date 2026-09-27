"""The Twitch path against a stream of 100k+ messages, before and after JEV-68. Free: no API calls.

Every input is a number measured in `results.jsonl` by `run.py`, named where it is used. The model
is the steady state of one stream at a constant rate: `Batcher` collects for `WINDOW_S`, hands the
batch to `ModerationService`, and does not start the next batch until the handler returns. Before,
one cycle was the window plus the time the judge takes; after, it is the longer of the two. A peak
is that rate held for as long as it lasts. `run.py replay` measures the same thing end to end.

What it leaves out, on purpose: local rules (they only remove messages before the judge, so the
model is the worst case for them), the cache (in a fast chat the context in the key differs every
window, so copies seldom hit it; `Judge` now asks identical lines in one batch once, and a raid of
copies is cheaper than the model says), and the platform side of acting on a verdict.

    python -m benchmark.throughput_stream.run model
"""

from __future__ import annotations

import math

WINDOW_S = 1.0  # twitch_bot.BATCH_WINDOW_S
MAX_BATCH = 100  # service.MAX_BATCH default
PASS = 0.95  # share of chat-sized messages the pre-filter sends to the model, on the YouTube comments
TOKENS_WINDOW = 1_112  # input tokens per judged message, window full, 17,766 messages (`replay` arms, after)
TOKENS_BARE = 905  # the same without the window (ramp arm, 1,069 requests)
REFUSED_ABOVE = 55  # judged messages per request: 50 with the window accepted, 60 refused (service arm)
PER_REQUEST = 50  # judge.MAX_REQUEST_MESSAGES
INFLIGHT = 4  # judge.MAX_INFLIGHT
KEY_TOKENS_PER_S = 355_000  # input tokens per second the key served for 60 s, 8 workers, production retries (`retries` arm)
USD_PER_M = 0.042
# Median request latency by messages in the request, `size` and `ramp` arms, retries off.
LATENCY_MS = ((1, 300.0), (10, 310.0), (25, 351.0), (50, 490.0))
REFUSAL_MS = 300.0  # a 400 comes back in about 300 ms (size arm, 100 messages)


def latency_s(n: float) -> float:
    pts = LATENCY_MS
    if n <= pts[0][0]:
        return pts[0][1] / 1000
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if n <= x1:
            return (y0 + (y1 - y0) * (n - x0) / (x1 - x0)) / 1000
    return pts[-1][1] / 1000


def before(rate: float) -> tuple[float, float, str]:
    """HEAD before this change: one request per batch, refused above its token limit, and a batch
    beyond MAX_BATCH cut to its first 100. Returns (cycle seconds, share of messages decided, why not)."""
    c = WINDOW_S + latency_s(1)
    for _ in range(50):  # fixed point of cycle = window + latency(batch that cycle collected)
        batch = rate * c
        sent = min(batch, MAX_BATCH)
        judged = sent * PASS
        lat = REFUSAL_MS / 1000 if judged > REFUSED_ABOVE else latency_s(judged)
        c = WINDOW_S + lat
    batch = rate * c
    sent = min(batch, MAX_BATCH)
    if sent * PASS > REFUSED_ABOVE:
        return c, 0.0, "the request is refused; every message fails open"
    return c, sent / batch, "over_batch beyond 100" if batch > MAX_BATCH else ""


def after(rate: float, cap: int = MAX_BATCH) -> tuple[float, float, str]:
    """This change: a batch is split into requests of at most fifty, sent `INFLIGHT` at a time, and
    `Batcher` counts the window from the oldest message waiting, so the cycle is the longer of the
    window and the judge rather than their sum."""
    c = WINDOW_S
    for _ in range(50):
        batch = rate * c
        judged = min(batch, cap) * PASS
        reqs = max(1, math.ceil(judged / PER_REQUEST))
        rounds = math.ceil(reqs / INFLIGHT)
        c = max(WINDOW_S, rounds * latency_s(judged / reqs))
    batch = rate * c
    return c, min(batch, cap) / batch, f"over_batch beyond {cap}" if batch > cap else ""


def first_failure(fn, lo: float = 1.0, hi: float = 1000.0) -> float:
    """The lowest rate at which a stream stops having every message decided, to 0.1 msg/s."""
    while hi - lo > 0.1:
        mid = (lo + hi) / 2
        if fn(mid)[1] < 0.999:
            hi = mid
        else:
            lo = mid
    return lo


def main() -> None:
    rates = (7, 14, 28, 40, 50, 60, 80, 100, 200, 400)
    print("One stream at a constant rate, Twitch path, 1 s window, conversation window on.\n")
    print("| msg/s | before: cycle s | before: decided | after: cycle s | after: decided | judged msg/s after "
          "| key share | $ per stream-hour |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rates:
        cb, sb, _ = before(r)
        ca, sa, _ = after(r)
        judged = r * sa * PASS
        tok = judged * TOKENS_WINDOW
        print(f"| {r} | {cb:.2f} | {sb:.0%} | {ca:.2f} | {sa:.0%} | {judged:.0f} | {tok / KEY_TOKENS_PER_S:.0%} "
              f"| ${tok * 3600 * USD_PER_M / 1e6:.2f} |")

    print(f"\nBefore, every message stops being decided at {first_failure(before):.0f} msg/s, all at once. "
          f"After, the first over_batch is at {first_failure(after):.0f} msg/s and the rest is still judged.\n")
    print("Where `JEVMOD_MAX_BATCH` puts the per-stream ceiling, after:\n")
    print("| JEVMOD_MAX_BATCH | first over_batch at msg/s | judged msg/s at 400 msg/s | key share at that rate |")
    print("|---|---|---|---|")
    for cap in (100, 200, 400):
        ceiling = 400 * after(400, cap)[1] * PASS
        print(f"| {cap} | {first_failure(lambda r, cap=cap: after(r, cap)):.0f} | {ceiling:.0f} | "
              f"{ceiling * TOKENS_WINDOW / KEY_TOKENS_PER_S:.0%} |")

    print("\nWhat a stream of 100,000 messages costs, all of them judged (x 0.95 for the pre-filter):\n")
    print("| | tokens per message | $ per 100k-message stream |")
    print("|---|---|---|")
    for label, t in (("with the conversation window", TOKENS_WINDOW), ("without it", TOKENS_BARE)):
        print(f"| {label} | {t:,} | ${100_000 * PASS * t * USD_PER_M / 1e6:.2f} |")

    print("\nStreams one key sustains at once, at the stream's average rate:\n")
    print("| stream length for 100k messages | average msg/s | streams per key |")
    print("|---|---|---|")
    for hours in (1, 2, 4, 8):
        avg = 100_000 / (hours * 3600)
        per = avg * PASS * TOKENS_WINDOW
        print(f"| {hours} h | {avg:.1f} | {KEY_TOKENS_PER_S / per:.0f} |")


if __name__ == "__main__":
    main()
