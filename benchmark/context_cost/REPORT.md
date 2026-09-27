# What the conversation window costs per judged message

JEV-67. Run on 2026-09-27 with `benchmark/context_cost/run.py` against the live API, one machine, one
key. Raw rows in `results/raw.jsonl` (one line per position and arm, with every request's reported
tokens and wall time) and `results/limit.jsonl` (the request-limit probe, with every rejected call's
error). The acceptance criteria are in `odd/tasks/context-cost.md`, written before the run but
committed with its results, so git cannot show the order; two of them were missed, and section 1
says which.

**The run cost $0.28**: 6,735,193 input tokens billed at TypeSafe's list price of $42 per billion
input tokens (typesafe.ai, read 2026-09-27). That is 6,380,011 for the main run, of which 119,856
were a batch-of-10 position the seeded draw picked twice and that `report` counts once, and 177,591
for each of two runs of the limit probe. A rejected request returned no usage; whether TypeSafe
bills it is not observable from here.

## The short answer

1. **The window is cheap on a busy channel and expensive on a quiet one, and the difference is
   padding, not context.** With the shipped window of ten and a real channel topic, a judged message
   costs 1.29 times the no-window request in batches of 25 and 1.35 times in batches of 10. A message
   judged alone costs **4.53 times**, because the service pads a batch under ten with the window's
   messages and asks every category about each of them. Padding is 92% to 96% of what the window
   costs a message judged alone; the `context` field itself costs that message 15%.
2. **What drives the bill is positions, not text.** On window-0 requests, tokens fit
   **256 per request plus 928 to 955 per position** (least squares, 50 requests per topic arm), most
   of it the seven category questions asked about each position. A message of context attached to a
   judged message costs about 29 tokens. Ten of them are under a third of a position.
3. **The topic costs 2% to 3%**, at every window and batch size. It is not a cost decision.
4. **A window of twenty does not fit.** Three of six batches of 50 with twenty messages of context
   came back `400 max_tokens_exceeded` from TypeSafe (observed, section 6), and a rejected request
   fails open: nothing in the batch is moderated. The same error rejects a batch of 100 with no
   window at all, and the service allows 100.
5. **Latency moves less than cost.** Median request time at a window of ten is 5% to 20% above no
   window: 250 to 291 ms for a message alone, 356 to 429 ms for 25.

## 1. What was measured

**The path is production's.** Each request goes through a fresh `ModerationService.moderate` on an
in-memory `Store`, with a `ConversationBuffer` holding the N comments posted before the batch in the
same stream. The service attaches the window to every message through `assemble`, pads a batch
under ten from the same window (`PAD_BATCH` on, as shipped), and `Judge` sends the request with the
seven categories that ship enabled. The only addition is a wrapper around the real TypeSafe client
that records the input and output tokens the API reports, the wall time of the call, and the class,
status and body of any exception. Nothing is estimated from characters. The cache is off
(`cache_ttl_s=0`), so every figure is a request that was actually sent; a production cache hit
would cost nothing and is not credited here.

**The stream** is the UCI YouTube Spam Collection (archive.ics.uci.edu, dataset 380): five videos,
1,956 comments, each video sorted by posting date and treated as one channel. Median length 48
characters, the shortest real text in the benchmark and the nearest thing to chat it has. About half
of it is spam, which does not change a token count. One file, Eminem, has 245 of 448 comments with
no date; they are kept in file order after the dated ones, and 5 of the 51 positions read their batch
or their history from that tail. Token counts do not depend on order; the history those five see is
less like a real conversation.

**The arms are paired.** For each batch size the positions were drawn once from a fixed seed (30
requests of 1, 10 of 10, 6 of 25, 6 of 50), and every window and topic arm judged exactly the same
messages at each position. `report` checks both that every arm sent the same ids and that every arm
judged the same number of messages at every position it was accepted at; both hold. The draw samples
with replacement and picked one batch-of-10 position twice; `report` keeps the first run of it, so
batch 10 has nine distinct positions. The arms ran in a shuffled order per position, so no arm owns a
time of day.

**Per judged message.** Of the 4,350 messages in accepted requests, 303 (7.0%) were skipped by the
pre-filter as too short and cost nothing; every figure divides by the 4,047 that were judged, as
`LOAD.md` did. A further 300 messages were in the six batch-of-50 window-20 requests that were
rejected (section 6); they are left out of both sides.

**Acceptance.** Every configuration was to have at least
30 judged messages and 4 requests. Two did not: every batch-of-1 arm has 29 (one of the 30 drawn
comments is too short to judge, in every arm), and the two batch-of-50 window-20 arms have 3
accepted requests, because the other three were rejected. The token counts are the API's; the
arms are paired; the cost is stated.

**The topic** is 138 characters, one plausible channel rule; no distribution of real topic lengths
was measured. With no topic,
`Judge` sends "general chat" at every position, so the topic arm measures the difference a real
topic makes, not the difference between something and nothing.

## 2. Input tokens per judged message

Multiplier: summed tokens of the arm over summed tokens of the window-0 arm of the same batch size and
topic, on the positions where both were accepted. The range is the smallest and largest per-request
ratio.

| batch | window | topic | context kept | positions per request | tokens per judged msg | x vs window 0 | per-request range | $ per 1K judged |
|---|---|---|---|---|---|---|---|---|
| 1 | 0 | yes | 0.0 | 2.0 | 2,168 | 1.00x | | $0.091 |
| 1 | 5 | yes | 4.9 | 5.0 | 5,169 | 2.38x | 1.90 to 2.60 | $0.217 |
| 1 | 10 | yes | 9.9 | 9.7 | 9,815 | **4.53x** | 2.82 to 4.91 | $0.412 |
| 1 | 20 | yes | 19.5 | 10.0 | 10,389 | 4.79x | 4.18 to 5.14 | $0.436 |
| 10 | 0 | yes | 0.0 | 10.4 | 1,093 | 1.00x | | $0.046 |
| 10 | 5 | yes | 5.0 | 10.4 | 1,275 | 1.17x | 1.06 to 1.31 | $0.054 |
| 10 | 10 | yes | 9.8 | 10.4 | 1,475 | **1.35x** | 1.16 to 1.59 | $0.062 |
| 10 | 20 | yes | 18.0 | 10.4 | 1,691 | 1.55x | 1.35 to 1.64 | $0.071 |
| 25 | 0 | yes | 0.0 | 25.2 | 1,000 | 1.00x | | $0.042 |
| 25 | 5 | yes | 5.0 | 25.2 | 1,155 | 1.16x | 1.08 to 1.21 | $0.049 |
| 25 | 10 | yes | 10.0 | 25.2 | 1,294 | **1.29x** | 1.16 to 1.38 | $0.054 |
| 25 | 20 | yes | 20.0 | 25.2 | 1,565 | 1.56x | 1.33 to 1.76 | $0.066 |
| 50 | 0 | yes | 0.0 | 46.3 | 982 | 1.00x | | $0.041 |
| 50 | 5 | yes | 4.9 | 46.3 | 1,092 | 1.11x | 1.08 to 1.13 | $0.046 |
| 50 | 10 | yes | 9.8 | 46.3 | 1,202 | **1.22x** | 1.15 to 1.29 | $0.051 |
| 50 | 20 | yes | 20.0 | 43.7 | 1,340 | 1.38x | 1.35 to 1.41, 3 of 6 rejected | $0.056 |

The rows without a topic are 2% to 3% lower in tokens and their multipliers are within 0.02 of these;
all 32 are printed by `report`. "Positions per request" for 10, 25 and 50 is the batch plus the lead
filler at `m0`, less the messages the pre-filter skipped. "Context kept" below the window is mostly
`assemble` dropping the oldest entries once the window passes its 600 estimated tokens (at batch 10,
window 20), and occasionally `exclude` dropping a comment identical to the one being judged, which a
spam stream has.

**The batch-of-50, window-20 row is priced on the three requests that were accepted**, and its
multiplier is paired on those three positions only. The three rejected were the larger ones: at
window 10 the same three positions already sent 56,525 to 63,587 tokens.

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
filler at `m0` and the message. With padding off the request keeps that filler. **With padding off,
the window of ten costs 15% more (2,431 against 2,114). With padding on, 352% more**, on this
stream. Padding positions carry text, so on longer chat the padded request grows faster than the
baseline and the multiplier rises above 4.53x. The window has
two costs and they are not the same size:

- **The `context` field** on the judged message: about 29 tokens per entry, so ten entries are about
  290 tokens against a position's 930 to 955.
- **Padding.** `_judge_batch` hands the window to `Judge` as padding when the batch is under ten, and
  `Judge` puts it in positions up to `m9` and asks every category about each. That is eight more
  positions.

**What padding buys is not measured.** `BATCH_EFFECT.md` section 9 corrected its own section 7: the
recall a message alone lost was mostly the cost of sitting at `m0`, not of a small batch. It measured
17.3% spam recall for a message alone at `m0`, 26.7% with a filler at `m0` and the message behind it
(this run's window-0 and padding-off request), 29.3% with the filler and eight messages from the same
spam pool behind it, and 38.7% in a real batch of ten varied messages. None of those is production's
padding: `Judge` puts the channel's own oldest window message at `m0` and eight real messages of the
channel's history behind it, which is closer to the 38.7% condition than to the 29.3% one, and the
26.7% arm has no runner or results in the repository. So padding costs 4.5 times the filler-only
request, and what it buys over the filler lies somewhere between 2.6 and 12 points of spam recall
on evidence that does not isolate it. That is the measurement JEV-19 needs before it can decide
padding on cost.

Padding is capped at ten positions, which is why twenty messages of window cost a message alone
barely more than ten: 4.79x against 4.53x.

## 4. Per position, and per context entry

A least-squares line through the 50 window-0 requests of each topic arm gives **256 tokens per
request plus 928 per position** without a topic and 955 with one. That is why the per-position cost
read off a single batch size falls as the batch grows: 1,057 at two positions, 933 at 25 and 50. The
seven questions are sent once per position, so the question text, not the message, is most of every
position. From the batch-of-25 arms, each message of context attached to each judged message adds
**29 tokens** on this stream.

On text of this length a request costs close to

    tokens = 256 + 930 x positions + 29 x (context entries summed over the judged messages)

and only the last term, and a little of the second, grows with message length.

## 5. Latency

Client wall time of one `system_one` call, topic on. The SDK retries inside that call and retries are
not recorded, so a retried call is one slow call here. Six to thirty requests per cell: enough for a
median, not for a tail; with six requests the p95 is the maximum. The run's first request, 926 ms,
was a cold connection and is left in its cell (batch 1, window 20, no topic).

| batch | window | requests | p50 ms | p95 ms |
|---|---|---|---|---|
| 1 | 0 | 29 | 250 | 389 |
| 1 | 10 | 29 | 291 | 360 |
| 1 | 20 | 29 | 289 | 404 |
| 10 | 0 | 9 | 302 | 350 |
| 10 | 10 | 9 | 316 | 374 |
| 25 | 0 | 6 | 356 | 389 |
| 25 | 10 | 6 | 429 | 464 |
| 50 | 0 | 6 | 480 | 540 |
| 50 | 10 | 6 | 562 | 689 |

Every cell is in `report`. Padding a message alone to ten positions adds about 40 ms to the median;
paired on the same positions, the window of ten adds a median 54 to 61 ms to a batch of 25 and 71 to
75 ms to a batch of 50. Batch sizes ran one after another, so comparing latency across batch sizes is
confounded with time of day; comparing windows is not, because the arms were shuffled per position. Against the two-second `Batcher` window neither
decides anything. `LOAD.md` measured 515 ms for 25 on longer text; the difference is the text, and
two runs days apart are not a trend.

## 6. The request limit, and what happens over it

TypeSafe documents **64k tokens per request**, the state and every question together (docs.typesafe.ai,
Models page, read 2026-09-27). `limit` sends batches of 60, 70 and 100 at windows 0 and 10 through the
service, and replays the three batch-of-50 window-20 requests that failed in the main run, recording
each exception. Topic on:

| batch | window | accepted | input tokens | what came back |
|---|---|---|---|---|
| 50 | 10 | 6 of 6 (main run) | largest 63,587 | |
| 50 | 20 | 3 of 6 (main run) | largest accepted 62,705 | the three others, replayed with the topic: `400 max_tokens_exceeded`; the no-topic failures were not replayed and are the same requests with about 1,350 fewer tokens, inferred |
| 60 | 0 | 1 of 1 | 60,348 | |
| 60 | 10 | 1 of 1 | 55,544 (11 skipped by the pre-filter) | |
| 70 | 0 | 1 of 1 | 61,699 (6 skipped) | |
| 70 | 10 | 0 of 1 | | `400 max_tokens_exceeded` |
| 100 | 0 | 0 of 1 | | `400 max_tokens_exceeded` |
| 100 | 10 | 0 of 1 | | `400 max_tokens_exceeded` |

`ModerationService` catches the error as any other `TypeSafeError` and fails open: every message in
the batch gets `action="none", reason="error_open"` and none is moderated. The probe is one request
per cell above 50, so it shows where the edge is, not how often a real batch crosses it. Three things
follow, and none is this issue's to fix:

- **`MAX_BATCH` is 100, and a request of 100 chat messages does not fit even with no window.** At
  about 930 tokens a position the ceiling is about 68 positions. A server that receives more than
  that in one two-second window, which is what a raid looks like, has the whole batch fail open. The
  limit that matters is the token budget, and `_gate_and_judge` splits by message count.
- **A batch of 50 at the shipped window of ten reached 63,587 of 64k** on 48-character comments.
  Longer messages, or longer context, which `assemble` allows up to 600 estimated tokens per message,
  put a full batch of 50 over.
- **A window of twenty is ruled out near 50 messages per request** by the limit alone, before any
  argument about its value.

## 7. Output tokens

Every accepted request reported output tokens: 769,722 in all, 12.3% of input. TypeSafe publishes a
price for input tokens and none for output, and every cost in this repository, this one included,
prices input only. If output is billed, every figure here is low by 12.3% times the ratio of the
output price to the input price.

## 8. A month

Model cost at list price, topic on; a month is this times the messages judged.

| window | batch | $ per 1K judged | 100k a month | 300k a month | 2M a month |
|---|---|---|---|---|---|
| 0 | 1 | $0.091 | $9.11 | $27.32 | $182.11 |
| 0 | 25 | $0.042 | $4.20 | $12.60 | $84.00 |
| 10 | 1 | $0.412 | $41.22 | $123.67 | $824.45 |
| 10 | 1, padding off | $0.105 | $10.50 | $31.50 | $210.01 |
| 10 | 10 | $0.062 | $6.20 | $18.59 | $123.94 |
| 10 | 25 | $0.054 | $5.43 | $16.30 | $108.69 |
| 10 | 50 | $0.051 | $5.05 | $15.15 | $101.01 |

The padding-off row is the no-topic arm (2,431 tokens, the only padding-off arm run) raised by the
topic's 3%.

**Which row a server pays is set by its traffic, not by its volume.** `Batcher` collects one tenant's
messages for two seconds, and padding comes from a buffer of the last fifteen minutes. The 4.53x row
is a ceiling on this stream: one message in the batch and a full window behind it. A channel quiet enough to have
nothing in the last fifteen minutes has nothing to pad with and pays close to 1.0x; this run put the
history in a moment before each request, so it never measured that case.

Between the two, a worked example on an assumed traffic shape, not a measurement: a server at 300k
messages a month over eight busy hours a day receives about 0.35 a second, so a two-second batch
holds 1 + Poisson(0.7) messages, 1.7 on average, almost always under ten and so padded to about ten
positions. With a full window, section 4's formula gives about 5,900 tokens per judged message
against 1,630 without the window, **about 3.6x**. Nobody has measured the batch-size distribution or
how full the window is on a real server, and those two decide whether the multiplier to price with
is 1.3, 3.6 or 4.5.

## 9. Recommendation for JEV-19

- **The context field is worth keeping on cost grounds.** At a window of ten it costs 15% for a
  message alone and 22% to 35% in a batch. Whether it buys anything is JEV-18's question.
- **Do not raise the window above ten.** Twenty costs 55% to 56% in a batch of 10 or 25 against 29%
  to 35% at ten, buys nothing extra for a message alone because padding is capped at ten positions,
  and does not fit in a batch of 50.
- **The number to decide is padding, not the window.** Padding a message alone to ten positions
  costs 4.5 times the filler-only request and 92% to 96% of what the window costs a quiet channel,
  for a recall gain over the filler alone that no run has isolated (section 3). Dropping the padding
  and keeping the filler puts a quiet channel at 1.15x. Whether that trade is worth it needs one
  run: the same spam messages judged behind the filler alone and behind production's real-history
  padding. Until then `JEVMOD_PAD_BATCH` stays as shipped.
- **Price on the batch-size distribution, which is unmeasured.** Until it is measured, with padding
  as shipped, price a small server between the worked example and the ceiling, 3.6x to 4.5x, and a
  busy one on the batch-of-25 row, 1.3x.
- **Split batches by tokens, not by count**, whatever JEV-19 decides. Section 6 is a fail-open path
  that a raid reaches today.

## What this does not say

- **It is not Discord.** Comments under a video are short and unthreaded. Chat of the same length
  costs about the same. The 29 tokens per context entry were measured on the entries `assemble`
  kept at batch 25, window 10: 68 characters on average, median 44. Across all arms, billed tokens
  per entry fit about 1.08 times `assemble`'s estimate (characters / 4) plus 9.4 for each entry's
  JSON, so longer chat costs more per entry, roughly in proportion to its length, and moves the
  per-position cost little.
- **It does not measure value.** Nothing here says whether a window of ten moderates better than
  five. That is JEV-18.
- **It does not measure user history or community state**, the other two parts JEV-19 budgets. The
  engine does not send them yet.
- **It does not credit the cache.** A spam wave in near-identical windows shares a cache key and
  costs nothing after the first request; how often that happens in real traffic is not known.
- **Positions are not independent.** 30 pairs of positions overlap in their batch or the history
  they read at a window of ten, 42 counting the window of twenty, so the effective sample behind each range is smaller than its request count. The ratios
  are paired and are not affected.
- **One key, one region, one afternoon.** Token counts do not depend on any of those; latency does.

## Reproduce

Needs `TYPESAFE_API_KEY`, `PYTHONUTF8=1`, and the five UCI CSVs in `benchmark/data/youtube_spam/`
(git-ignored; the same files `prepare.py` reads).

    python -m benchmark.context_cost.run ask       # paid, about $0.27, resumable, prints the running cost
    python -m benchmark.context_cost.run limit     # paid, under a cent; rewrites limit.jsonl
    python -m benchmark.context_cost.run report    # free, every table here
