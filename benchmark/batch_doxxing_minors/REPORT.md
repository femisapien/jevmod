# Does `doxxing` or `minors` depend on the batch? The rule's prediction, tested.

Run on 2026-09-28 against the live TypeSafe API from `benchmark/batch_doxxing_minors/run.py`. 470
messages, six conditions, 2,820 recorded judgements plus 1,880 neutral neighbours judged and
discarded, 643 requests, 5.40M input tokens, **$0.227** including the pilot. Raw results in
`results.jsonl` beside this file (ids and scores, no text), so every table recomputes for free.

JEV-62. `benchmark/BATCH_EFFECT.md` (JEV-56) found that for spam and harassment the *membership* of a
batch moves a score and its *composition* does not; `ai_detect/REPORT2.md` found the opposite for
`ai_generated`. BATCH_EFFECT.md section 4 reconciled the two with a rule written to explain those two
points: a question about the author or the world uses the neighbours as evidence, a question about
the text does not. The rule predicts that `doxxing` and `minors` move with composition. This is the
test.

## The short answer

**No composition effect survives, on decisions or on scores.** At the shipped thresholds, 0.80 for
`doxxing` and 0.70 for `minors`, no change of composition moves recall or the false-positive rate by
an amount this data can tell from zero, and no shift in the scores themselves survives correction
once the test is run on the unit that was actually randomised, the request. For `minors` the
decision test has about ±7 points of resolution and does not exclude effects up to roughly 12. For
`doxxing` it is a weak test, because the synthetic set has almost nothing near the line (section 5).

**The largest score shift is a hundredth.** Doxxing positives score **0.011 lower** when half their
neighbours are look-alike hard negatives: 15 of 16 templates down, but only 9 of 12 requests, which
is p = 0.15, and Holm 1.000 over the family. It is the direction the rule predicts, and among neutral
chat, which removes even more doxxing neighbours, the same messages go 0.003 the other way. At a mean
of 0.95 against a line at 0.80 it would change nothing even if it were real.

**No production change.** Judging these categories in isolation, which a composition effect would
have argued for, does not help either: alone, `doxxing` recall falls 5.7 points and false positives
rise 3.3 (point estimates, not significant after correction, and concentrated in two templates), and
`minors` does not move. Nothing here argues for a threshold move either.

**The rule is neither confirmed nor refuted, and should not be designed from.** In the two categories
it named this data sees no composition effect at all, and the resolution on `doxxing` decisions is
poor. It stays what JEV-62 called it: a rule invented to
explain two data points. Whether a category is composition-sensitive is measured, as this folder does
for about $0.23, not predicted.

## 1. The pools

| group | positive | hard negative | threshold |
|---|---|---|---|
| `doxxing` | 150 synthetic, 16 templates | 150 synthetic, 16 templates | 0.80 |
| `minors` | the 85 rows `items.jsonl` labels `minors` (81 distinct) | 85 rows labelled `nsfw` and not `minors` (84 distinct) | 0.70 |

**`doxxing` is synthetic because the labelled set has no doxxing rows at all.** `doxxing_items.py`
fills 16 templates per side, at least one per clause of the category's `true` and `false` criteria
in `jevmod/categories.json`. Every phone number is from a range reserved for fiction (NANP
555-0100 to 555-0199, Ofcom 07700 900xxx), every email domain from RFC 2606, and
`tests/test_batch_doxxing_minors.py` fails if that stops being true. The labels are the template's,
not a person's. The hard negatives carry the surface of doxxing (addresses, numbers, names, places)
and are excluded by the criteria: business contact details, the author's own city or first name,
public offices, fictional characters, venues, privacy talk. Neutral text sits near zero and cannot
cross 0.80, so without them the clean side of the test would be empty.

**`minors` uses only what the repository already holds.** The rows are the S3 class of the OpenAI
moderation eval, prepared by `benchmark/prepare.py` into the git-ignored `benchmark/data/`. Nothing
of this kind was written, generated or fetched for this measurement, and no text of these rows
appears in this folder: the results hold ids and scores, and a test fails if a row carries text. The
hard negatives are adult sexual content, which the category's `false` criterion excludes by name
("adults talking about adults (that is nsfw)") and which is the confusion a moderator would care
about. Five pairs of rows are the same text once normalised; `Judge` asks identical text once per
request, so both ids of a pair can carry one verdict, and the later id of each pair is left out of
every table. 81 and 84 is all there is, and it sets the power: section 5.

The neutral neighbours for `diluted` are the 226 clean YouTube comments of the labelled set that pass
the pre-filter, which dropped 24.

## 2. The conditions

The production question set (every category on by default), 25 messages per request where the
condition batches, the lead filler at `m0` as production puts it.

| condition | what it is |
|---|---|
| `pure` | each pool in batches of its own; the pool is shuffled first, so this is one random grouping |
| `pure2` | the identical requests again: the noise floor for a repeated request |
| `reshuffled` | each pool regrouped: a second random grouping, same composition |
| `mixed_shuffled` | positives and hard negatives together, membership randomised: composition half the other side |
| `diluted` | 5 of one pool among 20 neutral chat comments, positions shuffled: composition 80% unrelated, a doxxing message in a real channel |
| `single` | one message per request, filler at `m0`: a cold, quiet channel |

**The reference for every composition contrast is the mean of `pure` and `reshuffled`.** Both hold the
composition and randomise the membership, independently, so neither is a better reference than the
other, and a contrast against one alone inherits that grouping's luck. The first draft of this report
used `reshuffled` alone and published a survivor that did not survive against `pure`: section 6.
Beside every composition contrast the analysis prints the **membership control**, `reshuffled` minus
`pure`: two groupings with no composition change at all. It is one draw of the null, descriptive,
not a calibration of the test's error rate.

## 3. Recall, false positives, precision

Mean score, then the share over the shipped line with a 95% Wilson interval. On the positive side
that share is recall; on the hard-negative side it is the false-positive rate. The Wilson intervals
treat items as independent, which the doxxing items are not (section 4.1); the paired intervals in
4.1 do not make that assumption and are the ones to read.

| group | side | n | `pure` | `reshuffled` | `mixed_shuffled` | `diluted` | `single` |
|---|---|---|---|---|---|---|---|
| doxxing | positive | 150 | 0.958 / 100% [98, 100] | 0.956 / 99.3% [96, 100] | 0.946 / 100% [98, 100] | 0.960 / 99.3% [96, 100] | 0.923 / **94.0%** [89, 97] |
| doxxing | hard neg. | 150 | 0.072 / 0.0% [0, 2] | 0.081 / 0.0% [0, 2] | 0.081 / 0.0% [0, 2] | 0.073 / 0.0% [0, 2] | 0.095 / **3.3%** [1, 8] |
| minors | positive | 81 | 0.579 / 42.0% [32, 53] | 0.571 / 39.5% [30, 50] | 0.583 / 42.0% [32, 53] | 0.573 / 45.7% [35, 56] | 0.613 / 45.7% [35, 56] |
| minors | hard neg. | 84 | 0.185 / 6.0% [3, 13] | 0.177 / 4.8% [2, 12] | 0.194 / 4.8% [2, 12] | 0.197 / 6.0% [3, 13] | 0.176 / 6.0% [3, 13] |

Precision at the pools' own 1:1 ratio, bootstrap 95% resampling templates for doxxing and rows for
minors. Not a production precision, since the negatives are the hardest there are and the base rate
is 50%; it is here so a condition that bought recall with false positives would show it.

| group | `pure` | `reshuffled` | `mixed_shuffled` | `diluted` | `single` |
|---|---|---|---|---|---|
| doxxing | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 0.966 [0.87, 1.00] |
| minors | 0.872 [0.76, 0.97] | 0.889 [0.78, 0.97] | 0.895 [0.79, 0.98] | 0.881 [0.77, 0.97] | 0.881 [0.78, 0.97] |

`minors` recall of 40% to 46% at 0.70 is not new: `benchmark/results/report.md` has 0.45 on the same
rows. It is a calibration fact about this category on this data, and it does not move with the batch.

## 4. The tests

### 4.1 Composition against the reference

Two measures per cell. The sign test on paired scores asks whether the distribution shifts at all,
the test that found spam's +0.19 in JEV-56. The paired change in the share over the line asks whether
a shift changes a decision. Holm over all sixteen rows, the membership controls and `single`
included.

**Two units are correlated here, and the test runs on both.** The doxxing items are 16 templates per
side with the slots filled, and items from one template behave alike. Every item in one request
shares that request's draw. So the sign test is run on templates (a `minors` row is its own cluster)
and on the requests of the changed arm, and the larger of the two p-values is the one corrected.
Intervals resample templates or rows; they do not model the request, so read them as narrow.

| contrast | templates or rows up/down | requests up/down | larger p | Holm p | mean score shift [95%] | share over the line, change [95%] |
|---|---|---|---|---|---|---|
| doxxing positive, membership control | 7/9 | 3/3 | 1.000 | 1.000 | −0.002 [−0.005, +0.001] | −0.7 pts [−2.0, +0.0] |
| doxxing positive, `mixed_shuffled` | 1/15 | 3/9 | 0.146 | 1.000 | −0.011 [−0.016, −0.007] | +0.3 pts [+0.0, +1.0] |
| doxxing positive, `diluted` | 12/4 | 21/9 | 0.077 | 1.000 | +0.003 [+0.000, +0.007] | −0.3 pts [−1.0, +0.0] |
| doxxing positive, `single` | 4/12 | 37/98 | 0.077 | 1.000 | −0.034 [−0.065, −0.010] | −5.7 pts [−16.4, +0.0] |
| doxxing hard neg., membership control | 4/10 | 3/3 | 1.000 | 1.000 | +0.009 [−0.004, +0.031] | +0.0 pts |
| doxxing hard neg., `mixed_shuffled` | 11/5 | 5/7 | 0.774 | 1.000 | +0.004 [−0.002, +0.010] | +0.0 pts |
| doxxing hard neg., `diluted` | 6/10 | 9/21 | 0.455 | 1.000 | −0.004 [−0.011, +0.003] | +0.0 pts |
| doxxing hard neg., `single` | 5/11 | 44/96 | 0.210 | 1.000 | +0.019 [−0.015, +0.077] | +3.3 pts [+0.0, +10.1] |
| minors positive, membership control | 37/37 | 1/3 | 1.000 | 1.000 | −0.008 [−0.032, +0.015] | −2.5 pts [−9.9, +3.7] |
| minors positive, `mixed_shuffled` | 37/40 | 5/2 | 0.820 | 1.000 | +0.008 [−0.013, +0.029] | +1.2 pts [−5.6, +8.0] |
| minors positive, `diluted` | 43/36 | 10/7 | 0.629 | 1.000 | −0.002 [−0.030, +0.025] | +4.9 pts [−1.9, +12.3] |
| minors positive, `single` | 47/32 | 47/32 | 0.115 | 1.000 | +0.038 [+0.010, +0.067] | +4.9 pts [−1.2, +11.7] |
| minors hard neg., membership control | 31/40 | 1/3 | 0.625 | 1.000 | −0.007 [−0.020, +0.006] | −1.2 pts [−3.6, +0.0] |
| minors hard neg., `mixed_shuffled` | 47/30 | 5/2 | 0.453 | 1.000 | +0.013 [−0.002, +0.027] | −0.6 pts [−1.8, +0.0] |
| minors hard neg., `diluted` | 43/32 | 10/7 | 0.629 | 1.000 | +0.016 [+0.001, +0.033] | +0.6 pts [−1.2, +3.6] |
| minors hard neg., `single` | 32/46 | 32/46 | 0.141 | 1.000 | −0.005 [−0.024, +0.014] | +0.6 pts [−1.2, +3.6] |

A "+0.0 pts" with no interval is a cell where no item changed side, so every resample gives zero. It
means no decision changed, not that the change is known to be exactly zero. In `single` every request
is one item, so the request column repeats the item counts and the template column is the binding one.

**What the rule predicted, cell by cell:**

- *Doxxing positives among fewer doxxing neighbours score lower.* Among hard negatives the point
  estimate goes that way, −0.011 and 15 of 16 templates, but 9 of 12 requests is p = 0.15: the
  templates share those twelve requests, so they are not sixteen pieces of evidence. Among neutral
  chat, which removes even more doxxing neighbours but also changes the length and register of the
  request, +0.003. Neither survives.
- *Doxxing hard negatives among doxxing score higher.* +0.004, 5 of 12 requests up. Nothing.
- *Minors positives among fewer minors neighbours score lower.* 37 up, 40 down. Nothing.
- *Adult sexual text among minors content.* The rule can be read either way here: minors neighbours
  are evidence for minors, and adult neighbours are evidence for adults. The data does not have to
  choose: +0.013 with minors neighbours and +0.016 among neutral chat, neither surviving, and no
  decision moved.

### 4.2 Membership, against the noise floor

The JEV-56 table: crossings of the shipped line against `pure`, McNemar against the `pure2` floor,
Holm over sixteen tests. Nothing survives. The largest are `doxxing/positive/single`, 9 crossings
against 0 (Holm p = 0.062, item-level, and all nine come from two templates, so it flatters the
effect), and `minors/positive/diluted`, 11 against 5 (Holm p = 1.000). `run.py analyse` prints the
table. `pure2` is the byte-identical repeat, which JEV-56 found is a slightly flattering floor; since
nothing survives against it, a higher floor would not change anything here.

Scores do move with membership, as they did for spam, without moving decisions often enough to
measure at this n. Mean absolute movement against `pure`:

| group | side | `pure2` | `reshuffled` | `mixed_shuffled` | `diluted` | `single` |
|---|---|---|---|---|---|---|
| doxxing | positive | 0.004 | 0.013 | 0.019 | 0.015 | 0.042 |
| doxxing | hard neg. | 0.009 | 0.029 | 0.029 | 0.024 | 0.050 |
| minors | positive | 0.019 | **0.079** | 0.082 | 0.104 | 0.106 |
| minors | hard neg. | 0.015 | 0.044 | 0.051 | 0.047 | 0.052 |

`minors` positives move 0.079 on a regrouping against 0.019 on a repeat, about four times the floor.
Spam positives in JEV-56 moved 0.073 against 0.011. So a `minors` score has the same one-decimal
reproducibility per message that spam's has, and its positives sit around their line (mean 0.58
against 0.70), which is where that matters. At n = 81 the crossings it causes are 8 against a floor
of 5, which this data cannot separate from noise.

### 4.3 Alone

`single` is the production path for a cold, quiet channel: the lead filler at `m0`, the message at
`m1`, nothing else, because the conversation window is empty. JEV-57 found spam loses 21 points of
recall alone before the filler shipped and 9 after.

- **`doxxing` alone is worse on both sides as a point estimate**, 94.0% recall against 99.3% to 100%
  batched, and 3.3% false positives against 0%, with neither change significant after correction. It
  is concentrated. Of the nine positives under the line alone, eight are one template, a licence plate
  and the street a person parks on, whose mean falls from 0.90 batched to 0.69 alone. All five false
  positives are one template, "how do people even find someone's address from a username? asking for
  a privacy talk", whose mean rises from 0.34 to 0.79. Both are the borderline texts of this set:
  among neighbours the model is surer the plate is doxxing and the privacy question is not.
- **`minors` does not move alone** in any way this data can resolve: +0.038 on positives, the wrong
  direction for a context-starved question, and no change in either rate.

So neither category is better judged alone, which is what isolating them would amount to.

## 5. What this does not measure

- **Real doxxing, and most of the doxxing decisions.** The synthetic positives are unambiguous and sit
  at 0.95; 15 of the 16 hard-negative templates average under 0.15 in every condition. Only two
  templates of 32 have any mass near 0.80, so four of the eight "no decision changed" cells rest on
  those two, and a doxxing decision-level effect would have to be enormous to show. The rule's own
  mechanism, "is this data real, is this person private", barely applies to text whose data is
  fictional by construction, and the model may know that 555 numbers are. The score-level tests still
  speak; the decision-level ones need real labelled doxxing, which is JEV-11. The licence plates follow
  the UK format with random letters and digits; there is no range reserved for fiction, so some may
  match a real plate, attached to a made-up handle and street.
- **Power on `minors`.** 81 and 84 rows is all the labelled set has, in four requests per side per
  batched reference arm. The recall-change intervals are about ±7 points wide around their estimates
  and the upper ends reach +12, so a composition effect up to roughly 12 points of recall is not
  excluded, and the intervals do not model the request, so they are if anything narrow. What is
  excluded is an effect the size of REPORT2's `ai_generated` one, which moved a false-positive rate
  from 30% to 67%.
- **Length and register.** The neutral comments have a median of 38 characters; the `minors`
  positives 1,081 and the adult rows 808; the doxxing texts 85 to 88. `diluted` changes the length and register of the
  request as well as its composition, so it is not a clean composition arm on its own.
- **Order.** The conditions ran one after another, minutes apart, with no interleaving. `pure2` bounds
  drift between adjacent runs only.
- **Request size.** With 85 rows per pool, the `minors` reference arms hold a request of ten and
  `mixed_shuffled` one of twenty, so request size moves slightly with composition there.
- **Chat.** The `minors` rows are moderation-eval prose, not chat, and grooming is a sequence of
  messages rather than one. That is context (JEV-18), not composition, and it is not tested here.
- **Precision in production.** The 1:1 precision above is on the hardest negatives at a 50% base rate.
  It shows that no condition trades recall for false positives, and nothing about a real channel.

## 6. What the review changed

Two red-team rounds, each with no context, attacked the draft against the committed data. What they
found, all recomputed here before being accepted:

- **Round one: the first draft's survivor was the reference's luck.** It reported `minors` hard
  negatives scoring +0.016 with minors neighbours, Holm p = 0.002, against `reshuffled`. `pure` is also
  a random grouping (the pools are shuffled before chunking), so the JEV-56 reason for not using it did
  not apply, and against `pure` the same contrast did not survive. Fixed by the averaged reference and
  the membership control row. The withdrawn claim also carried "the rule does not predict +0.019 among
  neutral chat"; adult neighbours are evidence for adults, so the rule can predict it, and that is
  withdrawn too.
- **Round one: duplicates.** Five `minors` pairs were one text twice and were counted as two
  observations. The later id of each is now left out.
- **Round one: overstatements.** The doxxing decision cells were presented as a result when the set has
  almost no mass near the line; "retire the rule" went further than the data; the alone figures were
  stated as costs when they are point estimates that do not survive correction.
- **Round two: the second draft's survivor was the unit of analysis.** After the fix above, doxxing
  positives among hard negatives survived, 15 of 16 templates, Holm p = 0.008. The sixteen templates
  share the same twelve requests, so a draw that belongs to a request lands on all of them at once:
  by request it is 9 of 12 down, p = 0.15. The sign test now runs on both units and corrects the
  larger p, and nothing survives. The "contrast with look-alike text" mechanism the second draft
  offered for it is withdrawn with it: within the arm, the requests holding the most doxxing positives
  moved furthest (r = −0.57 over twelve requests, permutation p = 0.06), the opposite of that story and
  closer to a draw per request.
- **Round two: smaller corrections.** The membership control is one draw, not a calibration, and is
  described as such; the `minors` resolution is stated with its upper ends; the fictional-data test
  was loose (it let any text containing 07700 through) and now fails on any run of four or more digits
  outside the reserved ranges; `run.py` now refuses to resume or analyse rows judged in a request its
  current design no longer builds.

## What to do

1. **No change to production.** No isolation, no per-category batching, no threshold move: nothing
   here supports one.
2. **Do not design questions from the rule.** `BATCH_EFFECT.md` section 4 now points here. Measure a
   category's composition sensitivity, with this runner, before relying on it.
3. **Treat a `minors` score as spam's is treated:** a regrouping moves it 0.08 on average around a
   line it sits near. The `AGENTS.md` margin rule (assert a category and a direction, or a margin of
   0.2) already covers it.
4. **Re-run the doxxing half on real labels** when JEV-11 provides them, with the same runner and the
   pools taken from the labelled set.

## Reproduce

```
python -m benchmark.batch_doxxing_minors.doxxing_items   # free: rewrites doxxing.jsonl, byte-identical
python -m benchmark.batch_doxxing_minors.run pools       # free: pools, drops, request counts
python -m benchmark.batch_doxxing_minors.run pilot       # paid, one request per condition, $0.005
python -m benchmark.batch_doxxing_minors.run ask all     # paid, resumable, $0.22
python -m benchmark.batch_doxxing_minors.run analyse     # free, every table above
```

`benchmark/data/items.jsonl` has to exist first (`python benchmark/prepare.py`). `cache_ttl_s=0` is
load-bearing, as in JEV-56, and the runner refuses a cached or unjudged verdict. A request is written
whole or not at all, and a resumed run refuses a partly written one rather than re-asking it with
different neighbours.
