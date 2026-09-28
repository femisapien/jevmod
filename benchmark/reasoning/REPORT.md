# Does Jev return reasoning, and at what cost (JEV-15)

Run on 2026-09-27 against `jev-1.13.0`, 135 messages, 799,378 input tokens, **$0.0336** at the $0.042/M
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
3. **It is truthful and useful on 25 of 30 read by hand** (23 of 30 on a stricter reading; 95% interval
   roughly 66% to 93%), 27 of 30 truthful. Those 30 are almost all correct flags; see Limits.
4. **As a separate request explaining every flagged category it costs 880 input tokens per explained
   message**, 266 ms p50 (724 tokens and 238 ms for the top category alone), growing about half a token per
   character of message. Spread over every judged message at a 5% flag rate that is 44 tokens, +4.1% on the
   cheapest judgment (a full batch of nine) and +0.5% on a message padded alone. Asked inline in the judgment request it costs 1,060 tokens on every
   judged message, flagged or not: +97.6% on a full batch, +10.8% padded.
5. **It does not move the scores.** The inline arm shifts the category scores by 0.0036 on average, the
   same as sending the identical request twice (0.0037). A separate request cannot touch them at all.
6. **As asked here, it is not a second opinion.** Given a real flag it never disagreed (0 of 94). It
   explains the flag; with this prompt, which tells Jev the message was flagged, it does not check it.

## What was measured

135 messages: 67 from the red-team set (every row with a category, plus 20 clean), and 68 from the
benchmark set, stratified by the category the published v4 run flagged them under, plus clean ones. The
set is enriched on purpose: arm A flagged 94 of 134 (one message was skipped as too short in every arm).
Flags by top category: harassment 25, spam 23, scam 19, nsfw 14, selfharm 13. **Doxxing and minors were
not exercised** (one doxxing flag appears as a second category); their reason codes are untested.

| arm | what it sends | why |
|---|---|---|
| A | the judgment exactly as `Judge.judge()` builds it, nine messages plus the m0 filler, no padding | the baseline |
| B | A plus one Choice per message over every category's reason codes and `nothing` | the "extra field" option |
| A2 | A again, identical | how much a plain repeat moves the scores, to compare B's shift with |
| C single | one request per flagged message: a reason Choice for its top category and a span Choice | the companion, and what "on demand" costs |
| C batched | the same questions for every flagged message of a batch in one request | the cheaper companion |
| C every category | one request per flagged message, a reason and a span for every flagged category | added after the hand reading, see below |
| control | C single on 33 clean, unflagged messages, as if flagged under their highest-scoring category | can it say `not_it` |

A, B and A2 go through `jevmod.judge.Judge` itself; B only appends questions to the request Judge built,
so the judgment questions and state are byte for byte what production sends for an unpadded batch whose
messages carry no conversation context. Production attaches the channel's recent messages as `context` to
every message once a channel has history (`jevmod/core/service.py`); neither the judgment arms nor the
companion here carry it. The three judge arms were sent back to back for every batch, so drift hits all
three alike.

## Does asking for it change the scores

| comparison | pairs | mean abs | p95 | max | share > 0.03 | messages whose flag set changed |
|---|---|---|---|---|---|---|
| A2 vs A (repeat) | 938 | 0.0037 | 0.020 | 0.08 | 2.3% | 2 of 134 |
| B vs A (inline) | 938 | 0.0036 | 0.020 | 0.10 | 2.1% | 2 of 134 |
| B vs A2 | 938 | 0.0035 | 0.020 | 0.07 | 1.8% | 0 of 134 |

The inline Choice moves the scores no more than repeating the request does; the two messages whose flags
changed are the same two in both comparisons, so it was A that moved. The companion is a separate request
after the verdict, so it cannot move them by construction.

## Tokens, cost and latency

Output tokens are free (docs.typesafe.ai/models), so only input is priced.

| request | requests | messages | input tok / msg | output tok / msg | $ / 1,000 msgs | p50 | p95 |
|---|---|---|---|---|---|---|---|
| judge A | 15 | 134 | 1,086 | 149.4 | $0.0456 | 396 ms | 939 ms |
| judge B (inline) | 15 | 134 | 2,146 | 537.9 | $0.0901 | 448 ms | 1,353 ms |
| judge A2 | 15 | 134 | 1,086 | 149.4 | $0.0456 | 371 ms | 763 ms |
| companion batched | 15 | 94 | 502 | 116.5 | $0.0211 | 273 ms | 341 ms |
| companion single | 94 | 94 | 724 | 119.1 | $0.0304 | 238 ms | 303 ms |
| companion single, every flagged category | 94 | 94 | 880 | 174.2 | $0.0370 | 266 ms | 382 ms |

"$ / 1,000 msgs" is per message judged for the judge rows and per message explained for the companion rows.
With 15 requests per judge arm the p95 is the slowest request, and A and A2, the same request, differ by
25 ms at the median; B's +52 ms over A is therefore "small", not a measured cost.

Arm A is the cheapest a judgment gets: nine real messages sharing one request. Production padded a quiet
channel's small batch to ten positions until JEV-61 turned it off by default (`jevmod/core/service.py`); with
padding on, a message judged alone pays for a whole ten-position request: 9,775 tokens, the mean of arm A's 14 complete requests. The share each option adds is
therefore a range, from a full batch to a message padded alone:

| flag rate | companion, top category | companion, every flagged category | inline Choice |
|---|---|---|---|
| 1% | 7 tok / judged msg, +0.7% full, +0.1% padded | 9 tok, +0.8% full, +0.1% padded | 1,060 tok, +97.6% full, +10.8% padded |
| 2% | 14 tok, +1.3% full, +0.1% padded | 18 tok, +1.6% full, +0.2% padded | 1,060 tok, +97.6% full, +10.8% padded |
| 5% | 36 tok, +3.3% full, +0.4% padded | 44 tok, +4.1% full, +0.5% padded | 1,060 tok, +97.6% full, +10.8% padded |
| 10% | 72 tok, +6.7% full, +0.7% padded | 88 tok, +8.1% full, +0.9% padded | 1,060 tok, +97.6% full, +10.8% padded |

In money, at a 5% flag rate: $0.00185 per 1,000 judged messages for the companion on every flagged
category, $0.0445 for the inline Choice. The inline Choice costs so much because its 32 options (31 reason
codes and `nothing`) are sent once per message in the batch. That is the one inline design measured; a
smaller inline question (the category alone, say) would be cheaper and would add nothing the scores do not
already say.

## Quality: the 30 read by hand

A seeded sample of 30 single-mode rationales (`results/handread.md`), each read against the message.
**Truthful**: the sentence and the quoted part are true of the message. **Useful**: a moderator reading
only that line and the quote knows what to look at, beyond the category name they already see.

| | of 30 |
|---|---|
| truthful | 27 |
| useful | 25 |
| both | 25 |
| both, strict (also counting `rt_l4` and `oai331` as misses) | 23 |

The five misses, one line each (full notes in `handread.jsonl`):

- `oai7`, a short story about a teenager in therapy, explained as "hopelessness about the author's own
  life". False: it is fiction. The code's wording asserts the author, and Jev picked it anyway.
- `rt_l16` and `rt_e8`, a Nitro phishing link and a fake login page, explained under their spam flag as
  "advertises a product". Both were also flagged scam, within 0.01 of spam.
- `rt_e2`, a homoglyph Nitro giveaway, explained as "pushes an invite link". True, but it hides the scam.
- `oai1549`, true that it demeans a group, but the quoted part is the lesser sentence; the call to kill
  "these animals" is in the third.

The strict reading also fails `rt_l4` (a R$500 prize that asks for bank details, explained as
`fake_giveaway` where `credentials` names the danger better, though the quoted part is the right one) and
`oai331` (`insult` "aimed at a person" on a jab at a group of readers). Both are arguable, which is why the
headline is 25.

Three of the five are the same failure: a message flagged both spam and scam, explained only under spam.
38 of 94 flags carry more than one category, 28 of them spam and scam together. Explaining **every** flagged
category (the last companion row) gives those three a scam line too: `fake_giveaway` on all three, which is
true of `rt_l16` and `rt_e2` and close for `rt_e8`. It costs 880 tokens per message instead of 724.

**`fake_giveaway` and `credentials` are close on phishing that dangles a prize.** `fake_giveaway` wins 21
of the 28 spam and scam pairs, most of them real Nitro, skin or Robux giveaways where it is right. On the two
that also ask for a login or bank details it wins narrowly over `credentials`, which already exists (`rt_e8`
0.53 against 0.42, `rt_l4` 0.54 against 0.38). Both are true of those messages; a moderator is better served
by the one that names the danger. A third, `rt_e5` ("steamcommunity-login[.]com/verify your account or lose
it in 24h"), gets `lookalike_domain` over `credentials` by 0.77 to 0.23, although it is word for word the
"urgent account verification" in `credentials`. `lookalike_domain` is true of it too; the point is the same.
The fix is wording that makes `credentials` win whenever a message asks for a login, a code or bank
details, prize or lookalike link or not, and a re-read to check it.

**Cut spans can hide the evidence.** A part longer than 160 characters is cut before it is offered, so the
quote can miss the words that matter. 15 of 94 flagged messages had a cut part, and on 5 the chosen part was
a cut one (`rt_g2`, `oai7`, `oai1196`, `oai185`, `oai1603`). On `rt_g2` the "free nitro" link falls past the
cut, so no offered part contains it, and Jev still chose that part with p=0.90: the moderator would be shown
a quote about seller prices. Four of the 30 read by hand had a cut part (`oai1545`, `oai1598`, `oai1678`,
`oai7`), and on one, `oai7`, the chosen part was cut; that item failed on its reason code, not on the cut.

The quote is also of the normalized text (`jevmod.judge.normalize`: NFKC, combining and format characters
removed, spaces collapsed), which differs from what the user wrote on 31 of the 94 flagged messages.

## Agreement and the control

- Companion reason code, single vs batched: same on 86 of 94. Span: same on 62 of 64. Batched is 31%
  cheaper but gives a different code about one time in twelve, because every flagged message of the batch
  shares the state; single is what the hand reading judged.
- Inline code vs companion code: the same code on 69 of 94, the same category on 82 of 94. The inline arm
  names a category that crossed its line on 92 of 94. Ten of the twelve differences are spam and scam
  messages where the inline arm explained scam and the companion explained spam, the higher score; three of
  them (`rt_e2`, `rt_e8`, `rt_l16`) are hand-read misses. Another reason to explain every flagged category.
- `not_it` (the companion disagreeing with the flag): **0 of 94** real flags, in single and in batched, with
  a median p(not_it) of 0.00 and a maximum of 0.04. Across every flagged category, 1 of 133 pairs.
- Control, 33 clean unflagged messages sent as if flagged: `not_it` on 28, median p(not_it) 0.94. The
  controls are easy (the category they were sent under scored 0.01 to 0.28), and the five it explained
  anyway are clean messages that sound like the category: game banter (`rt_f1`, "kill you all in the next
  round") as a threat, a second-hand GPU sale (`rt_f11`) as a DM deal, a note on a game's gore setting
  (`rt_n5`) as gore, a concert listing (`oai637`) as advertising, and a prompt injection (`rt_i6`) as `other`.

So the companion can say "nothing here" when a message is plainly clean, but it does not second-guess a
flag Jev already raised. Of the six flags whose source labels them clean, four are arguably right (a cam ad,
male-enhancement spam, a pirate download listing, a real self-harm post) and two are false positives:
`oai7` (the story) and `cc161` (a friendly "Greg, get a job, your store is closed"), explained as `hopeless`
and `insult`. That is two cases, and the instruction opens with "A moderation system flagged this as X",
which invites agreement; a neutral wording was not tried. **A rationale that reads well on a false positive
is the risk to design for.**

## Recommendation for JEV-16

1. **A companion request, never inline.** The inline design measured costs 1,060 tokens on every judged message to explain the
   few that are flagged.
2. **Only for flagged messages, every flagged category, one message per request**, sent after the verdict
   and off its critical path, when the queue item is created. Not on demand when a moderator opens the item:
   - the saving is only on items nobody opens, and the whole thing is 44 tokens per judged message at a 5%
     flag rate;
   - the Discord log embed is posted at flag time and nobody "opens" it;
   - on demand needs the message text at open time, which the server does not have when
     `JEVMOD_QUEUE_TEXT` is off (`odd/decisions/jev-13-review-queue.md` in the private repository);
   - it would add 266 to 382 ms (p50 to p95 of the every-category request) to opening an item.

   If the request fails the item's `reasoning` stays null, which the JEV-13 queue item already allows.

   **Send the companion the same `context` the judgment had.** A flag the conversation caused, explained
   from the message alone, gets an invented reason, because the companion does not say `not_it` to a real
   flag. The cost with context is not measured here; it grows with the context the same way the judgment's
   does.
3. **Store codes, not text**: per category the reason code, and the chosen part as character offsets into
   the stored text (no offsets when text is not kept). The parts are cut from the normalized text, which
   differs from the raw text on a third of these messages, so either cut the parts from the raw text and
   send each one normalized, or keep a map from normalized to raw offsets; do not store normalized offsets
   against raw text. The UI renders the sentence from the code table, which makes it translatable into the
   six locales, and a code carries no message content.
4. **Do not cut a part that can be quoted.** Offer whole parts (split long sentences at clauses first), so
   the quote contains what it was chosen for. The cost of that is not measured here: cutting removed about
   25 characters per flagged message in this set, whose benchmark texts were already capped at 600
   characters, but on long messages every flagged category's span Choice resends the whole text. Bound it
   with a cap on the whole message rather than on each part, and measure it on long messages first.
5. **Word it as an explanation of the flag, not a verdict**: "Flagged as scam: a fake giveaway. See:
   (quote)". Never use `not_it` to dismiss anything and never present the rationale as agreement; it agreed
   with every flag in this run, false positives included. This fits the queue decision's rule that the
   suggestion is a label, not a filled button.
6. **Fix the table before shipping it**: `hopeless` must not assert "the author's own life" (fiction and
   quoted speech trip it); word `credentials` so it wins when a message asks for a login or bank details,
   prize or not; list scam before spam when both are flagged. Doxxing and minors codes need their own
   read before they are shown. Re-read 30 after the rewrite.
7. **Where it lives**: the reason codes are new V1 capability, so under the backlog rules they are built in
   the private hosted repository next to the queue, not in this engine. This directory is the measurement.

## Limits

- 135 messages, 94 flags, one run, one model version (`jev-1.13.0`).
- One reader, who also wrote the reason codes, and who read knowing what was flagged; not blind.
- The set is enriched and mostly English. The padded cost is arm A's ten-position request, not a padded
  request with real channel history in it.
- Latency is 15 requests per judge arm and 94 per companion mode.
- The reason codes were written here from `categories.json`; a different table would read differently.
  The quality number is for this table, not for the idea.
- **Quality was read almost only on correct flags.** 88 of the 94 flags carry a category label in their
  source, and only 2 of the 30 read by hand are labelled clean (`oai7` failed, `oai585` passed). A real
  community's flags hold a larger share of false positives, which is where a confident rationale does harm,
  and that share was not read. Of the 15 (message, category) flags outside their source's labels, the
  companion gave a positive reason on 14.
- No conversation context, in the judgment or the companion (see "What was measured").
- Companion cost grows with the message: about 614 + 0.50 tokens per character for the top category and
  774 + 0.48 per character for every category, fitted on messages of 220 characters on average and up to
  2,255. A set of longer messages would cost more than the 724 and 880 above.
- Two runner details the data was collected with, left as they are so the runner reproduces it, and not to
  be copied into JEV-16: the sentence splitter cuts dotted, obfuscated links (`discord . gg` in `rt_e3`),
  and the span options quote parts with Python's `repr`, so a part with a backslash or a quote reaches Jev
  escaped (6 parts).
