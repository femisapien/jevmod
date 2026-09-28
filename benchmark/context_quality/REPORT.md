# What the conversation window buys in verdicts

JEV-18. Run on 2026-09-28 with `benchmark/context_quality/run.py` against the live API, one machine, one
key. Raw rows in `results/raw.jsonl` (one line per row, arm and repeat, every category's score, billed
tokens), the blind relabelling in `results/blind_labels.jsonl`. Every table here is printed by
`python -m benchmark.context_quality.run report`.

**The run cost $0.30**: 7,227,276 input tokens at $42 per billion (the list price every benchmark here
uses), 2,240 judgements. The pre-registered red-team check of a spam threshold (section 5) added two passes
of `tests/test_redteam.py`, about a hundred calls each, and the repeat probe six requests; together under
two cents.

## The short answer

1. **On rows where the earlier messages decide what the last one means, the window helps.** Pooled over
   all seven categories, recall at the shipped thresholds goes from 37% to 64% and the false-positive
   rate from 14% to 6%; 50 rows are right only with the window, 1 only without it; the bootstrap interval
   of the pooled gain is +27 to +43 points. Of 105 pairs whose two halves end on the same line, no pair is
   fully right without the window, which is what the design forces, and 48 are with it. The 14% is a
   property of this set, not a base rate: 19 of its 20 false positives are innocent halves built to be
   ambiguous alone.
2. **Per category, as directions** (seven tests, uncorrected): the interval of the gain clears zero for
   doxxing (+80 points), selfharm (+50), spam (+35), scam (+35) and minors (+30); only doxxing and
   selfharm would survive a Bonferroni correction. Part of the minors and selfharm gain may be the model
   scoring the neighbourhood rather than the message (point 3). **Cannot tell**: harassment (+15, interval from 0 to +32) and nsfw (0: the window
   lifts nsfw's ranking from AUROC 0.68 to 0.91 but no context-dependent positive reaches 0.80).
3. **Where it can hurt, it barely does at the threshold.** No true positive was lost (35 of 35 control
   positives flagged in every arm). An innocent line after other people's violations was flagged 0 of 35
   times alone and 1 of 35 with the shipped window. Below the threshold the neighbourhood does leak:
   messages reporting grooming score `minors` 0.01 to 0.04 alone and 0.11 to 0.31 with the window
   (0.15 to 0.56 without padding, which is not what ships). With the shipped window none crosses 0.70,
   and none would cross 0.50.
4. **Padding bought nothing here; the context field bought all of it.** The window without padding
   (`ctx`, 1.05x the tokens of no window) and the shipped window with padding (`ctx_pad`, 3.08x) differ
   on two rows, both negatives, in opposite directions. Speaker pseudonyms (`ctx_spk`, not shipped) moved
   three verdicts against `ctx`, two one way and one the other, and none on net in recall.
5. **No threshold changes.** Spam passed the pre-registered retuning rule (0.85 is too high once the
   window is on, though the pass rests on a single row) and then failed the pre-registered red-team check
   on one row, a bare `bit.ly` link that `redteam.csv` labels clean and `categories.json` calls spam. Part
   of what keeps context-decided spam under 0.85 is the engine itself: the window drops any line identical
   to the one judged, so "the same offer, posted word for word again" reaches the model without its
   repeats. Section 5 has the numbers and what would
   settle it. `DEFAULT_THRESHOLDS` is untouched, so nothing flows to the site through `sync_product.py`.

## 1. What was measured, and what the sample is

**There is still no labelled set of real conversations.** `data/items.jsonl` has no threads (the
comment on JEV-18, 2026-09-23), JEV-7 and JEV-11 own building one, and JEV-64 has not started. So this run
uses rows written for the purpose, and everything below is about those rows.

**280 rows, 40 per enabled category** (`data/<category>.jsonl`), written by seven model instances, one per
category, from one brief each (the category's criteria from `categories.json`, the row shapes below,
fictional names, domains and numbers, non-explicit wording), labelled by their authors:

| kind | per category | what it asks |
|---|---|---|
| `pair_pos` and `pair_neg` | 15 pairs | the same closing line, byte for byte, after two lead-ups: one makes it a violation of the category, the other makes it innocent. Scored alone, both halves are one text, so without the window at most one of the two can be right |
| `control_pos` | 5 | a line that violates on its own, after ordinary unrelated chat. Does a benign neighbourhood talk the model out of a true positive? |
| `control_neg` | 5 | an innocent line (a report, a defence, a change of subject) after other people's clear violations. Does a bad neighbourhood make an innocent message look guilty? |

Lead-ups are 4 to 9 messages, chat register, English. The label is what a moderator reading the whole
conversation would decide about the closing line under that category's criteria, and the same label
scores every arm.

**Labels were fixed before any paid call.** The data and the runner, with its metrics and decision rules
in the docstring, were committed in `0c391ca` before the paid run; `results/raw.jsonl` carries the data's
sha256 (`cd965176...`) on every line, and `ask` refuses to mix results from other data. Two edits were made
to the data before that commit and before any call: fifteen doxxing pairs and one nsfw pair had different
channel topics on their two halves, and the doxxing topics described the scenario ("Trying to find where
an ex moved to"), which would have told the no-window arm the answer; they were replaced with one neutral
topic per pair, and the doxxing control negatives got the same neutral topic. One smoke call per arm on one
row (`harassment-p01-pos`) was made before the commit to test the runner; its scores were not kept.

**A second labeller** (a separate model instance, reading only a file of shuffled rows with the label,
kind and reasoning removed and the ids replaced) relabelled all 280 from the conversation. It agreed on 269
(96%): 96 of 105 pair positives, 103 of 105 pair negatives, all 70 controls. Seven of the eleven
disagreements are nsfw pair positives, so the nsfw set's positives are the weakest labels here.
`report --agreed-only` recomputes everything on the 269; no verdict in section 2 changes, pooled gain moves
from +35 to +37 points. The agreement is an upper bound on independence: 105 closing lines appear twice in
the labeller's file, so it could infer that each pair has one of each. It was started before the paid run
and finished while it ran, reading only a copy of that file in a separate folder.

**The arms**, every row in all four, two repeats each, arms shuffled per row, cache off:

| arm | what it is | path |
|---|---|---|
| `off` | the message alone, the filler at `m0` | `ModerationService.moderate` with an empty window, which is production with context off |
| `ctx_pad` | **what ships**: the window as `context` plus padding | the lead-up written into the service's `ConversationBuffer`; the service attaches it through `assemble` and, the batch being one message, pads the request with the same window |
| `ctx` | the window as `context`, no padding | the same with `PAD_BATCH` off |
| `ctx_spk` | exploratory: `context` entries prefixed `[author]` for the closing's own author and `[A]`, `[B]` for others | `Judge` directly, no padding; the shape JEV-19 decided and no engine sends yet |

**Scoring.** A row is flagged when its own category is at or over the shipped threshold
(`DEFAULT_THRESHOLDS`: spam 0.85, scam 0.75, harassment 0.75, nsfw 0.80, selfharm 0.50, doxxing 0.80,
minors 0.70); its score is the mean of its two repeats. Intervals are 95% percentile bootstraps over
scenarios (a pair is one scenario, its halves resampled together), 2,000 resamples, fixed seed.

**One row pair is never judged.** `harassment-p14` closes on "Get out.", six letters, and the engine's
pre-filter skips anything under eight whatever its context. The runner's own check counted characters,
not letters, and let it through; the row stays, as the pre-registration says, and every arm scores it 0:
a missed positive and a correct negative in all four arms. The check now calls the real pre-filter.

## 2. Recall and false-positive rate at the shipped thresholds

| category | arm | recall | 95% CI | FPR | 95% CI | AUROC |
|---|---|---|---|---|---|---|
| spam | off | 35% of 20 | 14 to 56 | 10% of 20 | 0 to 25 | 0.716 |
| spam | ctx_pad | 60% | 39 to 81 | 0% | 0 to 0 | 0.990 |
| spam | ctx | 60% | 39 to 81 | 0% | 0 to 0 | 0.993 |
| scam | off | 45% | 24 to 67 | 20% | 5 to 39 | 0.724 |
| scam | ctx_pad | 75% | 55 to 91 | 15% | 0 to 32 | 0.919 |
| scam | ctx | 75% | 55 to 91 | 10% | 0 to 25 | 0.919 |
| harassment | off | 50% | 27 to 71 | 25% | 6 to 45 | 0.676 |
| harassment | ctx_pad | 60% | 38 to 81 | 20% | 5 to 39 | 0.849 |
| harassment | ctx | 60% | 38 to 81 | 20% | 5 to 39 | 0.851 |
| nsfw | off | 25% | 6 to 44 | 0% | 0 to 0 | 0.681 |
| nsfw | ctx_pad | 25% | 6 to 44 | 0% | 0 to 0 | 0.910 |
| nsfw | ctx | 25% | 6 to 44 | 0% | 0 to 0 | 0.917 |
| selfharm | off | 35% | 14 to 56 | 10% | 0 to 25 | 0.615 |
| selfharm | ctx_pad | 80% | 60 to 95 | 5% | 0 to 17 | 0.948 |
| selfharm | ctx | 80% | 60 to 95 | 10% | 0 to 25 | 0.940 |
| doxxing | off | 45% | 22 to 67 | 30% | 11 to 50 | 0.711 |
| doxxing | ctx_pad | 95% | 84 to 100 | 0% | 0 to 0 | 1.000 |
| doxxing | ctx | 95% | 84 to 100 | 0% | 0 to 0 | 0.998 |
| minors | off | 25% | 6 to 44 | 0% | 0 to 0 | 0.695 |
| minors | ctx_pad | 55% | 33 to 78 | 0% | 0 to 0 | 0.978 |
| minors | ctx | 55% | 33 to 78 | 0% | 0 to 0 | 0.946 |
| **all** | off | 37% of 140 | 29 to 46 | 14% of 140 | 8 to 19 | 0.691 |
| **all** | ctx_pad | 64% | 56 to 72 | 6% | 2 to 10 | 0.898 |
| **all** | ctx | 64% | 56 to 72 | 6% | 2 to 10 | 0.903 |

Every category has 20 positives and 20 negatives. `ctx_spk` is in `report`; at the threshold it matches
the other two window arms in recall everywhere, and in FPR it equals one or the other of them in every
category. An interval of "0 to 0" is a bootstrap of a zero count, not a measured zero rate: 0 of 20 is
compatible with a true rate up to about 15%.

**The shipped window against no window, paired.** Gain is (recall change) minus (FPR change); the verdict
rule was fixed before the run: "helps" when the interval of the gain is above zero, "hurts" when below,
otherwise the sample cannot tell.

| category | recall change | FPR change | gain | 95% CI | right only with | right only without | McNemar p | verdict |
|---|---|---|---|---|---|---|---|---|
| spam | +25 | -10 | +35 | +16 to +55 | 7 | 0 | 0.016 | helps |
| scam | +30 | -5 | +35 | +15 to +55 | 7 | 0 | 0.016 | helps |
| harassment | +10 | -5 | +15 | 0 to +32 | 3 | 0 | 0.25 | cannot tell |
| nsfw | 0 | 0 | 0 | 0 to 0 | 0 | 0 | 1 | cannot tell |
| selfharm | +45 | -5 | +50 | +25 to +72 | 11 | 1 | 0.006 | helps |
| doxxing | +50 | -30 | +80 | +57 to +103 | 16 | 0 | 3e-5 | helps |
| minors | +30 | 0 | +30 | +11 to +53 | 6 | 0 | 0.031 | helps |
| **all** | +27 | -8 | +35 | +27 to +43 | 50 | 1 | 5e-14 | helps |

The McNemar column treats the 280 rows as independent, and they are not: the two halves of a pair share
their closing line, and without the window their correctness is anticorrelated by construction. Its p
values are smaller than they should be and are indicative only; the bootstrap over scenarios is the test
the verdicts use. Seven categories tested at 0.05 is seven chances; minors at p = 0.031 and spam and scam at 0.016 would not
survive a Bonferroni correction (0.007), selfharm and doxxing would. The bootstrap intervals, which are
what the verdicts use, are not corrected either. Read the per-category verdicts as directions and the
pooled row as the measurement.

**Why harassment moves least is not known.** The window the engine sends is message text with no
speakers (`core/context.py` cannot hold an author), and harassment on these rows is mostly about who is
aimed at whom: four people turning on a fifth reads, as unattributed lines, much like five people ribbing
each other. The pseudonym arm was the test of that explanation and did not change a single harassment
verdict, so the explanation is not supported; three rows right only with the window is too few to say more.

**Why nsfw does not move at the threshold.** The window lifts the nsfw positives from a mean of 0.31
alone to 0.41 (`ctx_pad`) and the ranking from 0.68 to 0.91, but the highest context-dependent one
reaches 0.59 (0.62 without padding) against a threshold of 0.80. The rows that reach 0.80 are the five that say "nudes" outright, alone
or not. The blind labeller also disagreed with seven of the fifteen nsfw pair positives, so part of the
gap is the labels.

## 3. Where the window could hurt

| kind | rows | off | ctx | ctx_pad | ctx_spk |
|---|---|---|---|---|---|
| pair_pos (flagged, should be) | 105 | 17 (16%) | 55 (52%) | 55 (52%) | 55 (52%) |
| pair_neg (flagged, should not be) | 105 | 19 (18%) | 6 (6%) | 7 (7%) | 7 (7%) |
| control_pos (flagged, should be) | 35 | 35 (100%) | 35 (100%) | 35 (100%) | 35 (100%) |
| control_neg (flagged, should not be) | 35 | 0 (0%) | 2 (6%) | 1 (3%) | 2 (6%) |

- **A benign neighbourhood never talked the model out of a clear violation**: 35 of 35 in every arm,
  compatible with a loss rate up to about 10%. The control positives are unambiguous by design (every
  one scores 0.88 or more alone), so this says the window does not undo an obvious call, not that it
  never shifts a borderline one.
- **A bad neighbourhood flagged an innocent line once in 35** with the shipped window, against none alone.
  One row is not a rate; 1 in 35 is compatible with about 15%.
- **Below the threshold it leaks, and in one category it leaks a lot.** The five minors control negatives
  (a parent reporting what they found on a child's account, a kid saying they will tell a counsellor, a
  moderator banning the groomer) score `minors` 0.01 to 0.04 alone, 0.11 to 0.31 with the shipped window
  and 0.15 to 0.56 with the window and no padding. The model partly scores the conversation instead of
  the message. With the shipped window nothing crosses 0.70, or would cross 0.50; without padding one
  row reaches 0.56.
- **Any category on a negative row**, other categories included: 22 of 140 negatives were flagged for
  something alone, 10 with the shipped window. The window removed more false flags than it added.

Not every closing was as ambiguous alone as the authors were asked to make it: without the window 17 of
the 105 context-dependent positives crossed their threshold anyway, and 19 of the innocent halves did
(the same lines). That narrows the room the window had; it does not widen it.

## 4. Noise, and what padding and pseudonyms add

**Repeat noise is small against the effect.** Rows whose verdict changed between the two repeats: 4 of 280
alone, 1 with `ctx`, 1 with `ctx_pad`, 3 with `ctx_spk`; mean absolute difference 0.009 to 0.011. The
effect in section 2 is 50 rows against 1.

**Padding.** `ctx` and `ctx_pad` differ on two rows, both negatives, in opposite directions: padding
flagged `scam-p13-neg` (0.76 against 0.71) and cleared `selfharm-c06-neg` (0.38 against 0.53). On these rows padding costs three times the tokens and buys nothing measurable at the
threshold. This is not the padding measurement JEV-19 fixed (at least 600 spam messages behind the filler
against behind real channel history, McNemar at 0.05, a 5-point floor): this set has 40 spam rows, the
padding here is the scenario's own lead-up, and a batch of one is the only shape run. It is consistent
with padding buying nothing and does not decide `JEVMOD_PAD_BATCH`.

**Speaker pseudonyms** (`ctx_spk`) moved three verdicts against `ctx` (`spam-p06-pos` flagged,
`spam-p15-pos` missed, `scam-p13-neg` flagged) and matched it in recall everywhere.
They raised context-dependent minors positives (the pair positives, mean 0.63 against 0.55) and the minors control
negatives a little too. Nothing here argues for or against building them; the format sent here is one
guess at JEV-19's.

## 5. Thresholds

**The rule, fixed before the run:** a category is retuned only if a threshold chosen on odd-numbered
scenarios improves recall minus FPR by at least 10 points over the shipped one on even-numbered
scenarios, and the same holds with the halves swapped, under `ctx_pad`; a threshold that passes is then
checked against `tests/data/redteam.csv` before it ships.

| category | shipped | chosen on odd | gain on even | chosen on even | gain on odd | passes |
|---|---|---|---|---|---|---|
| spam | 0.85 | 0.73 | +11 | 0.69 | +36 | **yes** |
| scam | 0.75 | 0.82 | 0 | 0.58 | -1 | no |
| harassment | 0.75 | 0.92 | -1 | 0.71 | 0 | no |
| nsfw | 0.80 | 0.55 | +11 | 0.53 | +9 | no |
| selfharm | 0.50 | 0.50 | 0 | 0.50 | 0 | no |
| doxxing | 0.80 | 0.79 | 0 | 0.80 | 0 | no |
| minors | 0.70 | 0.52 | +11 | 0.65 | 0 | no |

**Spam passed, and only just.** The even half has 9 positives and the odd half 11, so one row is 11.1
points on one side and 9.1 on the other: spam's +11 on the even half is exactly one row, and nsfw's
+11 and +9 and minors' +11 are the same granularity, not an effect. With the window, seven of fifteen context-decided spam positives
land between 0.69 and 0.79, just under 0.85, while no spam negative with the window reaches 0.70. At 0.75
the shipped window's spam recall on these rows is 80% against 60%, false positives still 0. The rule did
not say which value to try. 0.75 and 0.76 both clear the 10-point gain on both halves, 0.77 does not;
the check was run at 0.75, the round line, and the row that failed it scores 0.78 to 0.79, over both. Two sources outside this set point the same way and were read, not run,
before the check: on the 476 labelled YouTube comments in `benchmark/results/context_on.jsonl` (window on),
spam recall is 62% at 0.75 against 34% at 0.85, with no false positive among the 226 non-spam comments at
either line, nor among the 349 Civil Comments rows; on the 1,157 unlabelled OpenAI-eval prompts, 0.75
flags 59 for spam against 36 at 0.85, most of the added ones keyword-stuffed web text.

Then `tests/test_redteam.py`, run live with spam at 0.75, twice: nine tests pass and the `length` block
fails on one false positive, `g9`, the bare link `http://bit.ly/3xYzAbC`, spam 0.79 and then 0.78. The
second run's output is `results/redteam_spam_075.txt`; the first run's was read in the terminal and
not saved. `redteam.csv` labels it clean;
`categories.json` lists "bare shortened links with no context" as spam. The check was fixed as a gate, so
the threshold does not change here, and relabelling `g9` after seeing it block the change would be
choosing the label after the result. What would settle it, in order: decide what `g9` is, as a labelling
question on its own; then measure spam at 0.75 against 0.85 on clean chat of the register the product
sells, which is what the 1,718-message Discord set measured at 0.85 (10 false positives, 0.58%,
`BENCHMARK.md`) and whose scores are not in the repository. Spam is flag-only by default, so a false
positive costs a moderator a look.

**The window hides repeats, and that is part of spam's gap.** `ModerationService` drops from the window
any line identical to the one being judged (`window_for(exclude=...)` and the padding filter), so that a
message is not shown to itself. Three spam positives (`spam-p01`, `p05`, `p12`) are the same offer posted
again word for word, and were judged with their own repeats removed. Found by the red-team review, after
the run; `repeat_probe` judged those three once more with the repeats left in (`results/repeat_probe.jsonl`,
6 requests, under a cent):

| row | `ctx_pad` (shipped), repeats removed | `ctx`, repeats removed | repeats kept, no padding | threshold |
|---|---|---|---|---|
| spam-p01-pos | 0.77 | 0.80 | 0.83 | 0.85 |
| spam-p05-pos | 0.73 | 0.80 | 0.83 | 0.85 |
| spam-p12-pos | 0.69 | 0.73 | 0.79 | 0.85 |

Against `ctx`, the arm with the same shape, seeing the repeats adds 0.03 to 0.06 and none crosses 0.85:
the exclusion costs something, not the threshold's whole gap. The probe calls `Judge` directly and ran
twenty minutes after the main run, so path and time are not controlled; repeat noise in the main run was
about 0.01. Whether the window should keep a verbatim repeat from a different message is a
question for the context engine, not for this report.

**nsfw and minors** came within a point of the rule on one half each and nowhere near on the other. With
the leakage in section 3, lowering minors is the change this data argues most against.

## 6. Cost against quality

Billed input tokens per judged message, this run, one message per request:

| arm | tokens | multiplier | $ per 1K | positions | context entries kept |
|---|---|---|---|---|---|
| off | 2,087 | 1.00x | $0.088 | 2.0 | 0.0 |
| ctx | 2,192 | **1.05x** | $0.092 | 2.0 | 5.7 |
| ctx_pad | 6,421 | **3.08x** | $0.270 | 6.6 | 5.7 |
| ctx_spk | 2,206 | 1.06x | $0.093 | 2.0 | 5.7 |

JEV-67 measured the shipped window at 1.22x to 1.35x in batches of 10 to 50 and 4.53x for a message
alone with a full window of ten (`benchmark/context_cost/REPORT.md`). The 3.08x here is lower because
these lead-ups hold 4 to 9 messages, so a padded request has fewer positions.

- **The `context` field pays for itself where context decides**, at 1.05x for a message alone (quality
  was measured only on messages alone; the 1.22x to 1.35x of a batch is JEV-67's cost, not measured for
  quality here): pooled, 27 points of recall and 8 points of false-positive rate, on rows built so that it can.
  How often real traffic has such rows is not measured, so this is what the window does when context
  decides, not its average; nor is it a proven upper bound, since other constructed rows could gain more.
  `EVAL.md` measured the other end: on rows with no conversation in them the window changed
  nothing measurable.
- **Padding, at three to four and a half times, bought nothing here** beyond the field. That is evidence
  for JEV-19's padding measurement to run, not a substitute for it.
- **JEV-19's rule (1.75x at batches of ten or more) is not in question**: the conversation part is well
  under it, and nothing here asks for more context than the window of ten already sends.

## What this does not say

- **It is not real traffic.** The rows were written by model instances to make the window matter; the
  gain is what the window can do when context decides, not how often it does. The authors and the blind
  labeller are models, not moderators, and no human has read all 280 rows.
- **English only, one register, short lead-ups** (4 to 9 messages), one message per request. Batches
  were not run; `BATCH_EFFECT.md` found scores move with batch membership, so a batched window may land
  differently near a threshold.
- **Twenty positives and twenty negatives per category.** Intervals of 40 points are the honest width;
  the per-category verdicts are directions, the pooled line is the measurement.
- **The window sent is text only**, as shipped: no speaker, no user history, no community state. JEV-19's
  history and community lines are not built and not measured; the pseudonym arm is one possible format.

## Reproduce

Needs `TYPESAFE_API_KEY` and `PYTHONUTF8=1`.

    python -m benchmark.context_quality.run check     # free: schema, pairs, pre-filter notes, data hash
    python -m benchmark.context_quality.run blind     # free: the shuffled, unlabelled file for a second labeller
    python -m benchmark.context_quality.run ask       # paid, about $0.30, resumable
    python -m benchmark.context_quality.run report    # free: every table here
    python -m benchmark.context_quality.run report --agreed-only
