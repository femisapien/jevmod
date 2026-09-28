# What padding with real channel history buys over the filler alone

JEV-61. Runner `benchmark/real_neighbours/run.py`, raw rows `results/raw.jsonl`.

**Status: pre-registered, not yet run.** This section is committed and pushed before any paid request, so
git shows the order. The results are added below it in a later commit and do not edit it.

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
