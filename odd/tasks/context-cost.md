# What the conversation window costs per judged message

JEV-67, Urgent, blocking JEV-66 (tiers and price). <https://linear.app/jevmod/issue/JEV-67>

## Objective

Measure how input tokens, cost and latency per judged message move with the conversation window
(0, 5, 10 and 20 prior messages), with and without a channel topic, at batch sizes 1, 10, 25 and 50,
through the engine's real path: `ModerationService.moderate`, which fills `Message.context` from
`ConversationBuffer` through `assemble` and pads small batches, and `Judge`, which sends the request.
Produce the multiplier against the no-window baseline, cost per 1,000 messages for every
configuration, and monthly cost at 100k, 300k and 2M messages, so JEV-66 can price and JEV-19 can
decide how much context is worth.

## What exists

- `benchmark/LOAD.md` (JEV-6): 1,305 input tokens per message without the window and 1,842 with it,
  batches of 25, on `data/items.jsonl`. Those rows are prompts and comments, median 176 to 380
  characters for two of the three sources, not chat.
- `odd/tasks/pad-small-batches.md`: padding a batch of one to ten costs about eight times.
- Nobody has measured the window at more than one batch size, at 5 or 20, or with a topic.

## Plan

1. `benchmark/context_cost/run.py`: the stream is the UCI YouTube comment sets, each video sorted by
   date as one channel (median about 50 characters, the shortest real text in the benchmark and the
   nearest to chat). For every batch size, fixed positions in the streams are drawn once with a seed;
   each position is judged under all eight window and topic arms, so the arms are paired on identical
   judged messages. Arms are interleaved in a shuffled order per position so time of day does not
   load one arm.
2. Every request goes through a fresh `ModerationService` on a scratch SQLite, whose buffer holds the
   N messages that came before the batch in the same stream. The real client is wrapped only to record
   input tokens, output tokens and wall time per request.
3. One decomposition arm: batch of one with padding off, so the window's two costs (the `context`
   field on the message, and the padding positions) can be told apart.
4. `report` prints every table from the jsonl, free.

## Acceptance, written before the run

- Every one of the 32 configurations has at least 30 judged messages and 4 requests, and the token
  count is the one the API returned, not an estimate.
- Arms are paired: the same judged message ids in every window/topic arm of a batch size.
- Cost stated for the run itself.
- The report says what the stream is not (not Discord, not threaded) and what latency with four to
  thirty requests per cell can and cannot support.
- A recommendation JEV-19 and JEV-66 can use, stated with the number that drives it.

## Checks

`ruff check benchmark/context_cost`; the runner's `report` reproduces every table in REPORT.md.
TDD: off (a measurement, no behaviour changes in `jevmod/`).

## Evidence

(filled after the run)
