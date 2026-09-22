# Does a message's score depend on its batch-mates? Spam and harassment.

JEV-56, Urgent, Bug. <https://linear.app/jevmod/issue/JEV-56>

## Objective

Measure, for `spam` and `harassment`, the thing `benchmark/ai_detect/REPORT2.md` measured for
`ai_generated`: whether the same message scores differently depending on which other 24 messages
share its request.

## Why this one first

`ai_generated` was never shipped, so its instability cost nothing. `spam` and `harassment` are the
two categories whose default action can be `delete`. If a score moves with the company a message
keeps, then:

- the site publishes thresholds to two decimal places that do not mean what they appear to mean;
- the dashboard lets an owner tune them at that precision;
- labelling five thousand messages (JEV-11) against a moving score is labelling noise, which is why
  JEV-56 is ranked ahead of it.

REPORT2 already stated the expectation, without measuring it: *"It is a property of the batching
contract, not of the category, so it applies to spam, scam and harassment too, where it is
unmeasured and where the action is delete rather than flag."* An expectation written down is not a
measurement. This task turns it into one, in whichever direction it goes.

There is weak evidence on the other side, gathered on 2026-09-22 while building `judge_copy.py` and
again while dogfooding it: one question asked alone scored 0.80, and in company with four others
0.81 / 0.81 / 0.76; and changing one sentence of a text moved one question from 0.51 to 0.88 while
the other four stayed flat within 0.03. Both are single texts with a handful of questions, not the
25-message production batch. They are a reason to measure rather than assume, not a result.

## What counts as an answer

Not a mean. `REPORT2.md`'s `ALL` row drifted +0.001 because per-stratum drifts had opposite signs
and cancelled, while the false-positive rate for wiki-style text went 0.300 to 0.667 underneath it.
The number that decides this issue is **how many messages cross their shipping threshold between
two conditions**, reported per side, never pooled.

Shipping thresholds, from `DEFAULT_THRESHOLDS` in `jevmod/core/policy.py`: spam 0.85, harassment
0.75.

## Design

Three conditions over the same messages, 25 per request, the production batching contract:

| condition | what it is | what it controls for |
|---|---|---|
| `pure` | every message in the batch is from the same side | the baseline |
| `pure2` | identical composition, asked a second time | run-to-run noise, the control's control |
| `mixed` | the batch is about half the other side | the effect under test |

Without `pure2` no drift is attributable: REPORT2 found 17 of 156 items flipping across the
threshold with nothing changed at all, so a composition effect only exists if it is bigger than
that.

Both sides are measured. A clean message drifting up into `delete` and a spam message drifting down
out of it are different failures and neither is visible in the other's number.

Pools, from `benchmark/data/items.jsonl` (2,531 labelled: 1,658 clean, 319 harassment, 250 spam):

- 150 `spam`, 150 `harassment`
- 150 clean paired with spam, a separate 150 clean paired with harassment, so no clean message is
  reused across the two arms

1,800 judgements, 72 requests. Cost is measured by a pilot before the full run, not estimated.

## Constraints that the harness has to respect

1. **The 24-hour cache would silently answer the whole experiment.** `Judge.cache` is keyed by
   normalised text plus topic plus category set (`judge.py:_key`). Asking the same text twice would
   return `reason="cache"` and a drift of exactly zero, which looks like a clean result and is not
   one. Every run constructs its `Judge` with `cache_ttl_s=0`, and the harness asserts that no
   verdict comes back with `reason="cache"`.
2. **The pre-filter drops messages before Jev sees them.** Under eight alphanumerics without a link
   returns `judged=False` and no scores. Those items are excluded from the pools up front and the
   count is reported, rather than being discovered as holes in the results.
3. **The question set must be production's.** Asking only `spam` and `harassment` would be a
   different prompt from the one the product sends. The runs ask the same categories
   `benchmark/run_jevmod.py` asks, so the number transfers.
4. **Ordering must be deterministic.** Seeded shuffles, written down, so the run can be repeated.

## Tasks

- [ ] T1. `benchmark/batch_effect.py`: pools, seeded batch construction for the three conditions,
      resumable JSONL output with the id, condition, scores and per-batch token count.
- [ ] T2. Pilot: one batch per condition. Confirm no cache hits, no pre-filtered items, and measure
      the token cost before spending the rest.
- [ ] T3. The full run, all three conditions.
- [ ] T4. The analysis: per side and per category, mean drift, and the threshold-crossing counts
      that actually answer the question. Rerun drift beside composition drift in every table.
- [ ] T5. `benchmark/BATCH_EFFECT.md`: the report, with the recommendation the numbers support and
      the reproduce commands.
- [ ] T6. Whatever the numbers say, carry it back: JEV-56 closed or specified, and the claims about
      threshold precision on the site checked against the result.

## Acceptance

- Every table reports `pure` against `pure2` against `mixed`, never a composition drift without its
  noise floor beside it.
- Threshold-crossing counts are per side. No pooled row stands alone.
- The report states what it did not measure, in the shape REPORT2 and REPORT3 do.
- The run reproduces from the documented commands.

## Progress

Nothing run yet. Next: T1.
