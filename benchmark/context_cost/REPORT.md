# What the conversation window costs per judged message

JEV-67. Run on 2026-09-27 with `benchmark/context_cost/run.py` against the live API, one machine, one
key. Raw rows in `results/raw.jsonl` (one line per request arm, with every request's reported tokens
and wall time) and `results/limit.jsonl`. The acceptance criteria were written before the run, in
`odd/tasks/context-cost.md`.

**The run cost $0.27**: 489 requests, 6,380,011 input tokens at TypeSafe's list price of $42 per
billion input tokens (typesafe.ai, read 2026-09-27). The limit probe in section 6 added 177,591 input
tokens, under a cent; the rejected requests in it cost nothing.

## The short answer

1. **The window is cheap on a busy channel and expensive on a quiet one, and the difference is
   padding, not context.** With the shipped window of ten and a real channel topic, a judged message
   costs 1.29 times the no-window request in batches of 25 and 1.37 times in batches of 10. A message
   judged alone costs **4.53 times**, because the service pads a batch under ten with the window's
   messages and asks every category about each of them. Padding is 92% to 96% of what the window
   costs a message judged alone.
2. **What drives the bill is positions, not text.** Every position in a request costs about 930 to
   1,060 input tokens, most of it the seven category questions asked about it. A message of context
   attached to a judged message costs about 29 tokens. Ten of them are under a third of a position.
3. **The topic costs 2% to 3%**, at every window and batch size. It is not a cost decision.
4. **A window of twenty does not fit.** Half the batches of 50 with twenty messages of context were
   rejected by TypeSafe's 64k-token request limit, and a rejected request fails open: nothing in the
   batch is moderated. The same limit rejects a batch of 100 with no window at all, and the service
   allows 100 (section 6).
5. **Latency moves less than cost.** Median request time at a window of ten is 5% to 20% above no
   window: 250 to 291 ms for a message alone, 356 to 429 ms for 25.

## 1. What was measured

**The path is production's.** Each request goes through a fresh `ModerationService.moderate` on an
in-memory `Store`, with a `ConversationBuffer` holding the N comments posted before the batch in the
same stream. The service attaches the window to every message through `assemble`, pads a batch
under ten from the same window (`PAD_BATCH` on, as shipped), and `Judge` sends the request with the
seven categories that ship enabled. The only addition is a wrapper around the real TypeSafe client
that records the input and output tokens the API reports and the wall time of the call. Nothing is
estimated from characters. The cache is off (`cache_ttl_s=0`), so every figure is a request that was
actually sent; a production cache hit would cost nothing and is not credited here.

**The stream** is the UCI YouTube Spam Collection (archive.ics.uci.edu, dataset 380): five videos,
1,956 comments, each video sorted by posting date and treated as one channel. Median length 48
characters, the shortest real text in the benchmark and the nearest thing to chat it has. About half
of it is spam, which does not change a token count.

**The arms are paired.** For each batch size the positions were drawn once from a fixed seed (30
requests of 1, 10 of 10, 6 of 25, 6 of 50), and every window and topic arm judged exactly the same
messages at each position; `report` checks this and it holds for all 35 arms. The arms ran in a
shuffled order per position, so no arm owns a time of day.

**Per judged message.** 603 of 4,730 messages sent (12.7%) were skipped by the pre-filter as too
short and cost nothing; every figure divides by the 4,127 that were judged, as `LOAD.md` did. Cost
per message sent is lower by that share.

**The topic** is 138 characters, the length of a typical Discord channel topic. With no topic,
`Judge` sends "general chat" at every position, so the topic arm measures the difference a real
topic makes, not the difference between something and nothing.

## 2. Input tokens per judged message

Multiplier: summed tokens against the window-0 arm of the same batch size and topic, on the same
messages. The range is the smallest and largest per-request ratio.

| batch | window | topic | context kept | positions per request | tokens per judged msg | x vs window 0 | per-request range | $ per 1K judged |
|---|---|---|---|---|---|---|---|---|
| 1 | 0 | yes | 0.0 | 2.0 | 2,168 | 1.00x | | $0.091 |
| 1 | 5 | yes | 4.9 | 5.0 | 5,169 | 2.38x | 1.90 to 2.60 | $0.217 |
| 1 | 10 | yes | 9.9 | 9.7 | 9,815 | **4.53x** | 2.82 to 4.91 | $0.412 |
| 1 | 20 | yes | 19.5 | 10.0 | 10,389 | 4.79x | 4.18 to 5.14 | $0.436 |
| 10 | 0 | yes | 0.0 | 10.5 | 1,096 | 1.00x | | $0.046 |
| 10 | 5 | yes | 5.0 | 10.5 | 1,287 | 1.17x | 1.06 to 1.31 | $0.054 |
| 10 | 10 | yes | 9.8 | 10.5 | 1,499 | **1.37x** | 1.16 to 1.59 | $0.063 |
| 10 | 20 | yes | 17.8 | 10.5 | 1,707 | 1.56x | 1.35 to 1.64 | $0.072 |
| 25 | 0 | yes | 0.0 | 25.2 | 1,000 | 1.00x | | $0.042 |
| 25 | 5 | yes | 5.0 | 25.2 | 1,155 | 1.16x | 1.08 to 1.21 | $0.049 |
| 25 | 10 | yes | 10.0 | 25.2 | 1,294 | **1.29x** | 1.16 to 1.38 | $0.054 |
| 25 | 20 | yes | 20.0 | 25.2 | 1,565 | 1.56x | 1.33 to 1.76 | $0.066 |
| 50 | 0 | yes | 0.0 | 46.3 | 982 | 1.00x | | $0.041 |
| 50 | 5 | yes | 4.9 | 46.3 | 1,092 | 1.11x | 1.08 to 1.13 | $0.046 |
| 50 | 10 | yes | 9.8 | 46.3 | 1,202 | **1.22x** | 1.15 to 1.29 | $0.051 |
| 50 | 20 | yes | 19.7 | 43.7 | 1,340 | 1.36x | 3 of 6 rejected | $0.056 |

The rows without a topic are 2% to 3% lower and give the same multipliers to within 0.01; all 32
are printed by `report`. "Positions per request" for 10, 25 and 50 is the batch plus the lead filler
at `m0`, less the messages the pre-filter skipped. "Context kept" below the window is `exclude`
dropping a comment identical to the one being judged, which in a spam stream happens.

**The batch-of-50, window-20 row is survivorship.** It is priced on the three requests that fit under
the limit; the three that did not were the larger ones, and they judged nothing (section 6).

**Against JEV-6.** `LOAD.md` measured 1,305 tokens per message without the window and 1,842 with it,
41% more, in batches of 25 on `data/items.jsonl`. This run finds 972 and 1,266, 30% more, in batches
of 25 without a topic. Direction and size agree; the difference is text length. Two thirds of
`items.jsonl` is prompts and comments with a median of 176 to 380 characters, and a longer message
makes both the judged position and every context entry cost more.

## 3. Why a message judged alone costs four and a half times

| window | padding on | padding off | positions, padding on | share of the window's cost that is padding |
|---|---|---|---|---|
| 5 | 5,035 | 2,278 | 5.0 | 94% |
| 10 | 9,553 | 2,431 | 9.7 | 96% |
| 20 | 10,119 | 2,718 | 10.0 | 92% |

Batch of one, no topic, tokens per judged message; with no window it is 2,114, two positions, the
filler and the message. **With padding off, the window of ten costs 15% more (2,431 against 2,114).
With padding on, 352% more.** The window has two costs and they are not the same size:

- **The `context` field** on the judged message: about 29 tokens per entry, so ten entries are about
  290 tokens against a position's 950 to 1,060.
- **Padding.** `_judge_batch` hands the window to `Judge` as padding when the batch is under ten, and
  `Judge` puts it in positions `m0` to `m9` and asks every category about each. That is eight more
  positions. It is the recall fix from JEV-57 (`odd/tasks/pad-small-batches.md`: 17.3% spam recall
  alone against 38.7% in ten), and it is what the window costs a quiet channel.

Padding is capped at ten positions, which is why twenty messages of window cost a message alone
barely more than ten: 4.79x against 4.53x.

## 4. Per position, and per context entry

From the window-0 arms: **1,057 input tokens per position** in a request of two, 965 in ten, 933 in
25 and 50. Seven questions are sent once per position; dividing, each is about 130 tokens, so the
question text, not the message, is most of every position. From the batch-of-25 arms, each message
of context attached to each judged message adds **29 tokens** on this stream.

On text of this length a request costs close to

    tokens = 950 x positions + 29 x (context entries summed over the judged messages)

and only the second term grows with message length.

## 5. Latency

Client wall time per request, retries included, topic on. Six to thirty requests per cell: enough
for a median, not for a tail. With six requests the p95 is the maximum.

| batch | window | requests | p50 ms | p95 ms |
|---|---|---|---|---|
| 1 | 0 | 29 | 250 | 389 |
| 1 | 10 | 29 | 291 | 360 |
| 1 | 20 | 29 | 289 | 404 |
| 10 | 0 | 10 | 301 | 350 |
| 10 | 10 | 10 | 315 | 374 |
| 25 | 0 | 6 | 356 | 389 |
| 25 | 10 | 6 | 429 | 464 |
| 50 | 0 | 6 | 480 | 540 |
| 50 | 10 | 6 | 562 | 689 |

Every cell is in `report`. Padding a message alone to ten positions adds about 40 ms to the median;
the window adds 70 to 80 ms to a batch of 25 or 50. Against the two-second `Batcher` window neither
decides anything. `LOAD.md` measured 515 ms for 25 on longer text; the difference is the text, and
two runs days apart are not a trend.

## 6. The request limit, and what happens over it

TypeSafe documents **64k tokens per request**, the state and every question together, and 32k for
the state plus the longest question (docs.typesafe.ai, Models page, read 2026-09-27). A request over
it comes back `400 max_tokens_exceeded`. `ModerationService` catches it as any other `TypeSafeError`
and fails open: every message in the batch gets `action="none", reason="error_open"` and none is
moderated.

Measured through the service, topic on:

| batch | window | accepted | input tokens |
|---|---|---|---|
| 50 | 10 | 6 of 6 | largest 63,587 |
| 50 | 20 | 3 of 6 | largest accepted 62,705 |
| 60 | 0 | 1 of 1 | 60,348 |
| 60 | 10 | 1 of 1 | 55,544 (11 skipped by the pre-filter) |
| 70 | 0 | 1 of 1 | 61,699 (6 skipped) |
| 70 | 10 | 0 of 1 | rejected |
| 100 | 0 | 0 of 1 | rejected |
| 100 | 10 | 0 of 1 | rejected |

Three things follow, and none is this issue's to fix:

- **`MAX_BATCH` is 100, and a request of 100 chat messages does not fit even with no window.** At
  about 950 tokens a position the ceiling is about 65 positions. A server that receives more than
  that in one two-second window, which is what a raid looks like, has the whole batch fail open. The
  limit that matters is the token budget, and `_gate_and_judge` splits by message count.
- **A batch of 50 at the shipped window of ten reached 63,587 of 64k** on 48-character comments.
  Longer messages, or longer context, which `assemble` allows up to 600 estimated tokens per message,
  put a full batch of 50 over.
- **A window of twenty is ruled out near 50 messages per request** by the limit alone, before any
  argument about its value.

## 7. Output tokens

Every request reported output tokens: 781,602 in all, 12.3% of input. TypeSafe publishes a price
for input tokens and none for output, and every cost in this repository, this one included, prices
input only. If output is billed, every figure here is low by 12.3% times the ratio of the output
price to the input price.

## 8. A month

Model cost at list price, topic on; a month is this times the messages judged.

| window | batch | $ per 1K judged | 100k a month | 300k a month | 2M a month |
|---|---|---|---|---|---|
| 0 | 1 | $0.091 | $9.11 | $27.32 | $182.11 |
| 0 | 25 | $0.042 | $4.20 | $12.60 | $84.00 |
| 10 | 1 | $0.412 | $41.22 | $123.67 | $824.45 |
| 10 | 10 | $0.063 | $6.29 | $18.88 | $125.88 |
| 10 | 25 | $0.054 | $5.43 | $16.30 | $108.69 |
| 10 | 50 | $0.051 | $5.05 | $15.15 | $101.01 |

**Which row a server pays is set by its traffic, not by its volume.** `Batcher` collects one tenant's
messages for two seconds. A server at 300k messages a month spread over eight busy hours a day
receives about 0.35 a second, so a batch holds the first message and 0.7 more on average, and most
batches are padded. That is arithmetic on an assumed traffic shape, not a measurement. Nobody has
measured the batch-size distribution on a real server, and it decides whether the multiplier to
price with is 1.3 or 4.5.

## 9. Recommendation for JEV-19

- **The context field is worth keeping on cost grounds.** At a window of ten it costs 15% for a
  message alone and 22% to 37% in a batch. Whether it buys anything is JEV-18's question.
- **Do not raise the window above ten.** Twenty costs 56% in a batch against 29% to 37% at ten, buys
  nothing extra for a message alone because padding is capped at ten positions, and does not fit in
  a batch of 50.
- **The number to decide is padding, not the window.** Padding a message alone to ten positions
  costs 4.5 times judging it without context and is 92% to 96% of what the window costs a quiet
  channel. Padding to five costs 2.4 times, for 32.0% spam recall against 38.7% at ten
  (`BATCH_EFFECT.md` section 7). That trade is about quiet servers only: a busy one fills its own
  batch and pays 1.2 to 1.4 times.
- **Price on the batch-size distribution, which is unmeasured.** Until it is measured, the defensible
  multiplier for a small server is the batch-of-one row, 4.5x, and for a busy one the batch-of-25
  row, 1.3x.
- **Split batches by tokens, not by count**, whatever JEV-19 decides. Section 6 is a fail-open path
  that a raid reaches today.

## What this does not say

- **It is not Discord.** Comments under a video are short and unthreaded. Chat of the same length
  costs the same; chat twice as long roughly doubles the 29 tokens per context entry and moves the
  per-position cost little.
- **It does not measure value.** Nothing here says whether a window of ten moderates better than
  five. That is JEV-18.
- **It does not credit the cache.** A spam wave in near-identical windows shares a cache key and
  costs nothing after the first request; how often that happens in real traffic is not known.
- **One key, one region, one afternoon.** Token counts do not depend on any of those; latency does.

## Reproduce

Needs `TYPESAFE_API_KEY`, `PYTHONUTF8=1`, and the five UCI CSVs in `benchmark/data/youtube_spam/`
(git-ignored; the same files `prepare.py` reads).

    python -m benchmark.context_cost.run ask       # paid, about $0.27, resumable, prints the running cost
    python -m benchmark.context_cost.run limit     # paid, under a cent; rejected requests cost nothing
    python -m benchmark.context_cost.run report    # free, every table here
