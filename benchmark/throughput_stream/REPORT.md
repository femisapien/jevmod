# A live chat of 100,000+ messages per stream: throughput, concurrency, cost

JEV-68. Measured 2026-09-27 against the live TypeSafe API, from one machine on one key, with the
runner next to this file (`run.py`, `model.py`). Every request and every batch is one row in
`results.jsonl`; `python -m benchmark.throughput_stream.run summary` rebuilds the replay table below
from it. The text is the YouTube comment set in `benchmark/data/youtube_spam/` (fetched by
`benchmark/prepare.py`), cut at 200 characters, median 48: closer to a chat line than the moderation
corpus JEV-6 used.

Total spent on these measurements: **about $3.18** (75.8 million input tokens at $0.042 per million).
$1.21 of it is the two runs with production retries on. The live-API tests added with the change cost
about a cent a run.

## The answers

| question | answer |
|---|---|
| Messages per second one stream has fully judged | **60 measured** (95% judged, the rest too short to judge); at 100 msg/s, 90% judged and 5% shed. The model puts the edge at 100 (Twitch, 1 s window) |
| Before this change | already 10% `error_open` at 30 msg/s; **95% `error_open` at 60 msg/s**, the whole batch failing open. The model puts the edge at 44 |
| What happens above it now | the batch is capped at 100 distinct texts; the rest is shed as `over_batch`, spread across the window |
| Messages per second one key serves | **about 320 judged with the conversation window** (four streams at 100 msg/s: 323 judged a second), about 400 bare |
| Where the 429s and retries start | at the key's sustained limit, about 355,000 input tokens a second: past four requests of fifty in flight bare, and at four with the window |
| What retries do to latency past that point | p95 goes from 0.6 s to 2.9 s; 1.2% of requests still fail |
| Longest wait from a message arriving to its decision | 1.7 to 2.8 s for one stream up to 150 msg/s; 3.0 s with four streams at 100 msg/s |
| Cost | **1,112 input tokens per judged message**, $0.047 per thousand, **$4.44 per 100,000-message stream** |
| Cost per stream-hour | $1.11 at 7 msg/s (100k over 4 h), $4.44 at 28 msg/s (100k in 1 h), $16 at a held 100 msg/s |

"Judged" throughout means the message went to the model and came back with a verdict. About 5% of
chat never goes: the pre-filter drops lines that are too short to judge (`too short`).

## 1. The request limit, and the bug it hid

The API refuses a request over about 65,000 input tokens with `400 max_tokens_exceeded` (`max_request`
rows: 69 chat messages, 64,275 tokens, accepted; 71 refused; 75 refused). A chat message costs about
900 tokens bare and 1,030 to 1,110 with the ten-line conversation window, so **a request stops at
roughly 55 to 60 chat messages**.

Nothing split a batch before this change. `ModerationService` sent up to `MAX_BATCH` (100) messages
in one request, and a Twitch window that collected more than about 55 was refused whole: every message
in it came back `error_open`, unjudged, and it happened exactly when the chat was busiest (`service`
rows: 50 judged, 60 and 100 `error_open`).

`Judge` now splits a batch into requests under a 56,000-token estimate (`split_for_request`), evenly
rather than greedily because a small request loses recall (`benchmark/BATCH_EFFECT.md`), and never
more than fifty messages to a request.

| messages per request | p50 ms | max ms | input tokens per message |
|---|---|---|---|
| 10 | 310 | 470 | 1,039 |
| 25 | 350 | 372 | 978 |
| 50 | 521 | 528 | 932 |
| 100 | refused (400) | | |

(`size` rows, bare, three requests each.)

## 2. What one key serves

Batches of fifty, closed loop, fifteen seconds a level (`ramp` rows, retries off so a 429 is counted
rather than hidden):

| requests in flight | requests | p50 ms | p95 ms | max ms | 429 | judged msg/s |
|---|---|---|---|---|---|---|
| 1 | 30 | 488 | 621 | 623 | 0 | 100 |
| 2 | 59 | 505 | 591 | 659 | 0 | 194 |
| 4 | 125 | 485 | 600 | 715 | 0 | 404 |
| 8 | 367 | 493 | 616 | 814 | **226 (62%)** | 454 |

The latency does not move with load; the key refuses instead. The 429 carries `retry-after: 1`.

The same eight in flight with production's retries on (3 retries, backoff 0.5 to 8 s), `retries` rows:

| held for | requests | p50 ms | p95 ms | max ms | failed after retries | judged msg/s | input tokens/s |
|---|---|---|---|---|---|---|---|
| 15 s | 156 | 513 | 2,747 | 4,055 | 1 | 467 | 423,000 |
| 60 s | 488 | 531 | 2,933 | 4,579 | 6 (1.2%) | 391 | 355,000 |

So retries buy almost nothing over four in flight (391 against 404 msg/s sustained) and cost five
times the p95. The four-in-flight level ran bare (905 tokens a message) for fifteen seconds, inside the
key's burst allowance; the sustained limit is the 355,000 tokens a second of the sixty-second run. With
the conversation window a message costs 1,112 tokens, so the same limit is about 320 judged messages a
second, which is what four streams at 100 msg/s reached (section 3). **`Judge` now holds at most four requests in flight per process**, across every tenant
sharing it (`MAX_INFLIGHT`, `JEVMOD_MAX_INFLIGHT` for a key with a different limit). That turns the
key's limit into a queue inside the bot rather than 429s and retry sleeps.

## 3. One stream, end to end

`replay`: messages arrive at a constant rate for twenty seconds, `Batcher` collects them on the
Twitch window (1 s), `ModerationService.moderate` judges each batch on a thread with production
retries on, exactly as `twitch_bot._handle_batch` does. "before" is `main` at 7e3f0a7, run from a
separate checkout; "split only" is the request split without the `Batcher` and cap changes below.

| code | streams x msg/s | raid share | messages | judged | over_batch | error_open | batch p50 | longest wait s | tokens per judged message |
|---|---|---|---|---|---|---|---|---|---|
| before | 1 x 30 | 0% | 599 | 85% | 0% | 10% | 47 | 2.58 | 1,185 |
| before | 1 x 60 | 0% | 1,199 | 5% | 0% | 95% | 74 | 1.92 | 947 |
| before | 1 x 100 | 0% | 1,998 | 0% | 21% | 79% | 128 | 1.68 | - |
| before | 1 x 150 | 0% | 2,997 | 0% | 48% | 52% | 194 | 1.97 | - |
| before | 1 x 150 | 50% | 2,999 | 0% | 47% | 53% | 192 | 1.68 | - |
| after | 1 x 30 | 0% | 599 | 95% | 0% | 0% | 31 | 1.69 | 1,104 |
| after | 1 x 60 | 0% | 1,198 | 95% | 0% | 0% | 61 | 1.93 | 1,074 |
| split only | 1 x 80 | 0% | 1,598 | 75% | 21% | 0% | 129 | 2.64 | 1,066 |
| after | 1 x 100 | 0% | 1,999 | 90% | 5% | 0% | 103 | 2.79 | 1,132 |
| after | 2 x 100 | 0% | 3,998 | 94% | 1% | 0% | 102 | 2.15 | 1,137 |
| after | 4 x 100 | 0% | 7,988 | 81% | 15% | 0% | 127 | 3.02 | 1,129 |
| after | 1 x 150 | 0% | 5,996 | 67% | 30% | 0% | 154 | 2.81 | 1,066 |
| after | 1 x 150 | 50% | 2,996 | 98% | 0% | 0% | 154 | 1.73 | 544 |

Before, a stream at 30 msg/s already lost 10% to `error_open` (a burst pushed one window past the
request limit), and at 60 msg/s it lost 95%. After, a stream is fully judged to about 100 msg/s.

"Longest wait" is from a message arriving to its decision, the slowest message in the run. A decision
waits for the window (1 s) plus the judge (0.5 to 0.8 s).

`model.py` (free) is the same pipeline as arithmetic, from the measured latencies: before, every
message stops being decided at 44 msg/s; after, the first `over_batch` is at 100 msg/s. The replay
shows 5% shed at 100 msg/s where the model shows none, because real batches vary around the mean and
the cap cuts the big ones.

## 4. Where it queues

In order, from a single message to the whole bot:

1. **Per stream, in `Batcher`.** One batch per tenant at a time, so a tenant's batches are judged in
   order and its quota check sees what the previous batch spent. What arrives while a batch is being
   judged waits in `pending`. That wait is bounded by time, not by count: the next batch goes as soon
   as the current one is back.
2. **Per batch, at `MAX_BATCH`.** A batch over 100 distinct texts is cut to 100; the rest is shed as
   `over_batch` (`action=none`, `judged=false`). This is the load shedding. It is shedding rather than
   a growing backlog on purpose: a live chat cannot be slowed down, and a verdict that arrives a
   minute late is no use to anybody watching.
3. **Across streams, at the judge.** Four requests in flight per process, and behind them the key's
   sustained limit. With four streams at 100 msg/s each (400 msg/s against about 320 the key serves
   with the window) the judge's time grows from 0.5 s to about 1.3 s, the batches grow with it, and
   15% is shed. Two streams at 100 msg/s shed 1%.
4. **Not measured: threads and platform actions.** Each tenant's batch holds one thread from asyncio's
   default pool while it waits for the judge (`min(32, cores + 4)` threads), and Twitch's `delete` and
   `timeout` calls are awaited one after another inside the batch. The default policy is flag-only,
   which makes no Helix call, so neither showed up here; a channel set to delete during a raid would
   make its batches longer by one Helix round trip per action.

## 5. What changed in the code

- **The request split** (`jevmod/judge.py`, `split_for_request`, `REQUEST_TOKEN_BUDGET`). Section 1.
  Chunks of one batch go out in parallel under the in-flight cap; chunks that were answered are
  counted, billed and cached even when another chunk of the same batch fails, and the batch then
  fails open as before. The estimate counts text by script: ASCII at a third of a token a character,
  anything else at 1.5 and emoji at 2.5, because Chinese measured 1.08 tokens a character and emoji
  2.06 each; the channel topic every position carries is counted too. A request the API refuses as
  too big anyway is halved and asked again (`Judge._ask`), so an estimate that is wrong costs one
  unbilled refusal and not a batch failing open. Both are tested against the live API
  (`tests/test_throughput.py`).
- **Four requests in flight per process** (`MAX_INFLIGHT`). Section 2.
- **Identical lines asked once.** Copies of one text in one batch read the same context, so they are
  one position in the request and share its answer. The raid replay above: half the messages copies of
  three lines, 98% judged, 544 tokens per judged message instead of 1,066. A tenant's usage counts the
  positions asked, which is what was spent.
- **`MAX_BATCH` counts distinct texts that will reach the model** (`within_cap` in
  `jevmod/core/service.py`), per channel. A raid of 300 copies is one position; counting messages shed
  200 of them unjudged in exactly the batch a raid is. Before, 150 msg/s with half of it raid copies:
  0% judged. After: 98%. Lines the pre-filter drops and lines the cache answers cost nothing and do
  not count, so emote chat does not push real sentences out.
- **Over the cap, what is kept is spread across the batch**, not its first 100. Taking the start shed
  the end of every overloaded window, the same part every time.
- **`Batcher` counts the window from the oldest waiting message.** Before, what arrived while a batch
  was judged waited a full window more, so the cycle was window plus judge (1.5 s) and batches were
  half as big again as the window alone makes them. That is what put the first `over_batch` at 65 to
  80 msg/s with the split alone ("split only", 80 msg/s: 21% shed). Now the cycle is the longer of the
  two.
- **`Batcher` flushes what arrived during a batch** even if nothing else arrives after it. Before,
  the end of a raid waited for somebody else to speak.
- **Decisions are matched to messages by position**, not by id, in `moderate` and in the shed path:
  nothing makes ids unique, and a map by id handed one message's decision to another.
- **A cancelled batch does not strand what arrived during it**: the re-flush runs in `finally`.
- **A tenant is billed its own usage.** With several streams judging at once through one judge, the
  shared before/after totals billed each tenant for what the others spent in the meantime
  (`Judge.thread_usage`).

## 6. What it means for 100,000 messages per stream

100,000 messages is 7 msg/s averaged over four hours, 28 msg/s over one. Averages are not the problem;
peaks are. A raid, a giveaway or a clip moment runs a chat at several times its average for seconds to
minutes.

- **A stream is fully judged to at least 60 msg/s measured and about 100 by the model**, 90% at a held
  100 msg/s, and a raid of copies costs one position per line, so a copypasta wave above that is still
  judged whole. Above 100 distinct messages a second the stream is sampled: 67% judged at 150 msg/s.
- **One key serves about 320 judged messages a second** with the window across every stream on it:
  about three streams at a 100 msg/s peak at the same moment, or 48 four-hour 100k streams at their
  average.
- **`JEVMOD_MAX_BATCH` is the per-stream knob.** 200 raises one stream's ceiling to about 200 msg/s by
  the model, and lets that one stream take half of the key. That is a decision for a plan that pays for
  it (JEV-66), not a default.
- **Cost per stream-hour** is the rate: 1,112 tokens per judged message with the window, 0.95 of
  messages judged. $1.11 an hour at 7 msg/s, $4.44 at 28, $16 at 100 held. The ceiling per stream at
  the default cap is about $16 an hour.

## What this does not say

One machine, one key, one region, one afternoon. Twenty seconds per replay and sixty seconds for the
longest sustained run: no hour-long run, which would cost about $15 at 100 msg/s. The text is YouTube
comments, not Twitch chat, which is shorter and has more emote-only lines the pre-filter drops, so the
tokens per message here are likely an overestimate for Twitch. The replays run the Twitch path; the
Discord and Telegram windows are 2 s, which halves the per-stream ceiling to about 50 distinct
messages a second for the same cap.

## Runs set aside

Rows carrying a `note` are left out of the tables. One is the first four-stream replay, whose
per-batch tokens were read from the judge's shared totals and so counted the other streams' spend
(fixed in `run.py`; its real cost is counted in the total above). Two runs labelled as raid runs
did not apply the raid mix because of a bug in `run.py`; they are plain runs at 150 msg/s, marked
`repeat`, and counted as such.
