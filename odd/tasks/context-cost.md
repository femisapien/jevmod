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

- Run 2026-09-27, $0.28 in all (6,735,193 input tokens: main run 6,380,011, limit probe 177,591 twice).
  Tables in `benchmark/context_cost/REPORT.md`, reproduced by `run.py report` from `results/*.jsonl`.
- Multiplier at the shipped window of ten, topic on: 4.53x batch 1 (1.15x with padding off), 1.35x
  batch 10, 1.29x batch 25, 1.22x batch 50. Padding is 92% to 96% of the batch-of-1 cost.
- Acceptance: token counts from the API, arms paired (checked by `report`), cost stated. Missed: batch-1
  arms have 29 judged messages, not 30; batch-50 window-20 arms have 3 accepted requests, not 4, because
  the other three were rejected with `400 max_tokens_exceeded` (observed in `limit.jsonl`).
- Red-team review, round 1 (fresh reviewer, no context): no arithmetic errors; CONFIRMED and fixed: the
  recommendation cited `BATCH_EFFECT.md` section 7 recall figures that section 9 corrected (padding buys
  2.6 points, not 21); 300 rejected messages had been counted as pre-filter skips (7.0%, not 12.7%);
  acceptance misses not stated; rejection cause inferred, not recorded (now captured and observed);
  one batch-10 position drawn twice (deduplicated in `report`); undated Eminem tail not disclosed;
  "context kept" misattributed to `exclude`; batch-50 window-20 multiplier not paired; small text
  errors; "retries included" unsupported; per-position figure mixed a fixed per-request cost (fitted:
  256 + 928 to 955 per position).
- `ruff check benchmark/context_cost`: clean.
- Red-team round 2 (fresh reviewer): accounting held. CONFIRMED and fixed: the padding recall figure
  compared filler-only against filler plus same-pool spam, not production's real-history padding, so
  what padding buys is now stated as unmeasured and no padding change is recommended; 4.53x is a
  ceiling (full window, one message), with a worked 3.6x on the assumed traffic and about 1.0x for a
  channel with an empty window; no-topic batch-50 window-20 failures not replayed (said so); latency
  deltas now paired. PLAUSIBLE, addressed in text: overlapping positions, topic length unsourced,
  acceptance order not provable from git, per-entry cost measured on 95-character mean entries.
