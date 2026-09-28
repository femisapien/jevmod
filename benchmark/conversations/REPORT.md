# Five bots talking: generated conversations, and what they can be trusted for

JEV-64. Generator `generate.py`, gates `realism.py`, `leakage.py`, `jev_gate.py`, `blind.py`, scorer `score.py`,
data under `data/`. What the files are and how to run them: `README.md`.

**Status: pre-registered, nothing generated yet.** This section is committed and pushed before any generation, any
blind label or any paid request. Later sections are added under it; this one is not edited after the first run.

## Pre-registration (written 2026-09-29, before the run)

### The questions

1. **Context (JEV-18).** Does the conversation window raise the score of one fixed string when the conversation
   before it singles somebody out, and not when the same string lands among friends (A against B) or in a group
   that is just as harsh but where nobody is isolated (A against C)? The design, the three hand-written scenarios
   and the power calculation are in `gate.py`, `seed.jsonl`, `power.py` and `odd/tasks/synthetic-conversations.md`;
   this run is their T2, T4 and T6.
2. **Events (JEV-26, JEV-27, JEV-28).** A labelled set of multi-party chat streams containing the event types the
   detectors will look for (pile-on, coordinated harassment, spam wave, escalation, raid), each paired with a hard
   negative that shares its opening and its metadata, so a detector can be tested on the part of the rule that
   reads text.

Neither answers "how good is jevmod". Everything here is generated text.

### Who does what

- **Generator:** a local uncensored model, `Huihui-Qwen3-VL-30B-A3B-Instruct-abliterated-Q4_K_S.gguf`, through
  llama.cpp's `llama-server` on this machine. Free.
- **Five bots:** every scenario has five invented personas. Each message is written by one persona's call, which
  sees the chat so far, the shared situation and **only its own private brief**. Nobody but the generator script
  knows the label; a persona that is being picked on is told it feels blamed, not that it is the target of a
  pile-on. Crowds (raiders, spammers, a hype wave) are written by one call per crowd, because a crowd of twelve
  is not five bots, and every row that has one says so.
- **Blind labeller:** a model of a different family from the generator (Claude Sonnet, run as a separate agent
  with no access to the generator, its prompts or the intended labels). It sees items shuffled, under random ids,
  one conversation or one arm at a time. Its labels decide acceptance; they are not used as ground truth on their
  own.
- **Judge:** Jev, through `jevmod.judge.Judge`, cache off. The generator never judges and the judge never
  generates.

### Set 1: context triples

**Counts.** 120 accepted scenarios: 60 `harassment`, 30 `scam`, 30 `selfharm` (the seed's three categories; the
number is `power.py`'s). At most three candidates generated per accepted slot (180, 90, 90). If a category runs
out of candidates the set is reported short; **no gate is loosened to fill it**.

**Shape.** One closing line, stored once, and three lead-ups of 8 to 10 messages, the first message identical in
all three. A: five people, four turning on the fifth, the closing line said by one of the four to the fifth. B:
two of the same people, friends ribbing each other. C: all five, just as harsh, everyone giving and taking. For
`scam` A is a newcomer fishing for who owns what, B a regular with a genuine spare, C a busy trading channel where
everyone says "dm me". For `selfharm` A is the closer in real distress, B frustrated at a game, C office
hyperbole that may borrow A's register and never its imagery (the seed's rule).

**Gates, in order. A scenario is accepted only if it passes all of them.**

- **G0, closing line ambiguous alone (Jev, paid, before any arm is generated).** The closing line scored alone
  three times, one request each: mean in [0.10, threshold - 0.10] for its category (harassment and scam [0.10,
  0.65], selfharm [0.10, 0.40]) and range of the three at most 0.08. A line that is already flagged alone leaves
  nothing to measure; a line at zero cannot be moved by anything.
- **G1, structure.** Lead-ups of 8 to 10 messages; A and C five distinct authors, B two; in A the fifth person
  speaks two or three times; no lead-up message equals the closing line or shares a four-word sequence with it.
- **G2, realism (deterministic, `realism.py`).** Every message 2 to 220 characters, arm median at most 90; none
  carries a speaker prefix (`name: ...`), a narrated action (`*sighs*`), wrapping quotes, a hashtag, or model
  boilerplate ("as an ai", "i'm sorry, but", "language model", "roleplay", "character", "scenario"); no message
  repeated inside an arm; at least 30% of an arm's messages start in lower case (the bots are told to type the
  way people type in chat, and a transcript in perfect sentence case is the first thing that gives a generated
  chat away). Any sexual content, any mention of a minor near sexual content, any self-harm method, and any
  slur from the list in `realism.py`: rejected, whatever the arm.
- **G3, leakage (`leakage.py`).** No message uses the vocabulary of the label or of the private briefs: "pile on",
  "gang up", "bully", "harass", "target", "singled out", "reciprocal", "roast", "scam", "self harm", "suicid",
  "kill myself", "end it all", "hurt myself", "victim". For `harassment` and `scam`, C's lead-up must be at least
  as dense in the category's surface vocabulary as A's, less 0.1 hits a message (hostile words for harassment,
  trading words for scam; the lists are in `leakage.py`).
- **G4, harshness matched (Jev, paid).** For `harassment` and `scam`: every lead-up message of A and C scored
  alone; the mean category score of C's lead-up at least A's minus 0.05. This is the guard against a window that
  separates A from C by noticing rude words nearby. **No gate reads a score of the closing line in context**, so
  acceptance cannot select on the outcome being measured.
- **G5, blind label (independent).** Every arm, alone, shuffled across the whole set: the lead-up and the closing
  line marked as the last message. Harassment: "is the author of the last message joining several people in
  going after one person, and who?". Scam: "is the last message plausibly an attempt to scam someone here?".
  Selfharm: "should someone check on the author of the last message?". Also "does the last message fit this
  conversation" and realism on 1 to 5. Pass: A yes, B no, C no; for harassment, A's named person is the intended
  one; every arm fits and scores 3 or more on realism. Agreement before rejection is reported (Cohen's kappa of
  blind yes/no against intended).

**Scoring (`score.py`).** Each accepted closing line judged once in each arm's context, one request per
judgement, cache off, with every enabled category (`gate.py`'s procedure). Alone is the G0 mean.

- Primary: per scenario A-B and A-C in the category's score. Pooled and per category: mean with a 95% bootstrap
  interval (10,000 resamples of scenarios, seed 64) and the exact two-sided paired sign test.
- **The window does something** if pooled A-B has sign-test p < 0.05 and a positive mean. **It does the right
  thing** if pooled A-C does. Per-category results are reported with their intervals and not called significant
  on their own when n is under 30.
- Changed verdict: the share of scenarios where the closing line crosses the shipped threshold in A and not in C,
  and in A and not in B, with Wilson 95% intervals.
- Noise reference: the G0 range across three repeats, reported as a distribution.
- **Stop rule, `power.py`'s.** After the first 40 accepted scenarios (in the order accepted), score them. If
  pooled A-C does not meet the criterion, stop: nothing more is generated or scored and the report is on the 40.

### Set 2: event streams

**Counts.** 12 pairs per type, five types, 60 pairs, 120 streams. At most two candidate pairs per accepted pair.
A pair is kept or dropped whole.

**Shape.** Every stream is a channel's chat with a timestamp, an author and, per author, `account_age_days` and
`first_in_channel`. It opens with the same 12 to 16 messages of ordinary chatter from five regulars (the five
bots), byte-identical between the two streams of a pair; then the event segment; then 4 to 8 messages of
aftermath. The positive and its hard negative share the regulars, the channel, the number of messages and
accounts in the event segment, every timestamp and every newcomer flag and account age. **Metadata is identical
within a pair by construction**, so any detector that tells them apart is reading text.

| type | positive | hard negative |
|---|---|---|
| pile_on | three or four regulars turn on a fifth over about 5 minutes | the same five roast each other, everyone giving and taking |
| coordinated_harassment | six to eight new accounts arrive within two minutes and go after one regular with similar lines | six to eight accounts (the same count of new ones) complain in similar lines about a game patch or a referee, nobody in chat targeted |
| spam_wave | three or more accounts post near-identical promotional lines, ten or more in 60 s | a copypasta and emote wave after a big moment, regulars and viewers alike, ten or more in 60 s |
| escalation | one regular's messages at another rise from annoyed to insulting to talk of finding them elsewhere | a heated argument between the same two that stays level and cools off |
| raid | twelve new accounts arrive within 60 s hostile to the streamer and chat | twelve new accounts arrive within 60 s from a friendly raid and say hello |

Account ages for new accounts are drawn from one distribution for both streams of a pair. Real hate raids often
use fresher accounts than friendly ones; this set deliberately removes that cue and can say nothing about it.

**Labels.** Per stream: `surface` (a moderator should be told), `type` (null for a hard negative), `hard_negative_of`,
`span` (first and last message of the event segment), `target` (a handle, or null). Per message: `role`
(`regular`, `target`, `attacker`, `spammer`, `raider`, `viewer`, `newcomer`), `in_event`, `directed_at`.

**Gates.** G1: ids unique, times non-decreasing, prefix and metadata identical within the pair, the segment's
message and account counts as specified. G2: `realism.py` as above, except that near-duplicates are allowed where
the type is made of them (spam and copypasta roles) and crowd lines are at most 120 characters. G3: the label
vocabulary above plus "spam wave", "coordinated", "escalat", "hate raid"; "raid" and "spam" are ordinary chat
words on these platforms and are allowed in both streams of a pair. G5: the blind labeller sees each stream alone
(times, handles, a "new" marker on first-time accounts, no roles) and answers: alert a moderator yes/no, which
type from the five or none, who is targeted, realism 1 to 5. Pass: the alert matches `surface`, realism 3 or
more, and for a positive the type matches, or is its declared sibling (pile_on and coordinated_harassment), which
is recorded.

**Secondary, descriptive only.** Every message of every accepted stream judged alone by Jev (every enabled
category, one request per message, cache off), stored beside the stream, and per type the count of event-segment
messages over each category's line, positive against negative. No verdict is drawn from it.

### What neither set can be used for, decided now

Retraining, calibrating a threshold, choosing a detector's numbers (JEV-28's multiples and minimums need real
channels, JEV-70), or any published figure about jevmod's accuracy. Set 1 answers one comparative question about
the same string in two contexts. Set 2 is a fixture: it can show that a detector fires on a positive and holds on
its paired negative, and it cannot show how often either happens in real chat. Neither replaces JEV-11.

### Spend

Jev at about $0.00009 a judgement (`power.py`): G0 at most 360 lines x 3, G4 at most 180 x 20 messages, scoring
120 x 3, events 120 x about 45. Under $2 in all; the actual figure is reported.
