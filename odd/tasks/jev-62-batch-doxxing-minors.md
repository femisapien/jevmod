# Does `doxxing` or `minors` depend on the batch? JEV-62

<https://linear.app/jevmod/issue/JEV-62>. Follows `odd/tasks/batch-composition-spam-harassment.md` (JEV-56).

## Objective

JEV-56 and REPORT2 left a rule written to explain two data points: questions about the author or the
world (`ai_generated`) use the neighbours as evidence and move with batch composition; questions about
the text (`spam`, `harassment`) move with membership and not with composition. The rule predicts
`doxxing` and `minors` are composition-sensitive. Test it, at the shipped thresholds (0.80, 0.70),
with recall and false-positive movement and intervals, and decide whether production needs a change.

## What exists

- `benchmark/batch_effect.py`: the JEV-56 harness, McNemar against a `pure2` floor, Holm.
- `benchmark/data/items.jsonl`: 85 `minors` rows (OpenAI moderation eval, S3), 170 `nsfw` rows without
  `minors`, **no `doxxing` rows**.
- Production puts a filler at `m0` (JEV-57), so "alone" means filler plus message.

## Plan

- T1. Doxxing pools: 150 synthetic positives and 150 synthetic hard negatives from templates covering
  every clause of the category's `true` and `false` criteria, fictional data only (555-01xx, Ofcom
  drama range, RFC 2606 domains). `benchmark/batch_doxxing_minors/doxxing_items.py`.
- T2. Minors pools: all 85 `minors` rows against 85 adult `nsfw` rows. No text is written into the
  folder or the report; results hold ids and scores. No new material of this kind is created or
  fetched.
- T3. Runner with six conditions: `pure`, `pure2`, `reshuffled`, `mixed_shuffled`, `diluted` (5 targets
  among 20 neutral chat comments), `single`. Pilot, then the full run; resumable, a batch is written
  whole or not at all.
- T4. Analysis: recall and FPR with Wilson intervals, precision at 1:1 with bootstrap intervals,
  McNemar against `pure2` with Holm, and the rule's own tests (`mixed_shuffled`, `diluted`, `single`
  against `reshuffled`) as a sign test on paired scores plus the paired change in the share over the
  line with a bootstrap interval, Holm over that family.
- T5. `benchmark/batch_doxxing_minors/REPORT.md`, and a production change only if the data asks for one.
- T6. Red team, zero context, up to three rounds.

## Acceptance

- Every composition contrast is against `reshuffled`, so membership is held and composition is the only
  difference; never against `pure`.
- Per side, never pooled. Intervals on every recall and FPR.
- The report says what the synthetic doxxing set cannot show.
- The run reproduces from the documented commands; the raw jsonl is committed.

## Progress

- T1 to T3 done. Pilot, one request per condition: $0.0052, no cache hits, no unjudged rows.
- Full run: 643 requests, 5.40M input tokens, $0.227 including the pilot. 2,820 recorded rows.
- T4, T5 done. No composition effect on any decision in eight cells. One score effect survives Holm
  (`minors` on adult sexual text, +0.016 with `minors` neighbours, and +0.019 among neutral chat,
  which the rule does not predict). Alone, `doxxing` loses 5.3 points of recall and gains 3.3 of false
  positives, two templates. **No production change**: isolation would make doxxing worse and nothing
  argues for a threshold move.
- Found on the way and fixed before publishing: the doxxing items are 16 templates per side, so
  item-level tests overstated four cells. The sign test now counts templates and the bootstrap
  resamples them.
- `BATCH_EFFECT.md` section 4 and the JEV-56 task file point at the result.
