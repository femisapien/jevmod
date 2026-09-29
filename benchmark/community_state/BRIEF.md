# Brief given to each data author (JEV-30)

This is the brief each author received, verbatim apart from `{CATEGORY}`, `{CRITERIA}` and the counts.

---

You are writing labelled test rows for a moderation benchmark. A chat moderation engine judges one
closing message, and sees (a) the channel topic, (b) up to ten earlier messages in the channel as plain
text with **no author names** (the "window"; any earlier line byte-identical to the closing line is
removed from it before the engine sees it), and, in some arms, (c) a structured summary of the
**community state**: what is happening in the channel right now. The question being measured is whether
(c) changes the verdict on the closing line for the better.

Category: **{CATEGORY}**. The engine's criteria for it, which your labels must follow:

{CRITERIA}

Write rows as JSON Lines to `benchmark/community_state/data/{CATEGORY}.jsonl` (UTF-8, one object per
line, no other file). Fields:

```json
{"id": "{CATEGORY}-p01-pos", "scenario": "{CATEGORY}-p01", "category": "{CATEGORY}",
 "kind": "pair_pos", "label": true, "topic": "a neutral channel topic",
 "lead": ["earlier message 1", "..."], "closing": "the line being judged",
 "state": {STATE}, "why": "one sentence for the label"}
```

`state` has this shape (every field required; use 0 or null where nothing applies):

```json
{"rate_x": 12.0, "newcomers_5m": 40, "flagged_5m": {"spam": 8, "harassment": 3},
 "event": {"type": "spam_wave", "level": "E2"},
 "copies_60s": 13, "copies_accounts": 9, "target_5m": 0, "target_users": 0}
```

- `rate_x`: messages per minute now divided by the channel's usual rate (1.0 is normal).
- `newcomers_5m`: messages in the last 5 minutes from accounts younger than 7 days or posting here for the first time.
- `flagged_5m`: messages the engine flagged in the last 5 minutes, by category (omit zero categories; `{}` for none).
- `event`: `null`, or an open incident: type one of `raid`, `spam_wave`, `pile_on`, `escalation`, `conflict`,
  level `E1` (log only), `E2` (moderators alerted), `E3` (severe). Events follow these rules: a raid needs 5+
  newcomers in 60 s plus a rate over 3x usual or near-identical messages; a spam wave needs 3+ accounts posting
  10+ near-identical messages in 60 s; a pile-on needs 3+ users sending 5+ flagged messages at one person in
  5 min. A friendly raid or host from another streamer, or a hype moment, raises rate and newcomers and is
  **not** an event.
- `copies_60s`, `copies_accounts`: how many near-identical copies of **the closing line** were posted in the
  last 60 s, and by how many accounts (0 and 0 when none).
- `target_5m`, `target_users`: if the closing line mentions or replies to a specific person, how many messages
  that same person received in the last 5 minutes, and from how many different users (0 and 0 when the
  closing addresses nobody in particular).

Kinds and counts (**{COUNTS}**):

1. **Pairs** (`pair_pos` + `pair_neg`, same `scenario`). The two halves have the **same topic, the same lead
   and the same closing, byte for byte**; only `state` differs. The closing must be genuinely ambiguous from
   the text and the lead alone: a reasonable moderator could not call it either way without knowing what is
   happening in the channel. In `pair_pos` the state is an incident (raid, spam wave or pile-on as fits the
   category) under which a moderator would call the closing a violation of {CATEGORY}; in `pair_neg` it is a
   normal channel (quiet, or busy for an innocent reason) under which the same closing is innocent. The lead
   must be consistent with both states (remember identical copies of the closing are removed from the window,
   and the window carries no author names, so it cannot show who said what).
2. **event_neg**: an incident is happening (event state, flagged counts up, the lead shows it), and the closing
   is innocent: a bystander asking what is going on, someone calling the mods, the target answering calmly,
   someone reporting or quoting the spam in order to warn, a regular carrying on their normal conversation.
   Label false. This checks whether telling the model about an incident makes innocent people look guilty.
3. **busy_neg**: a normal but busy channel: a hype moment, a big play, a friendly raid or host with many
   newcomers, a giveaway the channel itself runs; `rate_x` from 3 to 15, newcomers can be high, `event` null,
   flagged counts 0 to 2. The closing is innocent but the kind of line an over-eager filter might catch
   (caps, hype, banter, competitive trash talk with no target, a one-off link someone asked for). Label false.
   This checks whether a busy channel inflates false positives.
4. **control_pos**: a line that clearly violates {CATEGORY} on its own, in a normal channel (`event` null).
   Label true. This checks that a calm state does not talk the model out of an obvious violation.

Rules: chat register, English, 4 to 9 messages in `lead`, closings at least 12 characters, fictional names,
handles and domains (use `.example`, `.test` or invented domains), no real people, non-explicit wording, no
slurs spelled out (a mild insult is fine). Vary topics, platforms (Twitch, Discord, YouTube live), and the
numbers in the states; do not make every incident E2 or every rate 12x. States must be internally consistent
with the rules above. The label is what a moderator who could see the lead, the closing and the state would
decide about the closing line under the criteria. Ids: pairs `{CATEGORY}-pNN-pos` / `-neg` with scenario
`{CATEGORY}-pNN`; others `{CATEGORY}-eNN` (event_neg), `{CATEGORY}-bNN` (busy_neg), `{CATEGORY}-cNN`
(control_pos), each its own scenario equal to its id. When done, validate the file parses and report the
counts per kind.
