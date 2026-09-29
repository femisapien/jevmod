# What a line of community state buys in verdicts

JEV-30, experiment D. Run on 2026-09-29 with `benchmark/community_state/run.py` against the live API, one
machine, one key, cache off, padding off (the default since JEV-61), through `ModerationService.moderate` with
the lead-up in its `ConversationBuffer`. Raw rows in `results/raw.jsonl` (one line per row, arm and repeat,
every category's score, billed tokens, the state line exactly as it went on the wire), the blind relabelling
in `results/blind_labels.jsonl`. Every table below is printed by `python -m benchmark.community_state.run report`
(and `report --agreed-only`).

**The run cost $0.099**: 2,359,524 input tokens at $42 per billion, 1,068 judgements (178 rows, three arms,
two repeats), none unjudged. The criterion was fixed in the runner's docstring and pushed in `9948223` at
11:59:26; the first paid request is stamped 11:59:49.

## The short answer

1. **The whole line (`full`) passes the pre-registered criterion, so it ships, on by default.** Pooled recall at
   the shipped thresholds goes from 59% with the window alone to 90%, the false-positive rate stays at 21%,
   gain +32 points (97.5% interval +20 to +46), 20 rows right only with it and 0 only without. The channel
   part alone (`chan`) also passes (+11, +4 to +21), and `full` beats it by +21 points (+11 to +31), so rule 3
   picks `full`. On the rows where the blind labeller agrees with the authors (`--agreed-only`, 99 rows),
   `full` still passes (+42, 97.5% lower end +20) and `chan` does not (+0).
2. **What does the work is the message's own part, and mostly for spam.** "This message: 16 copies by 11
   accounts/60s" is what the window cannot say, because the window drops every line identical to the one judged.
   Spam recall 36% to 96% (+60, interval +40 to +79); scam 69% to 92% (+23, interval from 0); harassment 76% to
   84% (+8, interval 0 to +20). The channel part (rate, newcomers, flagged counts, open event) bought +20 for
   spam and nothing for harassment; on the agreed rows it bought nothing at all.
3. **It adds, it never clears.** The state raised scores on incident halves; it did not lower them on calm
   halves. The 50 innocent halves of the pairs were flagged 24 times in every arm (mean score 0.66, 0.67,
   0.68). A calm-channel line does not talk the model out of a suspicious-looking message, so the state
   buys recall, not precision. This row set cannot show a false-positive cut, and none is claimed.
4. **Bystanders and busy chat, the guards: no verdict moved.** On 30 innocent lines during an incident
   (someone asking what is going on, calling the mods, the target answering, a defender replying to the
   target) and 35 innocent lines in busy normal chat (hype, friendly raids, birthday wishes), exactly the
   same rows cross a line in every arm: 0 of 30 and 1 of 35. Below the lines the busy rows drift up
   (`full` +0.036, 95% interval +0.014 to +0.064, under the +0.10 guard), and the drift is where it was
   expected: a hype chant copied by many accounts. `spam-b13` ("W streamer W chat W everything", 38 copies
   by 33 accounts) goes from 0.27 to 0.51 spam, `spam-b15` from 0.10 to 0.32. None is near 0.85, but this is
   the case to watch in production (last section).
5. **Harassment during pile-ons is not shown to benefit.** The blind labeller called every one of the 20
   harassment pair closings a violation on its own ("nobody asked for your opinion, just leave"), so those
   pairs do not isolate what the state adds, and on the agreed rows harassment has only its 5 controls.
   Telling the model the addressee "got 8 msgs from 5 users/5min" moved 2 of 20 incident halves over 0.75.
6. **Cost: +41 billed tokens a message alone, 1.019x.** The line is 96 characters on average, 151 at most (38
   estimated tokens), inside the 50 JEV-19 gives it. Latency is unchanged (median 256 to 257 ms in every arm).

## The data

178 rows in `data/<category>.jsonl`, written by model authors from the brief in `BRIEF.md`: spam 70, harassment
75, scam 33. JEV-64's labelled multi-party conversation set had not merged when this ran (`gh pr list` on
2026-09-29 shows no JEV-64 pull request), so the rows are constructed.

| kind | spam | harassment | scam | label | what it tests |
|---|---|---|---|---|---|
| `pair_pos` + `pair_neg` | 20 + 20 | 20 + 20 | 10 + 10 | true / false | the same topic, lead-up and closing byte for byte; only the state differs. With the window alone both halves are one request, so at most one can be right |
| `event_neg` | 10 | 15 | 5 | false | an incident is open and the closing is innocent |
| `busy_neg` | 15 | 15 | 5 | false | a busy normal channel (rate 3x to 15x, no event) and a line an over-eager filter might catch |
| `control_pos` | 5 | 5 | 3 | true | a clear violation in a calm channel |

Two hand edits, made after the authors and before any paid call, and recorded in the runner's docstring:

- Every `event_neg` row but `harassment-e04` had the wave's copy count, or the victim's counts, written into
  its own message part, which describes the closing line. A bystander's "is this a raid?" is not copied 18
  times. Those fields were set to 0; `harassment-e04` quotes the spam line itself and keeps them.
- Fifteen negatives were added where the message part is high for an innocent reason, because that is where
  it can hurt: a hype chant many accounts type at once (`spam-b11` to `b15`, 21 to 64 copies), many people
  congratulating one person (`harassment-b11` to `b15`, the target got 17 to 46 messages), and a defender
  replying to the target of a pile-on (`harassment-e11` to `e15`).

**Blind second labeller** (a model, shown topic, lead, closing and the `full` line, not the labels): agrees
on 138 of 178 (78%). It agrees on every `pair_pos`, `event_neg` and `control_pos`, 34 of 35 `busy_neg`, and
only 11 of 50 `pair_neg`: it reads most of the "ambiguous" closings as violations without any incident
("send 0.1 to this wallet and get 0.2 back instantly" is a scam in any channel). That is a fault in the
construction, not the labeller: the authors were asked for closings a moderator could not call without the
state, and mostly wrote closings that are suspicious on their own. It is why `--agreed-only` exists, and the
decision holds there.

## The arms

| arm | what the model sees |
|---|---|
| `win` | the conversation window only. What production sends today |
| `chan` | the window plus `channel: 7.0x usual rate, 25 new accounts/5min, flagged/5min spam 9, open event spam wave E2` |
| `full` | the same plus `; this message: 16 copies by 11 accounts/60s` (and, when it addresses someone, `its target got 8 msgs from 5 users/5min`) |

The line goes out as a `community_state` field beside `context` on the judged message, rendered by
`jevmod.core.context.render_state` from a `CommunityState` of counts, ratios, known category names and known
event types. Nothing a user typed can reach it.

## Recall and false-positive rate at the shipped thresholds

Spam 0.85, scam 0.75, harassment 0.75; a row's score is the mean of its two repeats; intervals are percentile
bootstraps over scenarios (a pair is one scenario), 2,000 resamples.

| category | arm | recall | 95% CI | FPR | 95% CI | AUROC |
|---|---|---|---|---|---|---|
| spam | win | 36% of 25 | 17 to 55 | 9% of 45 | 2 to 19 | 0.808 |
| spam | chan | 56% of 25 | 36 to 76 | 9% of 45 | 2 to 19 | 0.870 |
| spam | full | 96% of 25 | 86 to 100 | 9% of 45 | 2 to 19 | 0.972 |
| harassment | win | 76% of 25 | 58 to 92 | 28% of 50 | 16 to 41 | 0.832 |
| harassment | chan | 76% of 25 | 58 to 92 | 28% of 50 | 16 to 41 | 0.855 |
| harassment | full | 84% of 25 | 68 to 96 | 28% of 50 | 16 to 41 | 0.878 |
| scam | win | 69% of 13 | 43 to 92 | 30% of 20 | 11 to 52 | 0.783 |
| scam | chan | 85% of 13 | 64 to 100 | 30% of 20 | 11 to 52 | 0.825 |
| scam | full | 92% of 13 | 75 to 100 | 30% of 20 | 11 to 52 | 0.846 |
| all | win | 59% of 63 | 47 to 70 | 21% of 115 | 14 to 28 | 0.815 |
| all | chan | 70% of 63 | 58 to 81 | 21% of 115 | 14 to 28 | 0.853 |
| all | full | 90% of 63 | 83 to 97 | 21% of 115 | 14 to 28 | 0.908 |

The false-positive rates are properties of this set: every false positive is an innocent pair half, most of
which the blind labeller calls a violation too.

## The pre-registered criterion

A format passes against `win` when (a) the pooled gain, recall change minus FPR change, has its 97.5% lower
end above zero; (b) no category's 95% interval of the gain lies wholly below zero; (c) on `busy_neg`, rows with
any enabled category over its line rise by at most 1 and the 95% upper end of the mean change in the row's own
category is under +0.10; (d) the same on `event_neg`; (e) at most one `control_pos` flagged under `win` is lost.

### `chan`

| group | recall change | FPR change | gain | 95% CI | 97.5% CI | right only with | only without | McNemar p |
|---|---|---|---|---|---|---|---|---|
| spam | +20 | +0 | +20 | +5 to +38 | +4 to +41 | 5 | 0 | 0.0625 |
| harassment | +0 | +0 | +0 | +0 to +0 | +0 to +0 | 0 | 0 | 1 |
| scam | +15 | +0 | +15 | +0 to +36 | +0 to +40 | 2 | 0 | 0.5 |
| all | +11 | +0 | +11 | +5 to +20 | +4 to +21 | 7 | 0 | 0.0156 |

`busy_neg` 1 of 35 over a line with `chan`, 1 with `win`, mean change +0.018 [+0.005, +0.038]: pass. `event_neg`
0 and 0, +0.002 [-0.000, +0.003]: pass. Controls lost 0 of 13. **`chan` passes.**

### `full`

| group | recall change | FPR change | gain | 95% CI | 97.5% CI | right only with | only without | McNemar p |
|---|---|---|---|---|---|---|---|---|
| spam | +60 | +0 | +60 | +40 to +79 | +38 to +83 | 15 | 0 | 6.1e-05 |
| harassment | +8 | +0 | +8 | +0 to +20 | +0 to +23 | 2 | 0 | 0.5 |
| scam | +23 | +0 | +23 | +0 to +47 | +0 to +50 | 3 | 0 | 0.25 |
| all | +32 | +0 | +32 | +21 to +44 | +20 to +46 | 20 | 0 | 1.91e-06 |

`busy_neg` 1 of 35 with `full`, 1 with `win`, mean change +0.036 [+0.014, +0.064]: pass. `event_neg` 0 and 0,
+0.002 [-0.001, +0.005]: pass. Controls lost 0 of 13. **`full` passes.**

`full` against `chan`, pooled gain +21 points [+11, +31]. **Rule 3: both pass and `full` beats `chan` with a
lower end above zero, so `full` ships.**

### On the agreed rows only (secondary, `report --agreed-only`)

Every scenario with a row the blind labeller disagreed with is dropped: 99 rows (11 pairs, 30 `event_neg`, 34
`busy_neg`, 13 controls).

| format | spam | harassment | scam | pooled gain | 97.5% CI | busy / bystander / controls |
|---|---|---|---|---|---|---|
| `chan` | +0 | +0 | +0 | +0 | +0 to +0 | pass / pass / pass; **does not pass** (a) |
| `full` | +64 | +0 | +20 | +42 | +20 to +65 | pass / pass / pass; **passes** |

Recall there is 54% with `win` and 96% with `full`; FPR 0% in every arm.

## By kind of row

The row's own category at or over its line, and its mean score.

| category | kind | rows | win | chan | full | mean score win / chan / full |
|---|---|---|---|---|---|---|
| spam | pair_pos | 20 | 4 | 9 | 19 | 0.55 / 0.71 / 0.94 |
| spam | pair_neg | 20 | 4 | 4 | 4 | 0.55 / 0.55 / 0.55 |
| spam | event_neg | 10 | 0 | 0 | 0 | 0.03 / 0.03 / 0.03 |
| spam | busy_neg | 15 | 0 | 0 | 0 | 0.08 / 0.10 / 0.14 |
| spam | control_pos | 5 | 5 | 5 | 5 | 0.98 / 0.98 / 0.98 |
| harassment | pair_pos | 20 | 14 | 14 | 16 | 0.74 / 0.79 / 0.86 |
| harassment | pair_neg | 20 | 14 | 14 | 14 | 0.74 / 0.74 / 0.77 |
| harassment | event_neg | 15 | 0 | 0 | 0 | 0.03 / 0.03 / 0.03 |
| harassment | busy_neg | 15 | 0 | 0 | 0 | 0.08 / 0.08 / 0.08 |
| harassment | control_pos | 5 | 5 | 5 | 5 | 0.99 / 0.99 / 0.99 |
| scam | pair_pos | 10 | 6 | 8 | 9 | 0.73 / 0.84 / 0.87 |
| scam | pair_neg | 10 | 6 | 6 | 6 | 0.73 / 0.75 / 0.74 |
| scam | event_neg | 5 | 0 | 0 | 0 | 0.02 / 0.02 / 0.02 |
| scam | busy_neg | 5 | 0 | 0 | 0 | 0.06 / 0.13 / 0.12 |
| scam | control_pos | 3 | 3 | 3 | 3 | 0.97 / 0.97 / 0.97 |

Pairs with both halves right: 0 of 50 with `win` (the design forces it), 7 with `chan`, 20 with `full` (spam 15
of 20, harassment 2 of 20, scam 3 of 10).

Negatives with any enabled category over its line: `pair_neg` 24 / 24 / 24, `event_neg` 0 / 0 / 0, `busy_neg`
1 / 1 / 1 in every arm.

### The hard negatives, one by one (spam or harassment score, mean of two repeats)

| row | what | win | chan | full |
|---|---|---|---|---|
| `spam-b11` | "LETS GOOOOO IMMORTAL", 48 copies by 41 accounts | 0.02 | 0.02 | 0.07 |
| `spam-b12` | "GG GG GG we did it chat", 55 by 44 | 0.03 | 0.03 | 0.09 |
| `spam-b13` | "W streamer W chat W everything", 38 by 33 | 0.27 | 0.30 | 0.51 |
| `spam-b14` | "WORLD RECORD WORLD RECORD", 64 by 52 | 0.05 | 0.05 | 0.11 |
| `spam-b15` | "team blue team blue team blue", 21 by 17 | 0.10 | 0.11 | 0.32 |
| `harassment-b11`..`b15` | "@Lina happy birthday" and four more, target got 17 to 46 msgs | 0.01 to 0.07 | same | 0.01 to 0.08 |
| `harassment-e11`..`e15` | a defender replying to the pile-on's target, target got 6 to 11 msgs | 0.02 to 0.07 | 0.02 to 0.08 | 0.03 to 0.10 |

A copy count moves spam scores on innocent chants by 0.05 to 0.24; telling the model the addressee is
receiving many messages moves harassment scores on congratulations and defenders by at most 0.03.

## Repeat noise and cost

Verdicts flipping between the two repeats: `win` 0 of 178, `chan` 0, `full` 3; mean absolute difference 0.008
in every arm.

| arm | billed tokens per judged message | x win | added | state line chars, mean / max | ms median | ms p95 |
|---|---|---|---|---|---|---|
| win | 2,185 | 1.000x | +0 | 0 / 0 | 256 | 363 |
| chan | 2,217 | 1.015x | +33 | 70 / 101 | 257 | 374 |
| full | 2,226 | 1.019x | +41 | 96 / 151 | 256 | 331 |

A message alone, so the added tokens are absolute; in a batch of 25 at about 1,000 tokens a message, +41 is
about +4%. JEV-19 budgeted 50 estimated tokens for this part, about 64 billed; the longest line here is 38
estimated.

## What ships

The state line exactly as measured in `full`, rendered by `jevmod.core.context.render_state`, at most 50
estimated tokens (`STATE_TOKENS`), sent as `community_state` on the judged message. Fields, all optional:

| field | printed as | source (hosted, not in this package) |
|---|---|---|
| `rate_x` | `7.0x usual rate` | rate against the channel baseline (JEV-70) |
| `newcomers_5m` | `25 new accounts/5min` | JEV-28's newcomer signal |
| `flagged_5m` | `flagged/5min spam 9` (the top two categories this package knows) | the engine's own flags |
| `event`, `event_level` | `open event spam wave E2`, or `no open event` when a rate is known | JEV-26, JEV-27 |
| `copies_60s`, `copies_accounts` | `this message: 16 copies by 11 accounts/60s` | JEV-28's similarity signal, for this line |
| `target_5m`, `target_users` | `its target got 8 msgs from 5 users/5min` | JEV-28's targeting signal, for this line's addressee |

Parts are admitted greedily in order of worth (event, copies, target, rate, flags, newcomers): a part that does
not fit is skipped and a later, shorter one may still enter. At 50 tokens the budget never binds today: every
field at its largest gives 189 characters, under 200; `tests/test_community_state.py` exercises the cut with a
smaller budget. Identical lines in one batch are one position whatever their states (each copy of a wave carries
its own count), asked with the state of the latest copy, and the verdict is cached under every copy's own key;
a count that is not a finite number prints as 0 or `999+` and fails nothing. It is on by default under `JEVMOD_FULL_CONTEXT` (off sends nothing and computes every cache key
as before); a message whose caller gives no `community` goes out byte for byte as before, which is every caller
today. The npm package has no per-message context field, so it carries no state and needs no change; its cache
key is unchanged because the line is appended to the key only when there is one.

## What this does not show

- **Real traffic.** The rows are constructed by models to make the state matter, and the blind labeller is a
  model. How often production has a line whose copies or target decide it is unmeasured; JEV-64's multi-party
  set, when it lands, is the first place to re-run this.
- **The detectors.** The state here is written by hand and correct by construction. In production it comes from
  JEV-26, JEV-27 and JEV-70, and a wrong copy count reaches the model exactly as a right one does.
- **The bystander guard on the message part is thin.** After the edit that zeroed the bystanders' own counts,
  only 6 of the 30 `event_neg` rows (`harassment-e04`, `e11` to `e15`) carry a message part, so on the other 24
  `full` sends what `chan` sends. On those 6 no verdict moved and the largest rise was 0.04.
- **Harassment.** The harassment pairs were not ambiguous to the blind labeller, so whether the target counts
  help against a pile-on is open (+8 points, interval from 0).
- **The hype-chant drift.** A copy count lifts innocent chants by up to 0.24 spam. None came near 0.85 here,
  at 21 to 64 copies. A chat whose chants run into the hundreds of copies, or whose chant carries a link, is
  the first place a false positive from this line would appear. The detector can leave a line's copies out
  during the legitimate-spike windows JEV-28 already defines (first 5 minutes of a stream, 3 minutes after a
  raid or host) without any change to this package.
