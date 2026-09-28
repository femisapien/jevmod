# What padding with real channel history buys over the filler alone

JEV-61. Runner `benchmark/real_neighbours/run.py`, raw rows `results/raw.jsonl`.

**Status: run, decided.** The pre-registration below was committed and pushed in `e5860d3` before any paid
request, and it is unchanged since: `git diff e5860d3 -- REPORT.md` touches only this status line and adds the
sections after it. **Verdict by the criterion: padding goes off by default.**

## Pre-registration (written 2026-09-28, before the run)

### The question

`ModerationService` pads a batch under ten messages from one channel with that channel's history
(`PAD_BATCH`, default on): the oldest history line at `m0`, the message at `m1`, up to eight more behind
it, all asked every question. JEV-67 measured the cost: a message judged alone costs **4.53 times** the
unpadded request, $0.41 against $0.09 per thousand judged messages, and padding is 92% to 96% of that
(`benchmark/context_cost/REPORT.md`). `JEVMOD_PAD_BATCH=0` keeps the filler at `m0` and the window as
the message's `context` field and drops the padding positions. What that switch trades away in spam
recall has never been measured on production's path; the arms in `BATCH_EFFECT.md` section 9 are not
production's padding.

### The criterion, taken from JEV-19 and applied unchanged

JEV-19 (`odd/decisions/jev-19-context-worth-its-cost.md` in the private repository) fixed it before this
existed: at least 600 spam messages, paired, McNemar at p < 0.05. **Padding stays on by default if the
recall gain is significant and the lower end of its 95% interval is at least 5 points. It goes off by
default if the upper end is under 5 points. Otherwise the sample grows.**

Made exact here, before the run:

- **Primary contrast: `clean_on` against `clean_off`**, 600 spam messages, spam recall at the shipped
  threshold 0.85, the same messages in both arms. The history is the ten most recent clean comments of
  the same channel. That is the case padding exists for, a quiet channel whose history is ordinary
  conversation, and it is the case a channel is in most of the time. The natural history of these
  YouTube streams is about half spam, which no Discord server's history is; deciding on it would decide
  on the favourable case.
- **Interval:** Newcombe's method 10 for a difference of paired proportions, 95%. **Test:** exact
  two-sided McNemar on the discordant pairs.
- **False-positive guard:** on the 600 clean messages of the same two arms, if padding raises the false
  positive rate at 0.85 with McNemar p < 0.05, padding does not stay on by default even if recall
  passes. At a spam rate of a few percent, one point of false positives on clean traffic flags more
  messages than five points of recall catches.
- **Inconclusive:** the sample grows to every eligible message (653 spam, 629 clean on these streams).
  If it is still inconclusive there, the default does not change and this report says inconclusive.
- **Secondary, reported with the same test and not deciding the default:** `natural_on` against
  `natural_off`, production on this channel as it was. If it passes and the primary does not, the
  finding is that padding pays only when the history is itself spam, and that is written down as the
  result, not used to keep the default.
- **Why five points is the bar.** Padding multiplies the model spend of every padded message by about
  4.5, and plans are priced at $0.089 per thousand (JEV-66). Five points of spam recall on a quiet
  channel is the smallest gain JEV-19 judged worth that; this report does not move the bar.

### The mechanism, stated as tests before the run

The issue lists three hypotheses for why a real batch of ten beats the filler. Each has an arm on the
first 300 spam and 300 clean messages, and the contrasts are Holm-corrected together:

1. **Variety** (`synth_on` against `none`): ten different, harmless, channel-agnostic chat lines as the
   history. If variety is what neighbours buy, this recovers most of `clean_on`'s gain over `none`.
2. **Same kind of neighbour** (`spam_on` against `clean_on`): ten spam comments from the same channel
   against ten clean ones. If this is large and `clean_on` against `none` is small, the 29.3% of
   section 9 does not transfer to a real channel, as the issue fears.
3. **Position** (`clean_pos` against `clean_on`): the same ten lines, the message moved from `m1` to a
   seeded index between 1 and 9.

Also reported, descriptively: in the natural arm, the lift by how many of the ten history lines were
spam, by the word overlap of the nearest neighbour, and by whether a neighbour shares a link with the
message; that is where repetition and raid patterns would show.

### What is not measured

- **Scam recall.** No message in the streams is labelled scam, so the report gives the share of each side
  over the scam line (0.75) in every arm and makes no recall claim.
- **Discord.** These are YouTube comments under music videos from 2013 to 2015, median about 50
  characters. The history is the channel's own, in its real order, but the age limit of the buffer
  (fifteen minutes) is not applied: every arm has a full window, which is JEV-67's ceiling case.
- **Harassment and the other categories.** Section 8 of `BATCH_EFFECT.md` found harassment does not
  move with the batch; this run records every category's score but the criterion is spam's.

## Results (added 2026-09-28, after the run)

**The run.** 7,200 rows: a 24-row pilot (three per arm) and the full plan of 7,176, in one resumed file, 0
unjudged, 46,567,859 billed input tokens, **$1.956** at $0.042 per million. That is input only, as in every other
benchmark here: output tokens are not billed (docs.typesafe.ai/models), and the runner does not record them. Padding-on arms ran as one pass and
padding-off arms as a second pass, each shuffled with a fixed seed. `clean_off` against `none`, which straddle
the two passes and differ only in the `context` field, is +1.0 points [-1.5, +3.6], p 0.58, so the passes do
not show a drift large enough to matter here. Every table comes from `python -m benchmark.real_neighbours.run
report` over `results/raw.jsonl`.

### Per arm (spam at 0.85, scam at 0.75, Wilson 95%)

| arm | n spam | spam recall | n clean | spam FPR | mean spam score, spam / clean | scam over line, spam / clean | tokens per judged message |
|---|---|---|---|---|---|---|---|
| `natural_on` | 600 | 27.3% [23.9, 31.0] | 600 | 0.0% [0.0, 0.6] | 0.625 / 0.046 | 5.0% / 0.0% | 9,386 |
| `natural_off` | 600 | 25.8% [22.5, 29.5] | 600 | 0.0% [0.0, 0.6] | 0.628 / 0.045 | 5.7% / 0.0% | 2,432 |
| `clean_on` | 600 | 21.3% [18.2, 24.8] | 600 | 0.0% [0.0, 0.6] | 0.520 / 0.035 | 6.3% / 0.0% | 9,439 |
| `clean_off` | 600 | 20.3% [17.3, 23.7] | 600 | 0.0% [0.0, 0.6] | 0.516 / 0.035 | 5.8% / 0.0% | 2,334 |
| `none` | 300 | 19.0% [15.0, 23.8] | 300 | 0.0% [0.0, 1.3] | 0.518 / 0.034 | 5.0% / 0.0% | 2,106 |
| `synth_on` | 300 | 28.0% [23.2, 33.3] | 300 | 0.0% [0.0, 1.3] | 0.576 / 0.048 | 6.7% / 0.0% | 9,509 |
| `spam_on` | 300 | 28.3% [23.5, 33.7] | 300 | 0.0% [0.0, 1.3] | 0.633 / 0.077 | 5.0% / 0.0% | 9,390 |
| `clean_pos` | 300 | 24.7% [20.1, 29.8] | 300 | 0.0% [0.0, 1.3] | 0.572 / 0.039 | 6.0% / 0.0% | 9,429 |

The absolute recall here is lower than in `BATCH_EFFECT.md` (19.0% for the filler alone against 26.7%
there): a different sample, drawn from the eligible messages of four streams. Compare arms within this table,
not across files.

### The decision, as pre-registered

| contrast | side | n | on | off | difference, points [Newcombe 95%] | discordant b / c | McNemar p |
|---|---|---|---|---|---|---|---|
| `clean_on` vs `clean_off` (**primary**) | spam | 600 | 21.3% | 20.3% | **+1.0 [-0.2, +2.2]** | 9 / 3 | 0.146 |
| `clean_on` vs `clean_off` | clean | 600 | 0.0% | 0.0% | +0.0 [-0.6, +0.6] | 0 / 0 | 1 |
| `natural_on` vs `natural_off` (secondary) | spam | 600 | 27.3% | 25.8% | +1.5 [+0.1, +2.9] | 13 / 4 | 0.049 |
| `natural_on` vs `natural_off` | clean | 600 | 0.0% | 0.0% | +0.0 [-0.6, +0.6] | 0 / 0 | 1 |

- **Primary: the upper end, +2.2 points, is under 5. Padding goes off by default.** The sample does not
  grow: the rule grows it only when the interval straddles 5.
- **Secondary:** significant at p 0.049 but +1.5 points with an upper end of +2.9, also under 5. Padding does
  not pay even on a channel whose history is mostly spam (for 297 of the 600 spam messages, nine or ten of
  the ten before it were spam).
- **The false-positive guard had no power at 0.85.** No clean message crosses the spam line in any arm, 0 of
  600 on and off, so the guard could not have fired. The mean spam score of clean messages moves +0.001.
- **The 600 are 497 distinct texts.** Targets are distinct comment ids, and these streams repeat spam verbatim
  ("Check out this video on YouTube:" alone many times), so the pairs are not all independent. Collapsed to one
  message per text the primary is +1.2 points (8 / 2, p 0.11), and a bootstrap that resamples texts gives
  [-0.3, +2.4]; the secondary is +2.0 (12 / 2, p 0.013) and [+0.2, +3.1]. Both upper ends stay under 5, so the verdict does not move.
- **What the one point is.** All 12 discordant pairs of the primary have both scores between 0.80 and 0.89, and
  the mean score difference is +0.005: messages sitting on the line and tipping either way, not a small shift
  of the distribution.
- **Cost:** padding makes a message judged alone 4.0 times the tokens of the same message unpadded here (9,439
  against 2,334), in line with JEV-67's 4.53x ceiling. Per thousand judged messages at list price that is about
  $0.40 against $0.10, for one point of recall.

### The mechanism (300 of each side)

The Holm column corrects over every row of `run.py`'s table, twelve contrasts on both sides, which is wider
than the family the pre-registration names: three contrasts, spam side. Both were written before the run and
they disagree; over the registered three, Holm gives `synth_on` vs `none` 4.5e-08, `spam_on` vs `clean_on`
0.00018 and `clean_pos` vs `clean_on` 0.049 (printed by `run.py report`). The last is significant in the
registered family, and item 3 below explains why it does not measure position anyway.

| first vs second | side | n | first | second | difference [Newcombe 95%] | b / c | McNemar p | Holm | mean score difference |
|---|---|---|---|---|---|---|---|---|---|
| `synth_on` vs `none` | spam | 300 | 28.0% | 19.0% | +9.0 [+5.7, +12.4] | 27 / 0 | 1.5e-08 | 1.8e-07 | +0.058 |
| `clean_on` vs `none` | spam | 300 | 21.7% | 19.0% | +2.7 [-0.2, +5.6] | 13 / 5 | 0.096 | 0.77 | -0.006 |
| `spam_on` vs `clean_on` | spam | 300 | 28.3% | 21.7% | +6.7 [+3.4, +10.1] | 23 / 3 | 8.8e-05 | 0.00088 | +0.121 |
| `natural_on` vs `clean_on` | spam | 600 | 27.3% | 21.3% | +6.0 [+3.5, +8.6] | 49 / 13 | 4.8e-06 | 5.3e-05 | +0.105 |
| `clean_pos` vs `clean_on` | spam | 300 | 24.7% | 21.7% | +3.0 [+0.2, +5.9] | 13 / 4 | 0.049 | 0.44 | +0.060 |
| `clean_off` vs `none` | spam | 300 | 20.0% | 19.0% | +1.0 [-1.5, +3.6] | 8 / 5 | 0.58 | 1 | -0.010 |

On the clean side every one of these is 0 / 0 at 0.85. Mean clean-side spam scores: `spam_on` 0.077,
`synth_on` 0.048, `clean_on` 0.035, `none` 0.034.

1. **Same kind of neighbour: confirmed, and it is what the issue feared.** Spam history beats clean history
   by 6.7 points, and the channel's history as it was (mostly spam before a spam message) beats clean history by 6.0. What
   neighbours buy depends on what they are, so section 9's arm (same-pool spam as neighbours) was the favourable
   case. The gain itself is not shown to be smaller: section 9 had +2.6 points (26.7% to 29.3%) and the channel's
   own clean history here buys +2.7 [-0.2, +5.6] over nothing, not significant, on a different sample.
2. **Variety: more than confirmed, in a direction the hypothesis did not state.** Ten fixed, varied,
   off-topic chat lines buy +9.0 points over the filler alone, 27 messages up and none down, more than the
   channel's own clean history does, and about as much as ten spam neighbours (`spam_on`, 28.3%). So being
   real is not what buys recall here; which property does, this run cannot say (`synth_on` and `spam_on`
   were never contrasted with each other, or `synth_on` with `clean_on`). The arm cannot say through which channel: the ten lines are in the buffer, so they are
   also every message's `context`, and there is no `synth_off` to separate the field from the positions. It is
   also one fixed set in one order. This is one set of ten lines on 300 messages, not a decision contrast, and it costs the
   same 4 to 4.5 times: it is a follow-up, not a change.
3. **Position: not answered, because the arm is confounded.** The judge builds `messages` with the real
   messages first and adds `m0` after, so production's JSON reads `m1, m0, m2, ...`. The runner's move
   rebuilt the dict as `m0, m1, m2, ...`, which changes the key order as well as the index. The rows it
   left at index 1 are production's request with only the key order changed, and on those 29 spam messages
   the spam score went up on 22 and down on 3 (sign test p 0.00016, mean +0.064; one recall flip); on the 31
   clean ones +0.007, 9 up and 4 down. Every index but one shows about the same +0.05 to +0.10 (index 4,
   n 36, shows +0.004), so what `clean_pos` measured is mostly key order. Exploratory, found after the run, and a follow-up of its own:
   putting `m0` first costs nothing, unlike padding.

### What the natural history carried (spam messages, `natural_on` against `natural_off`)

| spam among the ten | n | recall off | recall on | mean lift |
|---|---|---|---|---|
| 0-2 | 82 | 17.1% | 17.1% | -0.001 |
| 3-5 | 128 | 32.0% | 33.6% | +0.002 |
| 6-8 | 93 | 37.6% | 41.9% | -0.002 |
| 9-10 | 297 | 21.9% | 22.9% | -0.004 |

| nearest neighbour, word overlap | n | recall off | recall on | mean lift |
|---|---|---|---|---|
| < 0.2 | 377 | 29.4% | 31.6% | -0.000 |
| 0.2 to 0.5 | 97 | 29.9% | 26.8% | +0.003 |
| >= 0.5 | 126 | 11.9% | 15.1% | -0.013 |

Five spam messages share a link with a neighbour, and all five are caught with and without padding. 82 of the
600 had an exact copy of themselves in the ten, which the service drops. No bucket shows padding moving the
mean score. Whatever the history holds reaches the model through the `context` field, which padding-off keeps;
asking the model about the same lines as extra positions adds little on top: +1.5 points on this history, which
is measurable (p 0.049; [+0.2, +3.1] resampling texts) and under the five points padding had to buy.

### What changes

`JEVMOD_PAD_BATCH` defaults to off in `jevmod/core/service.py`. The filler at `m0` and the window as the
message's `context` stay; only the padding positions go. A quiet channel's message drops from about 4.5 times
to about 1.15 times the no-context request (JEV-67). `JEVMOD_PAD_BATCH=1` turns padding back on, and an
unrecognised value now falls back to the default, off, with the warning it already logged. Neither "pad only
small batches" (padding already applies only under ten) nor "use real history as neighbours" (that is what
padding is, and what this run measured) survives the criterion.

### Follow-ups, not pre-registered here and not shipped

Both were measured on 2026-09-29 in their own pre-registered runs, and neither ships: the key order in
`benchmark/key_order/REPORT.md` (JEV-88: +7.5 points, and a false-positive guard fired), the synthetic
neighbours in `benchmark/synthetic_neighbours/REPORT.md` (JEV-89: the best is +5.7 [+3.8, +7.6] at 1.73 times).
Both move every score up rather than separate better, so what they buy is a lower line.

- **Key order.** Send `m0` before `m1` in the request JSON. Free in tokens; this run's exploratory +0.064 on
  29 spam messages needs its own pre-registered, paired run, with a false-positive check that has power (a
  lower line or scores, since nothing clean crosses 0.85 on these streams).
- **Varied synthetic neighbours.** +9.0 points at about 4 times the cost; worth measuring with fewer lines
  (two or three positions) to see how much of it survives at a price near the filler's.

### Limits

- YouTube comments under music videos, median about 50 characters, not Discord chat. Spam recall at one line
  only; no scam labels, so the scam columns are shares over the line, not recall.
- Padding-on arms ran in one pass and padding-off arms in the next, minutes apart, so the primary contrast
  crosses passes. The drift check above (`clean_off` vs `none`) also changes the `context` field, so a drift
  cancelled by a context effect would not show; nothing in the run points to one, and the passes were close.
- The key-order reading assumes the service does not reorder keys; the client keeps insertion order and
  what the server does with it is not observable from here.
- One run per arm; no test-retest of identical requests except the accidental one in `clean_pos`, which is not
  identical in key order.
- The false-positive guard had no power at 0.85 (above). A lower line was not pre-registered and is not used
  to decide.
