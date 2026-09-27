# Does Jev return reasoning, and at what cost (JEV-15)

Run on 2026-09-27 against `jev-1.13.0`, 135 messages, 776,584 input tokens, **$0.0326** at the $0.042/M
list price. Runner: `run.py` in this directory. Raw outputs: `results/dataset.jsonl` (the messages),
`results/judge.jsonl` (every score of arms A, B and A2), `results/companion.jsonl` (every rationale),
`results/handread.md` and `results/handread.jsonl` (the 30 read by hand, with a note on each miss).
`python -m benchmark.reasoning.run report` prints every table below from those files.

## Short answer

1. **Jev does not generate reasoning, and cannot.** The `/v1/systemone` response has `model`, `answers` and
   `usage` and nothing else (OpenAPI 0.2.0, typesafe-sdk 0.6.0), and the docs say so: "System One models do
   not write replies, produce code, or generate explanations of their reasoning." There is no field to turn on.
2. **A rationale can be selected instead.** A Choice over reason codes (one clause of the category's
   criteria each, for example "a fake giveaway: free Nitro, skins, gift cards or crypto") and a Choice over
   the parts of the message ("which part should a moderator read first"). The moderator reads a sentence we
   wrote, picked by Jev, plus a quote from the message.
3. **It is truthful and useful on 25 of 30 read by hand**, 27 of 30 truthful.
4. **It costs 724 input tokens per explained message** as a separate request, $0.03 per 1,000 explained
   messages, 238 ms p50 and 303 ms p95. At a 5% flag rate that adds 3.4% to the cost of judging (4.1% when
   every flagged category is explained). Asked inline in the judgment request it adds 97.6% to every
   judgment, flagged or not.
5. **It does not move the scores.** The inline arm shifts the category scores by 0.0036 on average, the
   same as sending the identical request twice (0.0037). A separate request cannot touch them at all.
6. **It is not a second opinion.** Given a real flag it never disagreed (0 of 94), including on the two
   flags that are plainly false positives. It explains the flag; it does not check it.

## What was measured

135 messages: 67 from the red-team set (every row with a category, plus 20 clean), and 68 from the
benchmark set, stratified by the category the published v4 run flagged them under, plus clean ones. The
set is enriched on purpose: arm A flagged 94 of 134 (one message was skipped as too short in every arm).
Flags by top category: harassment 25, spam 23, scam 19, nsfw 14, selfharm 13. **Doxxing and minors were
not exercised** (one doxxing flag appears as a second category); their reason codes are untested.

| arm | what it sends | why |
|---|---|---|
| A | the judgment exactly as `Judge.judge()` builds it, nine messages plus the m0 filler | the baseline |
| B | A plus one Choice per message over every category's reason codes and `nothing` | the "extra field" option |
| A2 | A again, identical | how much a plain repeat moves the scores, to compare B's shift with |
| C single | one request per flagged message: a reason Choice for its top category and a span Choice | the companion, and what "on demand" costs |
| C batched | the same questions for every flagged message of a batch in one request | the cheaper companion |
| C every category | one request per flagged message, a reason and a span for every flagged category | added after the hand reading, see below |
| control | C single on 33 clean, unflagged messages, as if flagged under their highest-scoring category | can it say `not_it` |

A, B and A2 go through `jevmod.judge.Judge` itself; B only appends questions to the request Judge built,
so the judgment questions and state are byte for byte what production sends. The three were sent back to
back for every batch, so drift hits all three alike.

## Does asking for it change the scores

| comparison | pairs | mean abs | p95 | max | share > 0.03 | messages whose flag set changed |
|---|---|---|---|---|---|---|
| A2 vs A (repeat) | 938 | 0.0037 | 0.020 | 0.08 | 2.3% | 2 of 134 |
| B vs A (inline) | 938 | 0.0036 | 0.020 | 0.10 | 2.1% | 2 of 134 |
| B vs A2 | 938 | 0.0035 | 0.020 | 0.07 | 1.8% | 0 of 134 |

The inline Choice moves the scores no more than repeating the request does. The companion is a separate
request after the verdict, so it cannot move them by construction.

## Tokens, cost and latency

Output tokens are free (docs.typesafe.ai/models), so only input is priced.

| request | requests | messages | input tok / msg | output tok / msg | $ / 1,000 msgs | p50 | p95 |
|---|---|---|---|---|---|---|---|
| judge A | 15 | 135 | 1,078 | 148.3 | $0.0453 | 396 ms | 939 ms |
| judge B (inline) | 15 | 135 | 2,130 | 533.9 | $0.0895 | 448 ms | 1,353 ms |
| judge A2 | 15 | 135 | 1,078 | 148.3 | $0.0453 | 371 ms | 763 ms |
| companion batched | 15 | 94 | 502 | 116.5 | $0.0211 | 273 ms | 341 ms |
| companion single | 94 | 94 | 724 | 119.1 | $0.0304 | 238 ms | 303 ms |
| companion single, every flagged category | 94 | 94 | 880 | 174.2 | $0.0370 | 266 ms | 382 ms |

"$ / 1,000 msgs" is per message judged for the judge rows and per message explained for the companion rows.
Per 1,000 **judged** messages, at assumed flag rates (a community flags far less than this set does):

| flag rate | companion, top category | companion, every flagged category | inline Choice |
|---|---|---|---|
| 1% | $0.00030 (+0.7%) | $0.00037 (+0.8%) | $0.04419 (+97.6%) |
| 2% | $0.00061 (+1.3%) | $0.00074 (+1.6%) | $0.04419 (+97.6%) |
| 5% | $0.00152 (+3.4%) | $0.00185 (+4.1%) | $0.04419 (+97.6%) |
| 10% | $0.00304 (+6.7%) | $0.00370 (+8.2%) | $0.04419 (+97.6%) |

The inline Choice doubles the input because its list of 32 options (31 reason codes and `nothing`) is sent
once per message in the batch.

## Quality: the 30 read by hand

A seeded sample of 30 single-mode rationales (`results/handread.md`), each read against the message.
**Truthful**: the sentence and the quoted part are true of the message. **Useful**: a moderator reading
only that line and the quote knows what to look at, beyond the category name they already see.

| | of 30 |
|---|---|
| truthful | 27 |
| useful | 25 |
| both | 25 |

The five misses, one line each (full notes in `handread.jsonl`):

- `oai7`, a short story about a teenager in therapy, explained as "hopelessness about the author's own
  life". False: it is fiction. The code's wording asserts the author, and Jev picked it anyway.
- `rt_l16` and `rt_e8`, a Nitro phishing link and a fake login page, explained under their spam flag as
  "advertises a product". Both were also flagged scam, within 0.01 of spam.
- `rt_e2`, a homoglyph Nitro giveaway, explained as "pushes an invite link". True, but it hides the scam.
- `oai1549`, true that it demeans a group, but the quoted part is the lesser sentence; the call to kill
  "these animals" is in the third.

Three of the five are the same failure: a message flagged both spam and scam, explained only under spam.
38 of 94 flags carry more than one category, 28 of them spam and scam together. Explaining **every** flagged
category (the last companion row) gives those three a scam line too: `fake_giveaway` on all three, which is
true of `rt_l16` and `rt_e2` and close for `rt_e8` (`credentials` would be closer). It costs 880 tokens per
message instead of 724.

## Agreement and the control

- Companion reason code, single vs batched: same on 86 of 94. Span: same on 62 of 64. Batched is 31%
  cheaper but gives a different code about one time in twelve, because every flagged message of the batch
  shares the state; single is what the hand reading judged.
- Inline code vs companion code: the same code on 69 of 94, the same category on 82 of 94. The inline arm
  picks from all seven categories at once, so it sometimes explains a different category from the one that
  crossed its line.
- `not_it` (the companion disagreeing with the flag): **0 of 94** real flags, in single and in batched, with
  a median p(not_it) of 0.00 and a maximum of 0.04. Across every flagged category, 1 of 133 pairs.
- Control, 33 clean unflagged messages sent as if flagged: `not_it` on 28, median p(not_it) 0.94.

So the companion can say "nothing here" when a message is plainly clean, but it does not second-guess a
flag Jev already raised. Of the six flags whose source labels them clean, four are arguably right
(a cam ad, male-enhancement spam, a pirate download listing, a real self-harm post) and two are false
positives: `oai7` (the story) and `cc161` (a friendly "Greg, get a job, your store is closed"), explained as
`hopeless` and `insult`. **A rationale that reads well on a false positive is the risk to design for.**

## Recommendation for JEV-16

1. **A companion request, never inline.** Inline doubles the cost of every judgment to explain the few
   that are flagged, and adds 52 ms to the p50 of the judgment the bot waits on.
2. **Only for flagged messages, every flagged category, one message per request**, sent after the verdict
   and off its critical path, when the queue item is created. Not on demand when a moderator opens the item:
   - the saving is only on items nobody opens, and the whole thing costs +4.1% of judging at a 5% flag rate;
   - the Discord log embed is posted at flag time and nobody "opens" it;
   - on demand needs the message text at open time, which the server does not have when
     `JEVMOD_QUEUE_TEXT` is off (`odd/decisions/jev-13-review-queue.md` in the private repository);
   - it would add 240 to 300 ms to opening an item.

   If the request fails the item's `reasoning` stays null, which the JEV-13 queue item already allows.
3. **Store codes, not text**: per category the reason code, and the chosen part as character offsets into
   the stored text (no offsets when text is not kept). The UI renders the sentence from the code table,
   which makes it translatable into the six locales, and a code carries no message content.
4. **Word it as an explanation of the flag, not a verdict**: "Flagged as scam: a fake giveaway. See:
   (quote)". Never use `not_it` to dismiss anything and never present the rationale as agreement; it agreed
   with every flag in this run, false positives included. This fits the queue decision's rule that the
   suggestion is a label, not a filled button.
5. **Fix the table before shipping it**: `hopeless` must not assert "the author's own life" (fiction and
   quoted speech trip it); add a phishing or fake-login code under scam; list scam before spam when both
   are flagged. Doxxing and minors codes need their own read before they are shown.
6. **Where it lives**: the reason codes are new V1 capability, so under the backlog rules they are built in
   the private hosted repository next to the queue, not in this engine. This directory is the measurement.

## Limits

- 135 messages, 94 flags, one run, one model version (`jev-1.13.0`). The hand reading is one reader.
- The set is enriched and mostly English.
- The reason codes were written here from `categories.json`; a different table would read differently.
  The quality number is for this table, not for the idea.
