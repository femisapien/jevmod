# Whether two or three varied synthetic neighbours pay for a message judged alone

JEV-89. Runner `benchmark/synthetic_neighbours/run.py`, raw rows `results/raw.jsonl`.

**Status: pre-registered, not run.** This section is committed and pushed before any paid request.

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
