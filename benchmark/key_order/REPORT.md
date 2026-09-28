# Whether the order of the keys in the request moves the scores

JEV-88. Runner `benchmark/key_order/run.py`, raw rows `results/raw.jsonl`.

**Status: run, decided.** The pre-registration below was committed and pushed in `74627d0` before any paid
request and is unchanged since: `git diff 74627d0 -- REPORT.md` touches only this status line and adds the
sections after it. **Verdict by the criterion: do not ship.** The order raises spam recall by 7.5 points, and a
guard fires: on a message judged alone it also raises harassment scores on messages without that label. What it
does is move scores up, not separate better; the same spam recall is on the current request at a line 0.04 to 0.06
lower.

## Pre-registration (written 2026-09-28, before the run)

### The question

`Judge._request` builds `state["messages"]` with the real messages first and adds `m0` afterwards, so the JSON
Jev receives reads `m1, m0` for a message judged alone and `m1, ..., mN, m0` for a batch. The keys and the
questions are the same whatever the order; only the insertion order of one dict changes. JEV-61
(`benchmark/real_neighbours/REPORT.md`, mechanism 3) saw, in an arm built for another question, that sending
the same request with `m0` first raised the spam score of 22 of 29 spam messages (sign test p 0.00016, mean
+0.064, one recall flip at 0.85) and moved clean messages +0.007. That was exploratory, with padding on, found
after the run. Padding is now off by default, so production's request for a quiet channel is two positions:
`m1` (the message, with its window as `context`) and `m0` (the filler).

If the order buys recall, it is free: no token changes.

### Arms and sets

Every request goes through `ModerationService.moderate` with padding off, as production runs. The runner
reorders `state["messages"]` of the request the judge built and checks, on every request, that the SDK's own
encoder puts the keys on the wire in that order; it also stops if the judge ever stops sending `m0` last.

- `current`: as sent today. `m0_first`: by index, `m0` first. `sorted_lex`: string order (`m0, m1, m10, ...,
  m2`), what a JSON encoder with sorted keys produces; the same as `m0_first` under ten positions, so run in
  batches only. `repeat`: `current` sent again, the noise floor of an identical request.
- `yt`, lone: all 1,281 eligible messages of JEV-61's four dated YouTube streams, **653 spam** and 628 clean,
  each alone with the ten comments before it as its `context`. Arms `current`, `m0_first`, `repeat`.
- `hx`, lone: **353 harassment** (every `openai_moderation` row labelled H, HR or V, every Civil Comments row
  at toxicity 0.7 or more) and 500 without the label (the 250 Civil Comments rows at 0.1 or less, 250 seeded
  unlabelled `openai_moderation` rows). Same three arms.
- `rt`, lone: the 98 rows of `tests/data/redteam.csv`; its 27 scam rows are the only scam labels the repository
  has. `current` and `m0_first`. Descriptive only.
- `ytb`, batches of 25: the four streams in posting order, 61 batches, 1,508 messages (760 spam), the ten
  comments before each batch in the buffer. `hxb`: the `hx` set in batches of 25, 35 batches. Arms
  `current`, `m0_first`, `sorted_lex`.

All units and arms run interleaved in one seeded order, so a drift in the service loads every arm alike.
Planned about 30 million billed input tokens, about $1.30; the runner stops at 45 million.

### The criterion

**Primary contrast:** `m0_first` against `current` on `yt`, the 653 spam messages, spam recall at the shipped
line 0.85, paired. Exact two-sided McNemar; Newcombe's method 10 for the 95% interval.

**Ship `m0_first` in the judge (and the npm package) if and only if both hold:**

1. **It helps:** the primary difference is positive with McNemar p < 0.05.
2. **It hurts nothing.** None of these fires, each a paired McNemar at p < 0.05 in the harmful direction, on
   `yt`, `ytb`, `hx` and `hxb`, without correction for the number of checks (which makes a false alarm more
   likely, so it errs towards not shipping):
   - recall of the set's own label falls: spam at 0.85 on `yt`/`ytb`, harassment at 0.75 on `hx`/`hxb`;
   - on messages without the set's label, the share over the line rises, for spam (0.85), scam (0.75) and
     harassment (0.75), **and at 0.50 for each of the three**. The shipped lines have no power on these sets
     (JEV-61: no clean message crossed 0.85 in any arm), and 0.50 is the lowest a server can move a line to
     (`Policy.nudge` clamps at 0.50), so a rise there is a false positive some server would see.

If the primary is not significant, nothing ships and this report says there is no demonstrated gain; the sample
does not grow (653 is every eligible spam message the streams have).

**`sorted_lex` does not ship on this run.** If it beats `m0_first` on `ytb` spam recall at p < 0.05, that is
written down as a follow-up.

**Reported, not deciding:** the paired score shifts with sign tests (Holm over the four sets), the `repeat`
noise floor, harassment and scam per set, and the red-team rows.

### What is not measured

- Scam recall with power. 27 scam rows are all the labels there are.
- Discord. These are YouTube comments under music videos and public moderation sets.
- Why the order would matter. The server's handling of key order is not observable from here; this measures
  whether it does, not why.

## Results (added 2026-09-28, after the run)

**The run.** 13,695 rows: a pilot of two units per set and arm, then the full plan, then one resume, in one file.
6,886 request units, 23,232,991 billed input tokens, **$0.976** at $0.042 per million (input only, as in every
benchmark here). One request failed open (`hx`, `current`, `oai882`; the error was not recorded) and was asked again
by the resume, which is the row used. The other unjudged rows are `too short`, the pre-filter, the same messages in
every arm (the resume re-lists the lone ones at no cost). Pairs use only rows judged in both arms. Every request's key order
was checked against the SDK's own encoder before it was sent: `current` went out as `m1,m0`, `m0_first` as
`m0,m1`, and no request was reordered by the encoder. Tables come from `python -m benchmark.key_order.run report`.

### Per set and arm

| set | arm | n with the label | recall at the line [Wilson 95%] | n without | over the line | over 0.50 | tokens per judged message |
|---|---|---|---|---|---|---|---|
| yt | `current` | 653 | spam 26.6% [23.4, 30.2] | 628 | 0 | 1 | 2,433 |
| yt | `m0_first` | 653 | spam 34.2% [30.6, 37.9] | 628 | 1 | 6 | 2,433 |
| yt | `repeat` | 653 | spam 25.9% [22.7, 29.4] | 628 | 0 | 3 | 2,433 |
| hx | `current` | 352 | harassment 76.1% [71.4, 80.3] | 498 | 32 | 80 | 2,177 |
| hx | `m0_first` | 352 | harassment 77.3% [72.6, 81.3] | 498 | 37 | 95 | 2,177 |
| hx | `repeat` | 352 | harassment 76.4% [71.7, 80.6] | 498 | 32 | 80 | 2,177 |
| rt | `current` | 27 | scam 88.9% [71.9, 96.1] | | | | 2,117 |
| rt | `m0_first` | 27 | scam 88.9% [71.9, 96.1] | | | | 2,117 |
| ytb | `current` | 760 | spam 35.4% [32.1, 38.9] | 675 | 0 | 1 | 1,217 |
| ytb | `m0_first` | 760 | spam 43.8% [40.3, 47.4] | 675 | 0 | 2 | 1,217 |
| ytb | `sorted_lex` | 760 | spam 40.5% [37.1, 44.1] | 675 | 0 | 2 | 1,217 |
| hxb | `current` | 352 | harassment 73.0% [68.1, 77.4] | 498 | 29 | 73 | 1,051 |
| hxb | `m0_first` | 352 | harassment 73.6% [68.7, 77.9] | 498 | 27 | 72 | 1,051 |
| hxb | `sorted_lex` | 352 | harassment 73.3% [68.4, 77.6] | 498 | 29 | 74 | 1,051 |

The token count per message is identical across arms of a set, as it has to be: only the order changes.

### The decision, as pre-registered

| contrast | set | with the label? | line | n | first | second | difference, points [Newcombe 95%] | flips b / c | McNemar p | mean score difference | scores up / down |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `m0_first` vs `current` (**primary**) | yt | spam | spam 0.85 | 653 | 34.2% | 26.6% | **+7.5 [+5.3, +9.7]** | 52 / 3 | 1.5e-12 | +0.055 | 462 / 113 |
| `m0_first` vs `current` (**guard that fired**) | hx | not harassment | harassment 0.50 | 498 | 19.1% | 16.1% | **+3.0 [+1.4, +4.8]** | 16 / 1 | 0.00028 | +0.017 | 241 / 82 |

- **It helps:** +7.5 points of spam recall on a message judged alone, p 1.5e-12. In batches of 25, +8.4 [+6.2,
  +10.7] (72 / 8).
- **It hurts:** on the 498 messages not labelled harassment, judged alone, 16 go over 0.50 for harassment with
  `m0_first` that did not with `current`, and 1 the other way (p 0.00028). At the shipped 0.75 the same direction,
  +1.0 [-0.3, +2.5], 7 / 2, not significant. Every other guard (27 more checks, all in the runner's output) is quiet:
  the largest is spam over 0.50 on clean YouTube, +0.8 [-0.0, +1.9], 5 / 0, p 0.06.
- **So `m0_first` does not ship.** The rule asked for zero harm and there is harm, at the line the rule named.
- **Which messages the guards read.** The pre-registration says "messages without the set's label": the 628 clean
  YouTube comments for `yt`, the 498 non-harassment rows for `hx`. The runner as committed with it read "without the
  category's label" for spam and harassment, so it also counted the spam comments as "without harassment" and the
  harassment rows as "without spam". The first review found the divergence; the runner now reads the text's
  population, and the verdict is the same both ways: the one guard that fires reads the same 498 rows in both, and
  no other guard reaches p < 0.05 in either (the lowest is spam over 0.50 on clean YouTube, p 0.06).
- **The shift is a lone message's.** In batches of 25 spam recall still rises +8.4, but the scores move far less
  (mean +0.020 on spam, +0.003 on clean) and harassment does not move at all: 98 positives up and 95 down, sign p
  0.89. Sign tests on the positives' scores, Holm over the four sets: `yt` spam 2e-50, `ytb` spam 4.1e-20, `hx`
  harassment 0.00038, `hxb` harassment 0.89.

### What the order does: it moves scores up, it does not separate better

Added after the run, descriptive, not part of the criterion; it explains the verdict rather than making it.

| set | category | AUROC `current` | AUROC `m0_first` | difference [paired bootstrap 95%] | `m0_first` at the line: recall, over it without the label | `current` gets that recall at | there: recall, over it without the label |
|---|---|---|---|---|---|---|---|
| yt | spam | 0.9846 | 0.9822 | -0.0024 [-0.0056, +0.0005] | 223/653, 1/628 at 0.85 | 0.79 | 228/653, 0/628 |
| ytb | spam | 0.9941 | 0.9937 | -0.0004 [-0.0009, +0.0000] | 333/760, 0/675 at 0.85 | 0.81 | 343/760, 0/675 |
| hx | harassment | 0.9256 | 0.9235 | -0.0022 [-0.0053, +0.0011] | 272/352, 37/498 at 0.75 | 0.74 | 272/352, 34/498 |
| hxb | harassment | 0.9286 | 0.9285 | -0.0001 [-0.0023, +0.0018] | 259/352, 27/498 at 0.75 | 0.74 | 259/352, 29/498 |

- With `m0` first, a lone message's scores go up whatever it is: spam up on 462 spam messages and down on 113,
  and also up on 402 of 628 clean ones (mean +0.022); harassment up on both sides. The area under the ROC curve
  falls slightly in all four sets, and the bootstrap interval of the difference rules out a rise above +0.002 in
  every one of them.
- **Every recall point it buys is on the current request at a lower line**, with false positives within three
  messages either way on these sets: 0.79 instead of 0.85 for spam alone, 0.81 in batches. Changing the order is
  changing the threshold by another name, on a lone message for every category at once, and without saying so.
- **The red-team file shows the cost of that.** Of its 96 judged rows, `m0_first` gets 13 category verdicts wrong
  against 11 for `current`. The one new false positive is `g9`, a bare `http://bit.ly/3xYzAbC` the file calls clean:
  spam 0.81 with `current`, 0.85 with `m0_first`, over the line. That is the row that failed JEV-18's red-team gate
  when a lower spam line was proposed. A lower spam line did not ship then, and this is the same move.
- `sorted_lex` in batches sits between the two (+5.1 over `current`, -3.3 [-5.4, -1.2] under `m0_first`, p 0.003):
  key order is a knob on the scores, not a single switch.

### The noise floor

The same request sent twice (`repeat` against `current`) moves spam recall -0.8 [-1.9, +0.4] (4 / 9) and mean
scores by 0.0000 (225 up, 235 down); harassment +0.3 (3 / 2). An identical request is not answered identically, so
it was not served from a cache, and its flips go both ways. `m0_first` has four times as many discordant pairs (55
against 13) and 52 of its 55 go one way.

### What changes

Nothing in the engine. `Judge._request` keeps sending `m1, ..., mN, m0`, and the npm package, which builds the same
order, keeps it too, so the two stay in parity. If spam recall is to be bought with a lower line, that is a
threshold decision with its red-team gate (JEV-18's), not a side effect of the request's key order.

### Limits

- YouTube comments and public moderation sets, not Discord. Scam labels: 27 red-team rows, no power.
- The harassment negatives mix Civil Comments (clean by a crowd score) and unlabelled OpenAI moderation rows; of the
  16 that crossed 0.50, 9 are OpenAI and 7 Civil Comments, so the guard does not rest on one source.
- One run per arm plus one repeat of `current` on the lone sets; the batch sets have no repeat.
- Why the server's scores depend on key order is not observable from here.
