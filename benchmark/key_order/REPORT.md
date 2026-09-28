# Whether the order of the keys in the request moves the scores

JEV-88. Runner `benchmark/key_order/run.py`, raw rows `results/raw.jsonl`.

**Status: pre-registered, not run.** This section is committed and pushed before any paid request.

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
