# Benchmark: jevmod against three local moderation models

Run on 2026-09-18 on the same 2,531 messages. Scripts in `benchmark/`; the raw per-message outputs of every system
are committed in `benchmark/results/` (`report.py` prints the tables from them). The datasets are not committed:
`prepare.py` downloads the public sets and rebuilds `items.jsonl`. Each `run_*.py` is resumable.

Added on 2026-09-20: a fourth set of 2,000 real Discord messages, jevmod only, because the three sets above are
essays, forum comments and YouTube comments — none of them is the live chat register the product actually
moderates. See "Discord scam" in the tables below.

## What was compared

| system | what it is | how it ran |
|---|---|---|
| **jevmod** | Jev (TypeSafe System One), one yes/no question per category with criteria, 7 categories at once | API, batches of 25 messages per request |
| **Llama Guard 3 8B** | Meta's open moderation model, 14 hazard categories, answers `safe`/`unsafe` + categories | llama.cpp Q4_K_M on an RTX 5080 |
| **ShieldGemma 2B** | Google's open moderation model, one Yes/No question per policy (harassment, hate, sexual, dangerous) | llama.cpp Q8_0 on an RTX 5080, 4 calls per message |
| **toxic-bert** | the BERT classifier behind Detoxify, trained on Jigsaw; toxicity/insult/threat/obscene | transformers on an RTX 5080 |

OpenAI's moderation endpoint is not in the table: it needs an OpenAI key. OpenAI published their own numbers on
the same evaluation set in "A Holistic Approach to Undesired Content Detection in the Real World" (2022).

## Data

| set | messages | what the labels mean |
|---|---|---|
| OpenAI moderation eval (`samples-1680`) | 1,680 | human labels for sexual (→ `nsfw`), sexual/minors (→ `minors`), hate + harassment + violence (→ `harassment`), self-harm (→ `selfharm`). 1,158 are clean. |
| Civil Comments (Jigsaw) | 351 | 101 with toxicity ≥ 0.7 (→ `harassment`), 250 with toxicity ≤ 0.1 (clean). Sampled from the HF test split. |
| YouTube Spam Collection (UCI) | 500 | 250 comments labelled spam, 250 not. Labels are loose: "I'm a subscriber" and "Thumbs up if you're watching in 2015" count as spam. |
| Discord scam/phishing (`wangyuancheng/discord-phishing-scam`, MIT) | 2,000 | real messages from private gaming Discord servers, 2024-01 to 2025-06 (English and Hindi). 278 labelled scam/spam (fake Nitro, giveaways, crypto airdrops, credential theft, spam bursts), 1,722 clean. One label column, not two: `scam` and `spam` are both scored against the same positives below. This is the one set of the four that is actually the product's register — short live chat, not essays or comments. |

## Quality

AUROC: probability that a random positive scores above a random negative; 0.5 is chance, 1.0 is perfect; it does
not depend on the threshold. F1 is at each system's default threshold (jevmod: its shipped defaults; others 0.5),
and "best F1" is the best threshold for that set in hindsight, which is what you would get after tuning on your
own traffic.

Llama Guard only gives a probability for "unsafe at all"; per-category numbers for it use that probability when
it named the category and 0 otherwise, which under-reports it on AUROC. ShieldGemma has no self-harm, minors or
spam policy; toxic-bert has none of those either.

| set | category | system | AUROC | F1 @ default | best F1 (threshold) |
|---|---|---|---|---|---|
| OpenAI eval | harassment | **jevmod** | **0.930** | 0.748 | 0.751 (0.80) |
| | | Llama Guard 3 8B | 0.805 | 0.681 | 0.681 |
| | | ShieldGemma 2B | 0.914 | 0.618 | 0.663 (0.80) |
| | | toxic-bert | 0.807 | 0.423 | 0.445 |
| OpenAI eval | nsfw | **jevmod** | **0.982** | **0.871** | 0.872 (0.85) |
| | | Llama Guard 3 8B | 0.843 | 0.780 | 0.782 |
| | | ShieldGemma 2B | 0.968 | 0.800 | 0.851 (0.90) |
| | | toxic-bert | 0.876 | 0.549 | 0.574 |
| OpenAI eval | selfharm | **jevmod** | **0.992** | 0.714 | 0.792 (0.35) |
| | | Llama Guard 3 8B | 0.891 | **0.825** | 0.825 |
| OpenAI eval | minors | **jevmod** | **0.977** | 0.519 | 0.645 (0.40) |
| | | Llama Guard 3 8B | 0.590 | 0.248 | 0.248 |
| OpenAI eval | any violation | jevmod | 0.939 | 0.762 | **0.825** (0.80) |
| | | Llama Guard 3 8B | 0.921 | **0.787** | 0.793 |
| | | ShieldGemma 2B | 0.939 | 0.760 | 0.791 |
| | | toxic-bert | 0.884 | 0.646 | 0.709 |
| Civil Comments | harassment | jevmod | 0.875 | 0.659 | 0.707 (0.50) |
| | | Llama Guard 3 8B | 0.539 | 0.159 | 0.159 |
| | | ShieldGemma 2B | 0.874 | 0.601 | 0.710 |
| | | toxic-bert | **0.973** | **0.846** | **0.899** (trained on this data) |
| YouTube | spam | **jevmod** | **0.994** | 0.534 | **0.962** (0.15) |
| | | Llama Guard 3 8B | 0.500 | 0.000 | no spam category |
| | | ShieldGemma 2B | | | no spam category |
| | | toxic-bert | | | no spam category |
| Discord scam | scam | jevmod | 0.980 | 0.651 | 0.833 (0.25) |
| Discord scam | spam | jevmod | 0.980 | 0.758 | 0.860 (0.40) |

No other system was run on the Discord set: none of the three open models has a scam/phishing category, and this
addition is about the register, not a new head-to-head. F1 @ default uses jevmod's shipped thresholds (scam 0.75,
spam 0.85); at those, false positives on the 1,718 clean Discord messages are 5 for scam (0.29%) and 10 for spam
(0.58%) — the number a server owner actually feels.

Reading it:

- On the serious categories (OpenAI's human-labelled set) jevmod has the best ranking quality in every category:
  harassment 0.93, sexual 0.98, self-harm 0.99, minors 0.98. Llama Guard is the closest open model on
  "flagged at all" and on self-harm at its own threshold.
- jevmod's shipped thresholds are conservative: self-harm at 0.80 misses cases that a 0.35 threshold would catch
  (F1 0.71 → 0.79); minors at 0.70 has recall 0.41 because OpenAI's label also covers *discussion* of child abuse,
  while jevmod's question asks about sexualisation or grooming. The ❌/✅ feedback loop in the bots and the
  `PUT /v1/policy` endpoint exist to move those lines per community.
- toxic-bert wins Civil Comments because it was trained on Civil Comments. On text it has not seen (OpenAI's set)
  it is the weakest of the four.
- Spam: only jevmod has a spam category. Its ranking is near perfect (0.994) but the shipped threshold of 0.85 is
  too high for YouTube's loose labels; at 0.15 F1 is 0.96. Spam is the category where community calibration
  matters most.
- The 0.994 spam AUROC is measured on YouTube comments, not on what the product actually moderates. On live
  Discord chat — the register jevmod is sold on — spam AUROC is 0.980 and scam (a category YouTube's set cannot
  test at all) is also 0.980. That is a real drop, not noise: about 1.4 points of ranking quality, in the
  direction you'd expect once "comment under a video" becomes "one line in a chat window with an emote and a
  link." It does not fall apart — 0.980 is still excellent, and at the shipped thresholds precision is 0.95-0.97
  with recall in the 0.49-0.63 range, which is the same conservative shape as everywhere else in this file — but
  the headline number the product is sold on does not fully survive contact with its own register, and this is
  the first time anyone measured that instead of assuming it.

## Cost and latency

| system | cost per 1,000 messages | latency per message | needs |
|---|---|---|---|
| jevmod (Jev, 7 categories) | **$0.042** (2.5 M input tokens for 2,504 messages, list price $0.042/M) | 22 ms amortised in batches of 25 (about 550 ms per request) | an API key |
| Llama Guard 3 8B Q4 | $0.004 in GPU time at $0.30/h | 49 ms | a 16 GB GPU, 5 GB of weights |
| ShieldGemma 2B Q8 | $0.011 in GPU time | 130 ms (4 calls) | a GPU, 3 GB |
| toxic-bert | $0.0006 in GPU time | 8 ms | a GPU or a CPU |

Local models are cheaper per message once you own the GPU and the ops around it. jevmod costs about $1 a month
for a community with 20,000 judged messages and needs no hardware. For scale, a general LLM as judge was not run;
at list price the same 1,005 input tokens plus about 20% of prompt overhead would cost roughly $1.2 per 1,000
messages with Claude Haiku 4.5 ($1 per million input tokens), about 30× Jev, before output tokens.

## Calibration

Is a 0.8 really 80%? Expected calibration error (ECE, 10 bins; 0 is perfect) and Brier score on jevmod's
probabilities, measured on the same runs:

| set | category | ECE | Brier | base rate |
|---|---|---|---|---|
| OpenAI eval | harassment | 0.136 | 0.099 | 0.15 |
| OpenAI eval | nsfw | 0.083 | 0.049 | 0.15 |
| OpenAI eval | selfharm | 0.015 | 0.010 | 0.03 |
| OpenAI eval | minors | 0.025 | 0.027 | 0.05 |
| Civil Comments | harassment | 0.088 | 0.133 | 0.29 |
| YouTube | spam | 0.130 | 0.067 | 0.53 |

The shape matters more than the number: above 0.9 the probabilities match the observed rate within a few points
(harassment bin 0.9: 183 messages, mean p 0.96, observed 84%; nsfw: 229 messages, 0.97 vs 92%). Between 0.5 and
0.85 they run high (harassment bin 0.8: mean p 0.85, observed 51%; bin 0.5: 0.55 vs 17%). That is why the shipped
thresholds sit mostly at 0.75 to 0.85 (minors 0.70, off-topic 0.90) and why "flag" is the default action: a 0.6 is a maybe, not a 60%.

## Caveats

- 2,531 messages across three public sets is a sanity benchmark, not a leaderboard. No system was tuned on this
  data; thresholds are the defaults.
- All four systems saw the same text after jevmod's normalisation (HTML entities, unicode).
- Llama Guard and ShieldGemma prompts are the ones published by Meta and Google; quantised weights (Q4/Q8) may
  cost them a little accuracy against fp16.
- The messages under 8 letters without a link (27 of 2,531) are never sent to Jev by design and count as clean.
- The Discord set has one label column, not two: "scam" and "spam" AUROC above are both scored against the same
  278 positives, so they are not independent measurements of two different failure modes, only of whether each of
  jevmod's two questions ranks the same bait highly. A few of the 278 are loose the same way YouTube's spam label
  is loose — e.g. "I think someone is pretending to be you and scammed me" is a message *about* being scammed,
  labelled scam anyway. The set comes from one author's gaming communities (11k members, ≈80k raw messages before
  filtering to these 2,000); it is not a random sample of Discord.
