"""Deterministic, model-free features for "was this written by a language model?".

Every feature here is pure Python over the message text: no API call, no model, no training data baked in.
Each one is mined from https://github.com/blader/humanizer/blob/main/SKILL.md (itself derived from Wikipedia's
"Signs of AI writing") and is named after the section it comes from, so a flag can always be explained in one
line to a server owner.

Contract: `extract(text) -> dict[str, float]`. Values are rates or counts, never booleans, so a threshold can be
chosen per feature during analysis instead of being frozen here. Text is expected to have gone through
`jevmod.judge.normalize` already (NFKC, combining marks dropped, whitespace collapsed) - which means newlines are
gone, so any feature about paragraph or list *layout* is measured from inline markers only and is documented as
degraded. See DEGRADED_BY_NORMALIZE.

Naming: `d_` prefix for every deterministic feature, so a merged row never collides with Jev's `A`.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Features that cannot work on this corpus because `normalize` collapses newlines and the texts are clipped to
# 400 characters. They are implemented (inline markers only) and reported, but their number here is a floor, not
# a measurement of the pattern in the wild.
DEGRADED_BY_NORMALIZE = {
    "d_bold_markers",
    "d_bullet_markers",
    "d_heading_markers",
    "d_decorative_arrows",
}

# --------------------------------------------------------------------------------------- word lists (SKILL.md)

# SKILL.md §12 "Overused AI words" - the only vocabulary list the skill sanctions.
AI_WORDS = {
    "additionally", "align", "aligns", "aligned", "bolster", "bolstered", "crucial", "crucially",
    "delve", "delves", "delving", "emphasize", "emphasizes", "emphasizing", "enduring", "enhance",
    "enhances", "enhanced", "enhancing", "foster", "fosters", "fostering", "garner", "garnered",
    "highlight", "highlights", "highlighted", "interplay", "intricate", "intricacies", "landscape",
    "meticulous", "meticulously", "pivotal", "robust", "showcase", "showcases", "showcasing",
    "tapestry", "testament", "underscore", "underscores", "underscoring", "vibrant", "multifaceted",
    "comprehensive", "nuanced", "seamless", "seamlessly", "leverage", "leveraging", "realm",
}

# SKILL.md §16 "Sales language".
SALES_WORDS = {
    "boasts", "vibrant", "profound", "exemplifies", "nestled", "groundbreaking", "renowned",
    "breathtaking", "stunning", "must-visit", "unparalleled", "cutting-edge", "state-of-the-art",
}

# SKILL.md §15 "Shallow -ing riders" - an -ing phrase bolted onto a plain fact.
ING_RIDERS = (
    "highlighting", "underscoring", "emphasizing", "ensuring", "reflecting", "symbolizing",
    "contributing to", "cultivating", "fostering", "encompassing", "showcasing", "allowing for",
)

# SKILL.md §9 "Stacked qualifiers" plus the ordinary hedges the skill calls human, kept separate on purpose.
HEDGES = (
    "may", "might", "could", "can be", "often", "typically", "generally", "usually", "tends to",
    "it is important to", "it's important to", "it is worth", "keep in mind", "in some cases",
    "to be fair", "it is also possible", "potentially", "arguably", "in general", "relatively",
    "somewhat", "various", "several", "a variety of", "a number of",
)

# SKILL.md §22 "Chatbot residue" - the most certain tell in the list.
CHATBOT_RESIDUE = (
    "i hope this helps", "hope this helps", "of course!", "certainly!", "great question",
    "you're absolutely right", "would you like", "want me to", "should i continue", "let me know if",
    "as an ai", "as a language model", "i'm sorry to hear", "i am sorry to hear",
    "it is not appropriate", "it's not appropriate", "i cannot provide", "i can't provide",
    "here is a", "here's a rundown", "in summary", "to summarize", "overall,",
)

# SKILL.md §23 "Knowledge-limit disclaimers and guesses".
DISCLAIMERS = (
    "as of my last", "up to my last training", "my training data", "as of 2021", "as of 2022",
    "while specific details", "based on available information", "not publicly available",
    "it is believed that", "i do not have access", "i don't have access", "i am not able to browse",
    "consult a", "consult with a", "seek medical", "professional advice", "a qualified",
)

# SKILL.md §4 "Staged run-up before the point".
STAGED_OPENERS = (
    "let's dive in", "let's explore", "let's break this down", "here's what you need to know",
    "without further ado", "here's the thing", "the thing is", "let's be honest", "real talk",
    "now let's look at", "first of all", "to begin with",
)

# SKILL.md §5 "Arguing with no one".
STRAWMAN = (
    "it's not about", "it is not about", "i'm not saying", "to be clear", "don't get me wrong",
    "this is not to say", "some might say", "one might be tempted", "you might think",
    "it would be easy to", "a tempting approach",
)

# SKILL.md §3 "Sayings that sound deep".
DEEP_SAYINGS = (
    "the real question is", "at its core", "in reality", "what really matters", "fundamentally",
    "the deeper issue", "the heart of the matter", "the bottom line", "at the end of the day",
)

# SKILL.md §13 "Inflated significance".
INFLATION = (
    "stands as a testament", "a testament to", "pivotal moment", "crucial role", "plays a key role",
    "plays an important role", "underscores its importance", "reflects a broader", "lasting legacy",
    "enduring legacy", "setting the stage", "evolving landscape", "indelible mark",
    "the future looks bright", "a step in the right direction", "despite these challenges",
)

# SKILL.md §14 "Vague connection or association".
VAGUE_LINK = ("associated with", "in association with", "connected to", "in connection with", "linked to", "tied to")

# SKILL.md §18 "Avoiding is, are, and has".
COPULA_DODGE = ("serves as", "stands as", "functions as", "operates as", "acts as", "refers to", "is known as")

# ---------------------------------------------------------------------------------- mined assistant register
#
# SKILL.md's vocabulary lists are written for 2024-2025 model prose. They barely fire on this corpus (see
# REPORT_DETERMINISTIC.md §2), so the five lists below were mined from a HELD-OUT slice of HC3 - 1,200
# question/answer pairs that are not among the 520 evaluated texts - and then frozen before any evaluation.
# Only n-grams that are also a register tell SKILL.md or jevmod's own `ai_generated` criteria name were kept;
# topical n-grams that separated just as well on the mining set ("the united states", "can cause") were thrown
# away on purpose, because they measure HC3's subject matter and not a language model.

# "there are several reasons" phrasing - named verbatim in jevmod's `ai_generated` true-criteria, SKILL.md §6.
ENUMERATIVE = (
    "there are a few reasons", "there are several", "there are a number of", "there are many",
    "a few reasons why", "one reason is", "another reason", "a variety of", "a number of",
    "a wide range of", "several factors", "a few things",
)
# Hedged scaffolding that stages a claim instead of making it - SKILL.md §9, and §4's run-up.
HEDGE_SCAFFOLD = (
    "it is important to", "it's important to", "it is worth noting", "it's worth noting",
    "it is also important", "keep in mind", "it is possible that", "it is generally",
    "it is recommended", "it is always a good idea", "it is best to",
)
# Definitional / encyclopedic register - SKILL.md §18 ("refers to" instead of "is").
DEFINITIONAL = ("also known as", "is a type of", "refers to", "is defined as", "is the process of", "is a term")
# Explainer scaffolding aimed at nobody in particular - the "encyclopedic explaining register" in the criteria.
EXPLAINER = ("this means that", "this is because", "for example, if", "in other words", "as a result,", "in general,")
# The assistant's liability reflex: send the user to a professional - SKILL.md §23's neighbour.
SAFETY_REFERRAL = (
    "consult a", "consult with a", "speak to a", "seek medical", "medical professional",
    "healthcare professional", "financial advisor", "a qualified", "professional advice",
)

# Human tells, used as negative evidence. Not from SKILL.md (which never looks at chat) but from the human side
# of jevmod's own `ai_generated` criteria, so the two halves are asked the same thing.
SLANG = (
    "lol", "lmao", "lmfao", "rofl", "idk", "imo", "imho", "tbh", "afaik", "ngl", "fr fr", "wtf",
    "omg", "yeah", "yep", "nope", "gonna", "wanna", "gotta", "kinda", "sorta", "dunno", "cuz",
    "u ", " ur ", " r u ", "pls", "plz", "thx", "haha", "hahaha", "xd", "bruh", "damn", "shit",
    "fuck", "hell no", "wow", "lolol",
)
# Contractions typed without the apostrophe: a typo class a model essentially never produces.
MISSING_APOSTROPHE = re.compile(
    r"\b(dont|cant|wont|isnt|arent|doesnt|didnt|couldnt|shouldnt|wouldnt|havent|hasnt|wasnt|werent"
    r"|im|ive|id|ill|youre|youve|youll|theyre|theyve|thats|whats|its a|lets|aint)\b",
    re.I,
)

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]"
)

# --------------------------------------------------------------------------------------------- helpers

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z']+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]


def _count_phrases(low: str, phrases) -> int:
    return sum(low.count(p) for p in phrases)


def _count_words(words: list[str], vocab: set[str]) -> int:
    return sum(1 for w in words if w in vocab)


# --------------------------------------------------------------------------------------------- features


def extract(text: str) -> dict[str, float]:
    """Every deterministic signal for one message. Rates are per 100 words unless the name says otherwise."""
    t = text.strip()
    low = t.lower()
    words = [w.lower() for w in _WORD.findall(t)]
    nw = max(len(words), 1)
    per100 = 100.0 / nw
    sents = _sentences(t)
    slens = [len(_WORD.findall(s)) for s in sents] or [0]
    ns = max(len(sents), 1)

    f: dict[str, float] = {}

    # --- A. Staging (SKILL.md §1-§5) --------------------------------------------------------------
    # "not X but Y": the negative half names something nobody claimed, so the positive half sounds bigger.
    f["d_not_x_but_y"] = float(
        len(re.findall(r"\bnot (?:just|only|merely|simply)\b[^.?!]{0,80}?\bbut\b", low))
        + len(re.findall(r"\bit'?s not\b[^.?!]{0,60}?,\s*it'?s\b", low))
        + len(re.findall(r"\bnot\b[^.?!]{0,60}?\bbut rather\b", low))
    )
    # "X rather than Y": the same contrast without the negation.
    f["d_rather_than"] = float(low.count("rather than"))
    # A closing one-liner that restates instead of adding ("In summary...", "Overall,...").
    f["d_tidy_closer"] = float(
        bool(re.search(r"\b(in summary|to summarize|in conclusion|overall|all in all|ultimately)\b", low[-160:]))
    )
    # Aphorisms dressed as hidden truths (§3).
    f["d_deep_sayings"] = float(_count_phrases(low, DEEP_SAYINGS))
    # A run-up that announces the point instead of making it (§4).
    f["d_staged_opener"] = float(_count_phrases(low, STAGED_OPENERS))
    # A defence against an objection nobody raised (§5).
    f["d_strawman"] = float(_count_phrases(low, STRAWMAN))

    # --- B. Rhythm by rule (SKILL.md §6-§11) ------------------------------------------------------
    # Em and en dashes used as the universal connector (§8). The obvious tell, measured per 100 words.
    f["d_emdash_rate"] = (t.count("—") + t.count("–")) * per100
    f["d_emdash_any"] = float(t.count("—") + t.count("–") > 0)
    # " -- " and spaced hyphens used the same way.
    f["d_hyphen_as_dash"] = float(len(re.findall(r"(?:\s--\s|\s-\s)", t)))
    # Forced triads: "A, B, and C" - ideas arriving in threes to sound complete (§6).
    f["d_triads"] = float(len(re.findall(r"[a-z)\"']\s*,[^,.?!]{1,60},\s*(?:and|or)\s+", low)))
    # Serial (Oxford) comma before "and": a copy-editing habit models apply by rule.
    f["d_oxford_comma"] = float(len(re.findall(r",\s+(?:and|or)\s+\w", low)))
    # Two or more consecutive sentences opening with the same word (§7).
    f["d_repeat_openers"] = float(
        sum(
            1
            for a, b in zip(sents, sents[1:], strict=False)
            if _WORD.findall(a)[:1] and _WORD.findall(a)[:1] == _WORD.findall(b)[:1]
        )
    )
    # Stacked qualifiers and ordinary hedges, per 100 words (§9): "hedging density".
    f["d_hedge_rate"] = _count_phrases(low, HEDGES) * per100
    # Hyphenated compound pairs applied in every position (§10).
    f["d_hyphen_pairs"] = float(len(re.findall(r"\b[a-z]{3,}-[a-z]{3,}\b", low)))
    # Passive voice, crudely: "is/are/was/were/been + past participle" (§11).
    f["d_passive"] = float(len(re.findall(r"\b(?:is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b", low)))

    # --- Sentence-length regularity ---------------------------------------------------------------
    mean_len = sum(slens) / ns
    var = sum((x - mean_len) ** 2 for x in slens) / ns
    sd = var**0.5
    # A model writes sentences of similar length; a person alternates short and long (SKILL.md "How to work" §4).
    f["d_sent_len_mean"] = mean_len
    f["d_sent_len_cv"] = sd / mean_len if mean_len else 0.0
    f["d_sent_count"] = float(ns)
    f["d_words"] = float(nw)
    # The longest run of consecutive sentences all within 5 words of each other: metronomic rhythm.
    run = best = 1
    for a, b in zip(slens, slens[1:], strict=False):
        run = run + 1 if abs(a - b) <= 5 else 1
        best = max(best, run)
    f["d_even_run"] = float(best)

    # --- C. Inflation and borrowed authority (SKILL.md §12-§18) -----------------------------------
    f["d_ai_words"] = _count_words(words, AI_WORDS) * per100  # §12 vocabulary, per 100 words
    f["d_sales_words"] = _count_words(words, SALES_WORDS) * per100  # §16 advertisement register
    f["d_ing_riders"] = _count_phrases(low, ING_RIDERS) * per100  # §15 -ing phrase bolted onto a fact
    f["d_inflation"] = float(_count_phrases(low, INFLATION))  # §13 ordinary fact called pivotal
    f["d_vague_link"] = float(_count_phrases(low, VAGUE_LINK))  # §14 "associated with" without saying how
    f["d_copula_dodge"] = float(_count_phrases(low, COPULA_DODGE))  # §18 "serves as" instead of "is"

    # --- D. Formatting by rule (SKILL.md §19-§21) - DEGRADED, see module docstring ----------------
    f["d_bold_markers"] = float(t.count("**"))
    f["d_bullet_markers"] = float(len(re.findall(r"(?:^|\s)(?:[-*•]\s+|\d+\.\s+)", t)))
    f["d_heading_markers"] = float(len(re.findall(r"(?:^|\s)#{1,4}\s+\w", t)))
    f["d_decorative_arrows"] = float(len(re.findall(r"[→⇒]|->", t)))
    # Curly quotes where the writer would type straight ones (§21). Weak alone by the skill's own labelling.
    f["d_curly_quotes"] = float(sum(t.count(c) for c in "“”‘’"))

    # --- Mined assistant register (frozen on held-out HC3; see the lists above) --------------------
    f["d_enumerative"] = float(_count_phrases(low, ENUMERATIVE))
    f["d_hedge_scaffold"] = float(_count_phrases(low, HEDGE_SCAFFOLD))
    f["d_definitional"] = float(_count_phrases(low, DEFINITIONAL))
    f["d_explainer"] = float(_count_phrases(low, EXPLAINER))
    f["d_safety_referral"] = float(_count_phrases(low, SAFETY_REFERRAL))
    f["d_register_total"] = (
        f["d_enumerative"] + f["d_hedge_scaffold"] + f["d_definitional"] + f["d_explainer"] + f["d_safety_referral"]
    )

    # --- E. Leftovers (SKILL.md §22-§23) ----------------------------------------------------------
    f["d_chatbot_residue"] = float(_count_phrases(low, CHATBOT_RESIDUE))  # §22 greeting/offer/closer left in
    f["d_disclaimers"] = float(_count_phrases(low, DISCLAIMERS))  # §23 knowledge-limit or "consult a professional"

    # --- Human tells (negative evidence; not from SKILL.md) ---------------------------------------
    f["d_slang"] = float(_count_phrases(low, SLANG))  # lol / idk / gonna / swearing
    f["d_missing_apostrophe"] = float(len(MISSING_APOSTROPHE.findall(t)))  # "dont", "im", "thats"
    f["d_emoji"] = float(len(EMOJI.findall(t)))
    f["d_exclaim"] = float(t.count("!"))
    f["d_allcaps_words"] = float(len([w for w in _WORD.findall(t) if len(w) >= 3 and w.isupper()]))
    f["d_first_person"] = float(len(re.findall(r"\b(?:i|i'm|i've|my|me|mine)\b", low))) * per100
    f["d_second_person"] = float(len(re.findall(r"\b(?:you|your|you're|u)\b", low))) * per100
    f["d_repeated_punct"] = float(len(re.findall(r"[!?]{2,}|\.{3,}", t)))  # "!!!", "???", "..."
    # Mechanical correctness: a model essentially never starts a sentence lowercase or drops the final stop.
    f["d_lower_sent_starts"] = sum(1 for s in sents if s[:1].islower()) / ns
    f["d_ends_unpunctuated"] = float(not t.endswith((".", "!", "?", '"', ")")))
    # One clean composite: fully punctuated, no slang, no typos, no emoji, no first-person-chat noise.
    f["d_mechanically_clean"] = float(
        f["d_lower_sent_starts"] == 0
        and f["d_slang"] == 0
        and f["d_missing_apostrophe"] == 0
        and f["d_emoji"] == 0
        and f["d_repeated_punct"] == 0
        and not f["d_ends_unpunctuated"]
    )

    return f


FEATURE_NAMES: list[str] = sorted(extract("A sentence. Another one.").keys())


def describe() -> dict[str, str]:
    """One line per feature, the line a server owner would be shown next to a flag."""
    return {
        "d_not_x_but_y": "uses the 'not X but Y' contrast (SKILL.md §1)",
        "d_rather_than": "'X rather than Y', the same contrast without the negation (§1)",
        "d_tidy_closer": "ends with a summary line that restates instead of adding (§2)",
        "d_deep_sayings": "'at its core', 'what really matters' and similar aphorisms (§3)",
        "d_staged_opener": "announces the point before making it, 'let's dive in' (§4)",
        "d_strawman": "defends against an objection nobody raised (§5)",
        "d_emdash_rate": "em/en dashes per 100 words (§8)",
        "d_emdash_any": "contains at least one em or en dash (§8)",
        "d_hyphen_as_dash": "spaced hyphens used as dashes (§8)",
        "d_triads": "'A, B, and C' triads per message (§6)",
        "d_oxford_comma": "serial comma before 'and'/'or'",
        "d_repeat_openers": "consecutive sentences starting with the same word (§7)",
        "d_hedge_rate": "hedges and qualifiers per 100 words (§9)",
        "d_hyphen_pairs": "hyphenated compound pairs (§10)",
        "d_passive": "passive-voice constructions (§11)",
        "d_sent_len_mean": "mean sentence length in words",
        "d_sent_len_cv": "coefficient of variation of sentence length: low = metronomic",
        "d_sent_count": "number of sentences",
        "d_words": "number of words",
        "d_even_run": "longest run of consecutive sentences within 5 words of each other",
        "d_ai_words": "SKILL.md §12 vocabulary per 100 words (delve, crucial, robust, ...)",
        "d_sales_words": "advertising register per 100 words (§16)",
        "d_ing_riders": "shallow '-ing' riders per 100 words (§15)",
        "d_inflation": "ordinary facts called pivotal or a testament (§13)",
        "d_vague_link": "'associated with' without saying how (§14)",
        "d_copula_dodge": "'serves as' instead of 'is' (§18)",
        "d_bold_markers": "markdown bold (§19) - DEGRADED: newlines are stripped before judging",
        "d_bullet_markers": "list markers (§19) - DEGRADED: newlines are stripped before judging",
        "d_heading_markers": "markdown headings (§20) - DEGRADED: newlines are stripped before judging",
        "d_decorative_arrows": "arrows used as decoration (§20) - DEGRADED",
        "d_curly_quotes": "curly quotes where straight ones would be typed (§21)",
        "d_enumerative": "'there are several reasons', 'a variety of' (mined, §6)",
        "d_hedge_scaffold": "'it is important to', 'keep in mind', 'it is worth noting' (mined, §9)",
        "d_definitional": "'also known as', 'is a type of', 'refers to' (mined, §18)",
        "d_explainer": "'this means that', 'this is because', 'in other words' (mined)",
        "d_safety_referral": "'consult a professional', 'seek medical attention' (mined, §23)",
        "d_register_total": "sum of the five mined assistant-register features: the headline deterministic score",
        "d_chatbot_residue": "assistant wrapper left in: 'I hope this helps', 'As an AI' (§22)",
        "d_disclaimers": "knowledge-limit or 'consult a professional' disclaimers (§23)",
        "d_slang": "chat slang and swearing (human tell)",
        "d_missing_apostrophe": "contractions typed without the apostrophe (human tell)",
        "d_emoji": "emoji count (human tell)",
        "d_exclaim": "exclamation marks",
        "d_allcaps_words": "ALL-CAPS words (human tell)",
        "d_first_person": "first-person pronouns per 100 words",
        "d_second_person": "second-person pronouns per 100 words",
        "d_repeated_punct": "'!!!', '???', '...' (human tell)",
        "d_lower_sent_starts": "fraction of sentences starting lowercase (human tell)",
        "d_ends_unpunctuated": "the message does not end in terminal punctuation (human tell)",
        "d_mechanically_clean": "fully punctuated, no slang, no typos, no emoji: one composite AI tell",
    }


_: Callable[[str], dict[str, float]] = extract
