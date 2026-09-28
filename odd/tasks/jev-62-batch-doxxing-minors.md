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
- T4, T5 done. No composition effect survives, on decisions or on scores, once the sign test runs on
  requests as well as templates. Largest: doxxing positives -0.011 among hard negatives, 9 of 12
  requests, p = 0.15. Alone, `doxxing` point estimates -5.7 pts recall and +3.3 pts FPR, not
  significant, two templates. **No production change**.
- Found on the way and fixed before publishing: the doxxing items are 16 templates per side, so
  item-level tests overstated four cells. The sign test now counts templates and the bootstrap
  resamples them.
- `BATCH_EFFECT.md` section 4 and the JEV-56 task file point at the result.
- T6 round 1 (PR #8): CONFIRMED and fixed: the survivor depended on `reshuffled` as reference (now the
  mean of `pure` and `reshuffled`, plus a membership control row); within-request correlation (control
  rows as the empirical null); five duplicate `minors` texts (later id dropped); four overstatements in
  the report (doxxing decision cells near-empty, rule retirement, alone figures, "four cells").
  PLAUSIBLE, recorded: `pure2` is a flattering floor (no conclusion depends on it); `diluted` changes
  length as well as composition for `minors`.
- T6 round 2: CONFIRMED and fixed: the round-1 survivor (doxxing positives, 15/16 templates) was the
  unit of analysis, 9/12 requests p = 0.15, so the sign test now runs on requests too and the larger p
  is corrected; the fictional-data test was loose (now: no 4+ digit run outside reserved ranges);
  `run.py` did not check stored requests against the design (now refuses); "15 of 16 at 0.12 or less"
  held only for the averaged reference. PLAUSIBLE, recorded in REPORT section 5: order of conditions,
  request size in `minors`, length/register in `diluted`, plates in real UK format.
