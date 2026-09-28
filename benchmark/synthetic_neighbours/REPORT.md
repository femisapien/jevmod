# Whether two or three varied synthetic neighbours pay for a message judged alone

JEV-89. Runner `benchmark/synthetic_neighbours/run.py`, raw rows `results/raw.jsonl`.

**Status: run, decided.** The pre-registration below was committed and pushed in `6884302` before any paid
request and is unchanged since: `git diff 6884302 -- REPORT.md` touches only this status line and adds the
sections after it. **Verdict by the criterion: nothing ships.** No arm's interval clears five points; the best,
three lines of set A, buys +5.7 [+3.8, +7.6] at 1.73 times the tokens, and set B's three lines buy +2.0.

## Pre-registration (written 2026-09-28, before the run)

### The question

JEV-61 (`benchmark/real_neighbours/REPORT.md`, mechanism 2) found that ten fixed, varied, off-topic chat lines as
the neighbours of a message judged alone (`synth_on`) bought **+9.0 points** of spam recall [+5.7, +12.4] over the
filler alone, 27 messages up and none down in 300 spam, at about four times the tokens. It could not say through
which channel (the lines were both the message's `context` field and nine extra positions), it was one set in one
order, and its baseline had no channel history, where production's request now carries the ten comments before
the message as `context`. Padding is off by default since that run. A position costs about 930 tokens (JEV-67),
so two synthetic lines instead of the filler cost about 1.4 times the filler request and three about 1.8 times;
ten cost four times.

### Arms

Every request goes through `ModerationService.moderate` with padding off. The synthetic lines are passed as the
judge's `padding`, as `JEVMOD_PAD_BATCH` would pass the window: the first takes `m0` in place of the filler, the
rest follow the message. The key order is whatever the judge on this branch sends when the run starts (JEV-88
decides it first), and every row records it.

**Decision arms**, 600 spam and 300 clean messages drawn with seed 89 from JEV-61's eligible messages, each with
the ten comments before it as `context` (production's request for a quiet channel):

- `filler`: production, the filler at `m0`.
- `s2a`, `s3a`: the first two or three of JEV-61's ten lines (set A) as padding.
- `s2b`, `s3b`: the first two or three of a second set of ten, B, written in the runner before this run, sharing
  no line with A.

**Mechanism arms**, the first 300 spam and 100 clean, no channel history, as JEV-61's `none` and `synth_on`:
`none` (filler only), `field10` (set A as `context` only, the `synth_off` JEV-61 lacked), `pos10` (set A as
padding only), `both10` (both, JEV-61's `synth_on`). Reported, not deciding.

All arms run interleaved in one seeded order. Planned about 25 million billed input tokens, about $1.06; the
runner stops at 40 million.

### The criterion, from JEV-19

JEV-19's revisit trigger for padding: a cheaper neighbour ships only if its own pre-registered run shows **five
points of spam recall at a multiplier near the filler's**. Made exact:

An arm **passes** if, against `filler` on the 600 spam messages at 0.85, all hold:

1. the gain is significant after Holm over the four decision arms (exact McNemar, p < 0.05);
2. the lower end of its 95% Newcombe interval is at least **+5 points**;
3. its billed tokens are at most **1.75 times** `filler`'s on the same messages (JEV-19's ceiling for context);
4. on the 300 clean messages, the share over the line does not rise at p < 0.05 for spam (0.85 and 0.50), scam
   (0.75 and 0.50) or harassment (0.75 and 0.50).

**Ship k synthetic lines** (k = 2 or 3, the smaller if both qualify) only if **both** `s{k}a` and `s{k}b` pass: a
gain that holds for one set of lines is a property of those lines, not of variety. Shipping means the judge puts
k of set A's lines in a message's request when the service would otherwise send the filler alone. Otherwise
nothing ships, the report gives the verdict, and JEV-19 records it.

### What is not measured

- Batches: padding applies only under ten messages, and this measures one.
- Discord, and any other category's recall: YouTube comments, spam labels only; scam and harassment appear as
  false-positive guards on the clean side.
- Which lines are best. Two sets, first lines in their written order; this is not a search over lines.

## Results (added 2026-09-29, after the run)

**The run.** 6,100 rows: a pilot of two per arm and the full plan of 6,082, 0 unjudged, 25,207,557 billed input
tokens, **$1.059** at $0.042 per million (input only). All arms interleaved in one seeded order. The judge sent
its keys as it does in production (`m1, m0, ...`, JEV-88 changed nothing), and each row records the order and what
sat at `m0`. Tables come from `python -m benchmark.synthetic_neighbours.run report`.

### Per arm (spam at 0.85, Wilson 95%)

| arm | n spam | spam recall | n clean | clean over 0.85 | clean over 0.50 | tokens per message |
|---|---|---|---|---|---|---|
| `filler` | 600 | 27.0% [23.6, 30.7] | 300 | 0 | 1 | 2,448 |
| `s2a` | 600 | 31.3% [27.8, 35.2] | 300 | 0 | 1 | 3,356 |
| `s3a` | 600 | 32.7% [29.0, 36.5] | 300 | 0 | 1 | 4,259 |
| `s2b` | 600 | 29.0% [25.5, 32.8] | 300 | 0 | 1 | 3,353 |
| `s3b` | 600 | 29.0% [25.5, 32.8] | 300 | 0 | 1 | 4,259 |
| `none` | 300 | 16.7% [12.9, 21.3] | 100 | 0 | 1 | 2,111 |
| `field10` | 300 | 22.7% [18.3, 27.7] | 100 | 0 | 1 | 2,264 |
| `pos10` | 300 | 21.7% [17.4, 26.7] | 100 | 0 | 1 | 9,363 |
| `both10` | 300 | 27.0% [22.3, 32.3] | 100 | 0 | 1 | 9,516 |

### The decision, as pre-registered

| arm vs `filler` | n | arm | `filler` | difference, points [Newcombe 95%] | b / c | McNemar p | Holm | mean score difference | token multiplier | guards | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `s2a` | 600 | 31.3% | 27.0% | +4.3 [+2.7, +6.0] | 26 / 0 | 3.0e-08 | 8.9e-08 | +0.034 | 1.37x | none | no: lower end under 5 |
| `s3a` | 600 | 32.7% | 27.0% | +5.7 [+3.8, +7.6] | 34 / 0 | 1.2e-10 | 4.7e-10 | +0.043 | 1.73x | none | no: lower end under 5 |
| `s2b` | 600 | 29.0% | 27.0% | +2.0 [+0.7, +3.3] | 13 / 1 | 0.0018 | 0.0037 | +0.018 | 1.37x | none | no: lower end under 5 |
| `s3b` | 600 | 29.0% | 27.0% | +2.0 [+0.4, +3.6] | 17 / 5 | 0.017 | 0.017 | +0.024 | 1.73x | none | no: lower end under 5 |

- **Every arm helps and none helps enough.** All four gains are significant after Holm; no lower end reaches +5
  points, so no arm passes, and the rule needed both sets to pass at the same k. **Nothing ships**; padding stays
  off and a lone message keeps the filler at `m0`.
- **The lines matter more than their number.** Set A's first three buy +5.7, set B's first three +2.0, with the
  same count and the same cost. Whatever the gain is, it is a property of particular lines, which is what the
  two-set rule was there to catch.
- **No guard came near firing.** On the 300 clean messages nothing crosses spam 0.85 or 0.50, scam 0.75 or 0.50 in
  any arm, and harassment moves by one message at most.
- **Cost:** two lines are 1.37 times the filler request, three 1.73 times, in line with JEV-67's 930 tokens a
  position.

### The mechanism: field and positions (300 spam, 100 clean, no channel history)

| first vs second | n spam | first | second | difference, points [Newcombe 95%] | b / c | McNemar p | token multiplier |
|---|---|---|---|---|---|---|---|
| `both10` vs `none` (JEV-61's `synth_on`, replicated) | 300 | 27.0% | 16.7% | +10.3 [+6.9, +14.0] | 31 / 0 | 9.3e-10 | 4.50x |
| `field10` vs `none` (the lines as `context` only) | 300 | 22.7% | 16.7% | +6.0 [+3.3, +9.0] | 18 / 0 | 7.6e-06 | 1.07x |
| `pos10` vs `none` (the lines as positions only) | 300 | 21.7% | 16.7% | +5.0 [+2.3, +7.9] | 16 / 1 | 0.00028 | 4.43x |
| `both10` vs `pos10` | 300 | 27.0% | 21.7% | +5.3 [+2.7, +8.1] | 16 / 0 | 3.1e-05 | 1.02x |
| `both10` vs `field10` | 300 | 27.0% | 22.7% | +4.3 [+1.9, +6.9] | 13 / 0 | 0.00024 | 4.19x |

- **JEV-61's +9.0 replicates** (+10.3 on a different draw of 300).
- **The two channels add up.** The lines as the `context` field alone buy +6.0 at 1.07 times the tokens; as
  positions alone +5.0 at 4.4 times; both together about the sum. JEV-61's arm could not tell them apart. On this
  YouTube data the field alone is where the cheap part of the gain is.
- This is the case of a channel with no history. Production already fills the field with the channel's real
  history when it has any, which the decision arms carry, and there the positions on top buy +2.0 to +5.7.

### What any of it buys: a shift, not separation

Added after the run, descriptive, not part of the criterion. The same check JEV-88's report makes of the key order.

| arm | against | AUROC arm | AUROC against | arm at 0.85 | `against` reaches that recall at | clean over the line, arm / against there |
|---|---|---|---|---|---|---|
| `s2a` | `filler` | 0.9848 | 0.9853 | 188/600 | 0.81 (193) | 0 / 0 |
| `s3a` | `filler` | 0.9831 | 0.9853 | 196/600 | 0.80 (201) | 0 / 0 |
| `s2b` | `filler` | 0.9844 | 0.9853 | 174/600 | 0.83 (178) | 0 / 0 |
| `s3b` | `filler` | 0.9831 | 0.9853 | 174/600 | 0.83 (178) | 0 / 0 |
| `field10` | `none` | 0.9809 | 0.9808 | 68/300 | 0.81 (70) | 0 / 0 |
| `pos10` | `none` | 0.9812 | 0.9808 | 65/300 | 0.82 (66) | 0 / 0 |
| `both10` | `none` | 0.9802 | 0.9808 | 81/300 | 0.77 (81) | 0 / 0 |

No arm separates spam from clean better than its baseline: the area under the ROC curve is flat or slightly lower
in all seven. Every recall point an arm buys at 0.85 is on the baseline request at a lower line, 0.77 to 0.83,
with no more clean messages over it on these sets; JEV-61's ten lines are worth a spam line of 0.77. That is the
same finding as JEV-88's key order: what neighbours and order change is where the scores sit, not how well they
rank. Buying that with tokens or with request shape is buying a lower threshold, and a lower spam line is a
threshold decision with its own red-team gate (JEV-18's: a bare shortened link the red-team file calls clean scores
0.78 to 0.81 and would cross).

### What changes

Nothing in the engine. JEV-19's revisit trigger for padding ("a cheaper form of neighbour shown in its own
pre-registered run to buy five points at a multiplier near the filler's") did not fire.

### Limits

- YouTube comments under music videos, spam labels only; the clean side is 300 (decision) and 100 (mechanism), and
  nothing clean crossed a line in any arm, so the guards had little to find.
- Two sets of lines, their first two or three in written order; a search over lines might find a set that clears
  five points, and by the table above it would be finding a lower line.
- The mechanism arms have no channel history, a case production meets only on a channel's first message or after
  fifteen quiet minutes.
