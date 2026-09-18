# Can Jev detect AI-generated text? Measured, not assumed.

Run on 2026-09-18 against the live TypeSafe API from `benchmark/ai_detect/run.py`. 520 texts, 260 AI and 260
human (base rate 0.500), each truncated to 400 characters, asked three different ways, 25 messages per request,
the same batching contract as `jevmod.judge.Judge`. Total spend: **463,499 input tokens = $0.0195**.

## The short answer

**Yes on the numbers, no as a default category.** The direct Noul (formulation A) reaches **AUROC 0.971** on the
whole set and there is a threshold (0.82) with **precision 0.902 at recall 0.988**, so both stated bars are
cleared. But the precision that matters in a real channel is not the precision on a 50/50 set: at a realistic
2% rate of AI-pasted messages, projected precision is 0.19-0.37. And the one failure mode is systematic and
not fixable by wording: **human beings who write like an encyclopedia are flagged as machines.**

Recommendation: **ship as an opt-in experimental category, flag-only, default threshold 0.85, with a warning.**

## 1. Does it work well enough to ship?

Bar: AUROC >= 0.85, and a threshold with precision >= 0.90 at recall >= 0.50 on chat-shaped text.

| subset | variant | n | AUROC | F1@0.5 | P@0.5 | R@0.5 | best F1 (th) | ECE | Brier |
|---|---|---|---|---|---|---|---|---|---|
| all | **A** | 520 | **0.971** | 0.852 | 0.744 | 0.996 | **0.936 (0.85)** | 0.138 | 0.111 |
| all | B | 520 | 0.869 | 0.843 | 0.728 | 1.000 | 0.878 (0.80) | 0.207 | 0.165 |
| all | C | 520 | 0.864 | 0.836 | 0.723 | 0.992 | 0.857 (0.60) | 0.150 | 0.158 |
| all | C_product | 520 | 0.865 | 0.844 | 0.800 | 0.892 | 0.857 (0.30) | 0.078 | 0.129 |
| all | C_polished | 520 | 0.835 | 0.840 | 0.748 | 0.958 | 0.845 (0.55) | 0.119 | 0.148 |
| all | C_impersonal | 520 | 0.847 | 0.782 | 0.651 | 0.981 | 0.805 (0.65) | 0.226 | 0.209 |
| chat-shaped only (AI vs real chat) | A | 350 | 0.999 | 0.998 | 1.000 | 0.996 | 0.998 (0.35) | 0.085 | 0.012 |
| chat-shaped only | B | 350 | 1.000 | 0.990 | 0.981 | 1.000 | 0.996 (0.60) | 0.062 | 0.017 |
| chat-shaped only | C | 350 | 0.998 | 0.989 | 0.985 | 0.992 | 0.989 (0.45) | 0.150 | 0.043 |
| chat-shaped only | C_product | 350 | 0.998 | 0.943 | 1.000 | 0.892 | 0.987 (0.20) | 0.204 | 0.078 |
| chat-shaped only | C_polished | 350 | 0.991 | 0.969 | 0.980 | 0.958 | 0.969 (0.50) | 0.144 | 0.059 |
| chat-shaped only | C_impersonal | 350 | 0.982 | 0.951 | 0.924 | 0.981 | 0.958 (0.65) | 0.065 | 0.055 |
| topic-matched HC3 pairs | **A** | 390 | **0.943** | 0.858 | 0.753 | 0.996 | 0.936 (0.85) | 0.147 | 0.140 |
| topic-matched HC3 pairs | B | 390 | 0.738 | 0.858 | 0.751 | 1.000 | 0.882 (0.75) | 0.206 | 0.193 |
| topic-matched HC3 pairs | C | 390 | 0.736 | 0.854 | 0.750 | 0.992 | 0.866 (0.60) | 0.112 | 0.175 |
| topic-matched HC3 pairs | C_product | 390 | 0.737 | 0.845 | 0.803 | 0.892 | 0.868 (0.30) | 0.102 | 0.166 |
| topic-matched HC3 pairs | C_polished | 390 | 0.687 | 0.859 | 0.778 | 0.958 | 0.861 (0.40) | 0.120 | 0.173 |
| topic-matched HC3 pairs | C_impersonal | 390 | 0.730 | 0.832 | 0.722 | 0.981 | 0.839 (0.60) | 0.176 | 0.208 |

The three subsets say three different things and all three are needed:

- **chat-shaped only** (AI answers vs real YouTube/Civil Comments messages) is the easy case, AUROC 0.998-1.000
  for every formulation. This is the number an AI-detection vendor would quote. It is close to meaningless on
  its own: separating "gm guys this song slaps" from a ChatGPT paragraph is separating registers, not authors.
- **topic-matched HC3 pairs** is the honest case: the same question answered by a human and by ChatGPT, so
  subject matter is controlled. Here the formulations split apart hard: A holds at 0.943, B and C collapse to
  0.74.
- **all** mixes both, and is the closest to a moderation queue that contains casual chat *and* long careful posts.

### The ship bar

| subset | variant | threshold | precision | recall | F1 |
|---|---|---|---|---|---|
| all | **A** | **0.82** | **0.902** | **0.988** | 0.943 |
| all | B, C, C_product, C_polished, C_impersonal | none exists | | | |
| chat-shaped only | A | 0.10 | 0.919 | 1.000 | 0.958 |
| chat-shaped only | B | 0.21 | 0.903 | 1.000 | 0.949 |
| chat-shaped only | C | 0.31 | 0.906 | 1.000 | 0.951 |
| chat-shaped only | C_product | 0.05 | 0.932 | 1.000 | 0.965 |
| topic-matched HC3 pairs | **A** | **0.82** | **0.902** | **0.988** | 0.943 |
| topic-matched HC3 pairs | B, C, ... | none exists | | | |

**Only formulation A clears the bar anywhere except the easy subset.** B and C never reach precision 0.90 at any
threshold once the human side includes careful writing.

### Why the 50/50 precision is not the precision you get

A channel is not 50% AI. Projecting with the measured TPR and FPR (FPR* is the 95% upper bound by the rule of
three, because zero false positives on 90 messages only means "below ~3%"):

| human side | threshold | TPR | FPR obs | FPR* | P @50% AI | P @10% | P @5% | P @2% | P @1% |
|---|---|---|---|---|---|---|---|---|---|
| chat only | 0.50 | 0.996 | 0.000 | 0.033 | 0.968 | 0.769 | 0.611 | 0.379 | 0.232 |
| chat only | 0.85 | 0.954 | 0.000 | 0.033 | 0.966 | 0.761 | 0.601 | 0.369 | 0.224 |
| chat only | 0.95 | 0.042 | 0.000 | 0.033 | 0.559 | 0.124 | 0.063 | 0.025 | 0.013 |
| all human | 0.50 | 0.996 | 0.342 | 0.342 | 0.744 | 0.244 | 0.133 | 0.056 | 0.029 |
| all human | 0.85 | 0.954 | 0.085 | 0.085 | 0.919 | 0.556 | 0.372 | 0.187 | 0.102 |
| all human | 0.95 | 0.042 | 0.000 | 0.012 | 0.786 | 0.289 | 0.162 | 0.070 | 0.036 |

At 2% AI traffic, four out of five flags are wrong even at threshold 0.85 on the mixed human side. That is the
number that decides "experimental, flag-only" rather than "another category next to spam".

Note also the 0.95 row: **Jev's probabilities top out around 0.93**. Recall at 0.95 is 0.042. A threshold above
0.93 is unusable, so there is no "very high confidence" band to auto-act on.

## 2. Which wording won, and why

**A, the direct Noul, won**, and the gap only shows on the topic-matched subset: A 0.943 vs B 0.738 vs C 0.736.

- **A** ("was this written by a language model rather than typed by a person?") asks the question we actually
  care about, and its criteria name the tells on both sides *and* an explicit exception ("careful writing,
  correct grammar, a formal register or imperfect English from a non-native speaker are NOT by themselves signs
  of a language model"). That exception is what keeps the non-native and long-formal-comment strata clean.
- **B** (Score, "how much does this read like a person typing quickly in a chat", 4 levels) measures the wrong
  thing on purpose, and the proxy turns out to be too lossy: it is an excellent *register* detector (AUROC 1.000
  separating chat from prose) and a poor *authorship* detector (0.738 when both sides are prose). It answers
  "is this chatty", and a careful human is not chatty.
- **C** (two decomposed Nouls) has the same defect and adds a combination problem. Its two halves are weaker
  alone than A (polished 0.687, impersonal 0.730 on matched pairs) and no combination rescues them: mean 0.736,
  product 0.737. Decomposition did buy the best calibration on the full set (C_product ECE 0.078 vs A 0.138),
  worth remembering if calibration ever matters more than ranking, but it cannot reach precision 0.90.

The lesson is the one already in the `judge.py` header: criteria carry the work. A's criteria explicitly excuse
formal and non-native writing; B's and C's rubrics define "human" as "informal", so every careful human is a
positive.

## 3. Where it fails

Human false positive rate by source, formulation A:

| provenance | n | FPR @0.5 | FPR @0.85 |
|---|---|---|---|
| UCI YouTube Spam Collection (non-spam) | 60 | **0.000** | **0.000** |
| Civil Comments (toxicity<=0.1, short) | 30 | **0.000** | **0.000** |
| Civil Comments (toxicity<=0.1, >=200 chars) | 20 | 0.100 | **0.000** |
| JFLEG (English-learner sentences, uncorrected) | 20 | 0.100 | **0.000** |
| HC3/reddit_eli5/human | 28 | 0.286 | 0.036 |
| HC3/finance/human | 24 | 0.458 | 0.000 |
| HC3/medicine/human | 23 | 0.478 | 0.000 |
| HC3/open_qa/human | 28 | **1.000** | 0.036 |
| HC3/wiki_csai/human | 27 | **1.000** | **0.741** |

Named categories of false positive, worst first:

1. **Encyclopedic / reference writing.** HC3's `wiki_csai` human answers are Wikipedia lead paragraphs. Every
   single one is flagged at 0.5, and **three quarters are still flagged at 0.85** - the only stratum the high
   threshold does not rescue. In a real community this is the member who answers by pasting a definition, writes
   documentation, or posts a careful technical explainer. They will be flagged, repeatedly.
2. **Short, complete factual answers.** `open_qa` human answers ("The film was released in 1997.") are flagged
   100% of the time at 0.5. At 0.85 this mostly clears (0.036), because the question is genuinely undecidable:
   a one-sentence fact carries no authorship signal either way.
3. **Domain-expert prose.** Finance and medicine human answers, 46-48% at 0.5, 0% at 0.85. A subject-matter
   expert writing carefully looks like a model at a loose threshold.
4. **Long formal comments.** Civil Comments >= 200 chars: 10% at 0.5, 0% at 0.85.
5. **Non-native English: not a problem here.** 10% at 0.5, **0% at 0.85** on 20 learner-written sentences. This
   was the feared failure and formulation A's explicit exception appears to hold it. 20 items is a small sample
   (95% upper bound ~15% even at zero observed), and JFLEG sentences are essay fragments, not chat, so this
   should be re-measured on real non-native chat before leaning on it.

The 10 worst false positives are all `wiki_csai` human answers, p 0.90-0.93: "A stop sign is a traffic sign
designed to notify drivers that they must come to a complete stop...", "Medical image computing (MIC) is an
interdisciplinary field at the intersection of computer science...", "In logic, a predicate is a symbol which
represents a property or a relation...". The full table with text is in the output of `run.py report`.

False negatives are less interesting: the 10 worst include two pieces of **dataset noise** (a Cloudflare
interstitial and a "Too many requests in 1 hour" error captured as a ChatGPT answer, p 0.11 and 0.53), and the
rest are short bare facts ("Hillary Clinton was born in Chicago, Illinois, on October 26, 1947.", p 0.68) where
there is nothing to detect. At 0.85 recall is still 0.954, so misses are not the problem - false positives are.

## 4. What it would cost

| formulation | requests | input tokens | tokens/msg | $ / 1,000 msgs | latency / msg |
|---|---|---|---|---|---|
| A | 21 | 163,583 | 315 | **$0.0132** | 14 ms (batched 25, ~350 ms/request) |
| B | 21 | 141,743 | 273 | $0.0114 | 16 ms |
| C | 21 | 158,173 | 304 | $0.0128 | 13 ms |

$0.0132 per 1,000 messages as a standalone question. Added as a ninth question to jevmod's existing batch it is
cheaper still, because the state (the messages themselves) is already being sent: only the extra Noul and its
criteria are new, roughly 60-80 tokens per message, so **well under $0.01 per 1,000 messages marginal**, against
jevmod's current $0.042 for 7 categories. Cost is not the reason to hesitate.

## 5. Recommendation

**Ship as an opt-in experimental category, off by default, flag-only, threshold 0.85, with a warning in the
docs and in the flag itself.** Not a default category, and never an auto-delete or auto-ban action.

Why not "ship as a category": the quality bars are met on paper (AUROC 0.971, precision 0.902 at recall 0.988),
but the errors are not random. They land on one identifiable group of humans - the ones who write carefully and
encyclopedically - and 74% of that group is still flagged at 0.85. A moderation category that systematically
accuses the members who write the best answers is worse than no category. On top of that, at a realistic 2%
base rate the projected precision is 0.19-0.37, so most flags in production will be wrong even where the FPR is
small, and the probability ceiling of ~0.93 means there is no confident band to act on automatically.

Why not "do not ship": on chat-shaped text, which is what jevmod actually sees most of the time, the separation
is essentially perfect (AUROC 0.999, zero false positives in 90 real messages) and non-native English survived
the test. For a community whose rule is "don't paste ChatGPT answers in here", a flag for a human to look at is
genuinely useful and costs almost nothing.

Concretely, if it ships:

- category name `ai_generated`, default **off**, default threshold **0.85**, default action **flag**;
- use formulation A's wording verbatim, including the "careful writing / non-native English is not evidence"
  exception in the `false` criteria - that clause is doing measurable work;
- the category's own description must say that it fires on human members who write in an encyclopedic or
  reference register, and that a flag is a prompt to read the message, not a verdict;
- do not expose it to the feedback loop's automatic threshold moves until it has been measured on a real
  community's traffic, where the base rate is known.

## Data and caveats

520 items, 260 AI / 260 human, base rate 0.500, every item truncated to 400 characters after `jevmod.normalize`.

| stratum | n | source |
|---|---|---|
| ai_chatgpt | 260 | HC3 `all.jsonl`, first ChatGPT answer, spread evenly over finance / medicine / open_qa / reddit_eli5 / wiki_csai |
| human_hc3_formal | 130 | HC3 human answer to the *same* 130 questions (topic-matched pairs) |
| human_chat | 90 | 60 UCI YouTube non-spam comments + 30 short Civil Comments (toxicity <= 0.1), from `benchmark/data/items.jsonl` |
| human_formal_long | 20 | Civil Comments >= 200 chars, toxicity <= 0.1 |
| human_nonnative | 20 | JFLEG validation, uncorrected English-learner sentences |

- The AI side is **ChatGPT only, and 2022-era ChatGPT at that**. A modern model asked to "write like a Discord
  user" would be much harder. Treat every number here as an upper bound on real-world performance.
- HC3's `wiki_csai` human answers are copied Wikipedia text, not something a person typed. They are kept
  deliberately: they are the clearest available instance of the failure mode, and a member pasting a definition
  into a channel is the same thing. They also make the "all" subset harder than a real channel would be.
- Two of the 260 AI items are dataset noise (a Cloudflare page, an OpenAI rate-limit error). They cost ~0.8% of
  recall and were left in rather than cherry-picked out.
- 20 non-native items is too few to conclude anything strong; it is enough to say the feared catastrophe did not
  happen with formulation A's wording.
- No prompt was tuned on this data after seeing the results: the three formulations were written before the run
  and each was asked exactly once.
