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

**The prediction fails where it matters.** At the shipped thresholds, 0.80 for `doxxing` and 0.70
for `minors`, no change of composition moves recall or the false-positive rate by an amount this data
can tell from zero, in any of the eight cells. The only composition effect that survives correction
is on scores, not decisions: adult sexual text scores **+0.016** higher on `minors` when half its
neighbours are `minors` rows instead of other adult text, and +0.019 higher among neutral chat,
which the rule does not predict. Neither adds a false positive.

**No production change.** Judging these two categories in isolation, which is what a composition
effect would have argued for, makes `doxxing` worse, not better: alone, recall falls 5.3 points and
false positives rise 3.3, both concentrated in two templates. The thresholds are not what this
measurement tests, and it gives no reason to move them.

**The rule should stop being used to design questions.** It is now one category for it
(`ai_generated`), no decision-level effect in the two categories it named, and a score effect in one
cell whose direction does not separate it from "any change of neighbours moves the score a little".
It was, as JEV-62 says, a rule invented to explain two data points.

## 1. The pools

| group | positive | hard negative | threshold |
|---|---|---|---|
| `doxxing` | 150 synthetic, 16 templates | 150 synthetic, 16 templates | 0.80 |
| `minors` | the 85 rows `items.jsonl` labels `minors` | 85 rows labelled `nsfw` and not `minors` | 0.70 |

**`doxxing` is synthetic because the labelled set has no doxxing rows at all.** `doxxing_items.py`
fills 16 templates per side, at least one per clause of the category's `true` and `false` criteria
in `jevmod/categories.json`. Every phone number is from a range reserved for fiction (NANP
555-0100 to 555-0199, Ofcom 07700 900xxx), every email domain from RFC 2606, and
`tests/test_batch_doxxing_minors.py` fails if that stops being true. The labels are the template's,
not a person's. The hard negatives carry the surface of doxxing (addresses, numbers, names, places)
and are excluded by the criteria: business contact details, the author's own city or first name,
public offices, fictional characters, venues, privacy talk. Neutral text sits near zero and cannot
cross 0.80, so without them the clean side of the test would be empty.

**`minors` uses only what the repository already holds.** The 85 rows are the S3 class of the OpenAI
moderation eval, prepared by `benchmark/prepare.py` into the git-ignored `benchmark/data/`. Nothing
of this kind was written, generated or fetched for this measurement, and no text of these rows
appears in this folder: the results hold ids and scores, and a test fails if a row carries text. The
hard negatives are adult sexual content, which the category's `false` criterion excludes by name
("adults talking about adults (that is nsfw)") and which is the confusion a moderator would care
about. 85 is all there is, and it sets the power: section 5.

The neutral neighbours for `diluted` are the 226 clean YouTube comments of the labelled set that pass
the pre-filter, which dropped 24.

## 2. The conditions

The production question set (every category on by default), 25 messages per request where the
condition batches, the lead filler at `m0` as production puts it.

| condition | what it is | against `reshuffled`, what differs |
|---|---|---|
| `pure` | each pool in batches of its own, seeded order | baseline for crossings |
| `pure2` | the identical requests again | nothing: the noise floor |
| `reshuffled` | each pool regrouped, same composition | the reference for every composition test |
| `mixed_shuffled` | positives and hard negatives together, membership randomised | composition, half the other side |
| `diluted` | 5 of one pool among 20 neutral chat comments, positions shuffled | composition, 80% unrelated: a doxxing message in a real channel |
| `single` | one message per request, filler at `m0` | no batch at all: a cold, quiet channel |

Every composition contrast is against `reshuffled` and never against `pure`, the lesson of JEV-56:
`pure` holds its neighbours fixed, so a change against it is membership and composition at once.

## 3. Recall, false positives, precision

Mean score, then the share over the shipped line with a 95% Wilson interval. On the positive side
that share is recall; on the hard-negative side it is the false-positive rate. The Wilson intervals
treat items as independent, which the doxxing items are not (section 4.1); the paired intervals in
4.1 do not make that assumption and are the ones to read.

| group | side | n | `reshuffled` | `mixed_shuffled` | `diluted` | `single` | `pure2` (floor) |
|---|---|---|---|---|---|---|---|
| doxxing | positive | 150 | 0.956 / 99.3% [96, 100] | 0.946 / 100% [98, 100] | 0.960 / 99.3% [96, 100] | 0.923 / **94.0%** [89, 97] | 0.959 / 100% |
| doxxing | hard neg. | 150 | 0.081 / 0.0% [0, 2] | 0.081 / 0.0% [0, 2] | 0.073 / 0.0% [0, 2] | 0.095 / **3.3%** [1, 8] | 0.075 / 0.0% |
| minors | positive | 85 | 0.570 / 38.8% [29, 49] | 0.584 / 41.2% [31, 52] | 0.573 / 44.7% [35, 55] | 0.609 / 44.7% [35, 55] | 0.582 / 43.5% |
| minors | hard neg. | 85 | 0.176 / 4.7% [2, 11] | 0.192 / 4.7% [2, 11] | 0.195 / 5.9% [3, 13] | 0.175 / 5.9% [3, 13] | 0.186 / 5.9% |

Precision at the pools' own 1:1 ratio, bootstrap 95% resampling templates for doxxing and rows for
minors. Not a production precision, since the negatives are the hardest there are and the base rate
is 50%; it is here so a condition that bought recall with false positives would show it.

| group | `reshuffled` | `mixed_shuffled` | `diluted` | `single` |
|---|---|---|---|---|
| doxxing | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 0.966 [0.87, 1.00] |
| minors | 0.892 [0.78, 0.97] | 0.897 [0.79, 0.98] | 0.884 [0.78, 0.97] | 0.884 [0.78, 0.97] |

`minors` recall of 39% to 45% at 0.70 is not new: `benchmark/results/report.md` has 0.45 on the same
rows. It is a calibration fact about this category on this data, and it does not move with the batch.

## 4. The tests

### 4.1 Composition against `reshuffled`

Two measures per cell. The sign test on paired scores asks whether the distribution shifts at all,
the test that found spam's +0.19 in JEV-56. The paired change in the share over the line asks whether
a shift changes a decision. Holm over the twelve contrasts, `single` included so the correction
covers it.

**The doxxing items are not 150 independent texts each.** They are 16 templates per side with the
slots filled, and items from one template behave alike. So for doxxing the sign test counts templates
(a template moves up if its items' mean shift is positive), and every interval resamples whole
templates. Counting items would have handed four doxxing cells a "significant" label they do not
earn: item by item, `doxxing/positive/mixed_shuffled` is 42 up and 81 down, p = 0.0006; per template
it is 3 against 13, Holm p = 0.23. A `minors` row is its own cluster.

| contrast | clusters up/down | Holm p | mean score shift [95%] | share over the line, change [95%] |
|---|---|---|---|---|
| doxxing positive, `mixed_shuffled` | 3/13 | 0.234 | −0.010 [−0.015, −0.005] | +0.7 pts [+0.0, +2.0] |
| doxxing positive, `diluted` | 11/5 | 1.000 | +0.004 [+0.001, +0.008] | +0.0 pts |
| doxxing positive, `single` | 4/12 | 0.768 | −0.033 [−0.064, −0.009] | **−5.3 pts** [−15.4, +0.0] |
| doxxing hard neg., `mixed_shuffled` | 12/4 | 0.768 | +0.000 [−0.018, +0.011] | +0.0 pts |
| doxxing hard neg., `diluted` | 5/11 | 1.000 | −0.008 [−0.017, −0.001] | +0.0 pts |
| doxxing hard neg., `single` | 6/9 | 1.000 | +0.014 [−0.013, +0.062] | **+3.3 pts** [+0.0, +10.1] |
| minors positive, `mixed_shuffled` | 40/41 | 1.000 | +0.015 [−0.009, +0.038] | +2.4 pts [−4.7, +9.4] |
| minors positive, `diluted` | 42/35 | 1.000 | +0.003 [−0.026, +0.032] | +5.9 pts [−1.2, +14.1] |
| minors positive, `single` | 49/34 | 0.991 | +0.039 [+0.011, +0.068] | +5.9 pts [−1.2, +12.9] |
| **minors hard neg., `mixed_shuffled`** | **54/21** | **0.002** | +0.016 [−0.000, +0.033] | +0.0 pts |
| minors hard neg., `diluted` | 43/29 | 0.991 | +0.019 [+0.002, +0.037] | +1.2 pts [+0.0, +3.5] |
| minors hard neg., `single` | 35/41 | 1.000 | −0.002 [−0.022, +0.021] | +1.2 pts [+0.0, +3.5] |

A "+0.0 pts" with no interval is a cell where no item changed side between the two conditions, so
every resample gives zero. It means no decision changed, not that the change is known to be exactly
zero.

**What the rule predicted, cell by cell:**

- *Doxxing positives among fewer doxxing neighbours score lower.* `mixed_shuffled` goes that way,
  −0.010, and `diluted`, with far fewer doxxing neighbours, goes the other way, +0.004. Neither
  survives at the template level, and neither is within a tenth of the distance to a decision: these
  positives sit at 0.95 against a line at 0.80.
- *Doxxing hard negatives among doxxing score higher.* 12 templates up against 4, mean shift +0.000.
  Nothing.
- *Minors positives among fewer minors neighbours score lower.* 40 up, 41 down. Nothing.
- *Adult sexual text among minors content scores higher on `minors`.* **Yes, 54 up against 21, the one
  survivor, +0.016.** But among neutral chat, where the rule predicts nothing, it moves +0.019, the
  same size and the same direction. The sounder reading is that a batch made entirely of adult sexual
  text pulls each member's `minors` score slightly *down*, and any other composition releases it.
  That is a composition effect, and a real one; it is not the one the rule describes, and it moves no
  decision (4.7% false positives in both arms).

### 4.2 Membership, against the noise floor

The JEV-56 table: crossings of the shipped line against `pure`, McNemar against the `pure2` floor,
Holm over sixteen tests. Nothing survives. The largest are `doxxing/positive/single`, 9 crossings
against 0 (Holm p = 0.062, and all nine come from two templates, so the item-level p flatters it),
and `minors/positive/diluted`, 12 against 5 (Holm p = 1.000). `run.py analyse` prints the table.

Scores do move with membership, as they did for spam, without moving decisions often enough to
measure at this n. Mean absolute movement against `pure`:

| group | side | `pure2` | `reshuffled` | `mixed_shuffled` | `diluted` | `single` |
|---|---|---|---|---|---|---|
| doxxing | positive | 0.004 | 0.013 | 0.019 | 0.015 | 0.042 |
| doxxing | hard neg. | 0.009 | 0.029 | 0.029 | 0.024 | 0.050 |
| minors | positive | 0.018 | **0.081** | 0.082 | 0.103 | 0.105 |
| minors | hard neg. | 0.014 | 0.043 | 0.050 | 0.047 | 0.052 |

`minors` positives move 0.081 on a regrouping against 0.018 on a repeat, 4.5 times the floor. Spam
positives in JEV-56 moved 0.073 against 0.011. So a `minors` score has the same one-decimal
reproducibility per message that spam's has, and its positives sit around their line (mean 0.57
against 0.70), which is where that matters. At n = 85 the crossings it causes are 9 against a floor
of 5, which this data cannot separate from noise.

### 4.3 Alone

`single` is the production path for a cold, quiet channel: the lead filler at `m0`, the message at
`m1`, nothing else, because the conversation window is empty. JEV-57 found spam loses 21 points of
recall alone before the filler shipped and 9 after.

- **`doxxing` loses recall and precision alone**, the only category measured so far where being alone
  costs on both sides: 94.0% recall against 99.3%, 3.3% false positives against 0%. It is
  concentrated. Of the nine positives lost, eight are one template, a licence plate and the street a
  person parks on, whose mean falls from 0.90 in a batch to 0.69 alone. All five false positives are
  one template, "how do people even find someone's address from a username? asking for a privacy
  talk", whose mean rises from 0.42 to 0.79. Both are the borderline texts of this set: among
  neighbours the model is surer the plate is doxxing and the privacy question is not.
- **`minors` does not move alone** in any way this data can resolve: +0.039 on positives, the wrong
  direction for a context-starved question, and no change in either rate.

So neither category is better judged alone, and one is worse. What isolation would cost was the
question this measurement had to answer before anyone proposed it.

## 5. What this does not measure

- **Real doxxing.** The synthetic positives are unambiguous and sit at 0.95: they are the easy half of
  the category, and on the positive side the decision-level tests ask whether anything can pull 0.95
  under 0.80, which nothing here could. The rule's own mechanism, "is this data real, is this person
  private", barely applies to text whose data is fictional by construction, and the model may know
  that 555 numbers are. The score-level tests still speak; the decision-level ones need real labelled
  doxxing, which is JEV-11.
- **Power on `minors`.** 85 rows is all the labelled set has. The intervals on recall changes are about
  ±7 points wide, so a composition effect under roughly 10 points of recall is not excluded. What is
  excluded is an effect the size of REPORT2's `ai_generated` one, which moved a false-positive rate
  from 30% to 67%.
- **Chat.** The `minors` rows are moderation-eval prose, not chat, and grooming is a sequence of
  messages rather than one. That is context (JEV-18), not composition, and it is not tested here.
- **Precision in production.** The 1:1 precision above is on the hardest negatives at a 50% base rate.
  It shows that no condition trades recall for false positives, and nothing about a real channel.

## What to do

1. **No change to production.** No isolation, no per-category batching, no threshold move: nothing
   here supports one.
2. **Retire the rule as a design tool.** `BATCH_EFFECT.md` section 4 now points here. Whether a
   category is composition-sensitive is measured, as this folder does for about $0.23, not predicted.
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
