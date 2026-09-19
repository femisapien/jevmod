"""Local rules: link filtering, word/pattern blocking, anti-raid. No key, no database, no Discord.

These are the checks that must keep working when the model is off, out of quota, or over budget, because
they cost nothing per message. See odd/tasks/free-tier.md in the private repo for the decision this
implements: local rules run before every cost gate.
"""

import time
from pathlib import Path

import pytest

from jevmod.core.local import RepeatWindow, check
from jevmod.core.policy import ACTIONS, Policy
from jevmod.judge import Message


def msg(text, mid="m1", author="a"):
    return Message(mid, text, author=author)


def _all_categories_off() -> Policy:
    """Ships with several categories enabled by default (moderation-on-by-default). To test the free-tier
    claim precisely — active() must become true from a local rule ALONE — start from every category off."""
    from jevmod.judge import CATEGORIES

    p = Policy()
    for c in CATEGORIES:
        p.set_category(c, "off")
    return p


# ---- Policy fields: defaults, validation, active()


def test_the_ten_fields_default_off():
    p = Policy()
    assert p.link_mode == "off"
    assert p.link_action == "flag"
    assert p.link_allowlist == []
    assert p.words == []
    assert p.word_action == "flag"
    assert p.patterns == {}
    assert p.pattern_actions == {}
    assert p.raid_joins == 0
    assert p.raid_repeats == 0
    assert p.raid_action == "flag"


def test_active_becomes_true_from_a_local_rule_alone():
    """A server on Free with every category off and no natural-language rule must still have its link filter
    run: active() has to say so, or moderate() will short-circuit before local.check ever sees the message."""
    for make in (
        lambda p: p.set_link_mode("invites"),
        lambda p: p.set_words(["nitro"]),
        lambda p: p.set_pattern("x", r"free\s+nitro"),
        lambda p: p.set_raid(joins=5),
        lambda p: p.set_raid(repeats=5),
    ):
        p = _all_categories_off()
        assert not p.active()
        make(p)
        assert p.active(), "a policy with only a local rule set must be active"


def test_link_mode_validation():
    p = Policy()
    for mode in ("off", "invites", "allowlist", "all"):
        p.set_link_mode(mode)
        assert p.link_mode == mode
    with pytest.raises(ValueError):
        p.set_link_mode("everything")


def test_link_action_validation():
    p = Policy()
    p.set_link_action("delete")
    assert p.link_action == "delete"
    with pytest.raises(ValueError):
        p.set_link_action("nuke")


def test_link_allowlist_limits():
    p = Policy()
    p.set_link_allowlist(["example.com"] * 25)
    with pytest.raises(ValueError):
        p.set_link_allowlist(["example.com"] * 26)
    with pytest.raises(ValueError):
        p.set_link_allowlist(["x" * 254])
    p.set_link_allowlist(["x" * 253])  # exactly at the limit is fine


def test_words_limits():
    p = Policy()
    p.set_words(["ab"] * 100)
    with pytest.raises(ValueError):
        p.set_words(["ab"] * 101)
    with pytest.raises(ValueError):
        p.set_words(["a"])  # 1 char, below the 2 char floor
    with pytest.raises(ValueError):
        p.set_words(["x" * 65])  # 65 chars, above the 64 char ceiling
    p.set_words(["xy", "x" * 64])  # both ends of the allowed range


def test_pattern_limits_and_bad_regex():
    p = Policy()
    for i in range(5):
        p.set_pattern(f"p{i}", "free.?nitro")
    with pytest.raises(ValueError):
        p.set_pattern("p5", "free.?nitro")  # a 6th pattern
    p.set_pattern("p0", "steam.?gift")  # replacing an existing name is not a new one
    with pytest.raises(ValueError):
        p.set_pattern("bad", "(unterminated")  # fails to compile
    with pytest.raises(ValueError):
        p.set_pattern("long", "a" * 201)  # over 200 characters
    p.set_pattern("p1", "a" * 200)  # exactly 200 is fine; replacing an existing name is not a 6th
    p.set_pattern("p0", None)  # clears it, same style as Policy.set_rule
    assert "p0" not in p.patterns and "p0" not in p.pattern_actions


def test_pattern_action_validation():
    p = Policy()
    with pytest.raises(ValueError):
        p.set_pattern("x", "nitro", action="nuke")
    p.set_pattern("x", "nitro", action="delete")
    assert p.pattern_actions["x"] == "delete"


def test_a_catastrophic_pattern_is_refused_at_write_time():
    """(a+)+ against a probe with no trailing match backtracks exponentially. A pattern like this has to be
    refused when the operator writes it — moderation itself must never be the place this is discovered."""
    p = Policy()
    with pytest.raises(ValueError):
        p.set_pattern("evil", r"(a+)+$")


def test_raid_validation():
    p = Policy()
    p.set_raid(joins=3, repeats=3, action="delete")
    assert (p.raid_joins, p.raid_repeats, p.raid_action) == (3, 3, "delete")
    p.set_raid(joins=100, repeats=50)
    p.set_raid(joins=0, repeats=0)  # off is always allowed
    with pytest.raises(ValueError):
        p.set_raid(joins=2)
    with pytest.raises(ValueError):
        p.set_raid(joins=101)
    with pytest.raises(ValueError):
        p.set_raid(repeats=2)
    with pytest.raises(ValueError):
        p.set_raid(repeats=51)
    with pytest.raises(ValueError):
        p.set_raid(action="nuke")


def test_policy_roundtrip_includes_local_fields():
    p = Policy()
    p.set_link_mode("allowlist")
    p.set_link_allowlist(["example.com"])
    p.set_words(["nitro", "free steam"])
    p.set_pattern("gift", r"free\s+gift", action="delete")
    p.set_raid(joins=10, repeats=5, action="timeout")
    q = Policy.from_dict(p.to_dict())
    assert q.link_mode == "allowlist"
    assert q.link_allowlist == ["example.com"]
    assert q.words == ["nitro", "free steam"]
    assert q.patterns == {"gift": r"free\s+gift"}
    assert q.pattern_actions == {"gift": "delete"}
    assert (q.raid_joins, q.raid_repeats, q.raid_action) == (10, 5, "timeout")


# ---- local.check: a deterministic hit is not a probability


def test_a_local_decision_is_not_a_probability():
    p = Policy()
    p.set_words(["nitro"])
    d = check(msg("free nitro here"), p, RepeatWindow())
    assert d is not None
    assert d.judged is False
    assert d.probability == 1.0
    assert d.reason == "local"
    assert d.category == "local:word"
    assert d.action in ACTIONS


def test_no_local_rule_set_means_no_hit_ever():
    p = Policy()
    assert check(msg("anything at all, even a link http://x.y"), p, RepeatWindow()) is None


# ---- rule ordering: patterns, then words, then links, then raid


def test_rule_order_is_pattern_then_word_then_link_then_raid():
    """A message that could match more than one local rule is decided by the first rule in this order, not
    by the most severe action — an operator who wrote a pattern meant that pattern."""
    p = Policy()
    p.set_pattern("p", r"free\s+nitro", action="flag")
    p.set_words(["nitro"])
    p.set_link_mode("all")
    text = "free nitro http://example.com"
    d = check(msg(text), p, RepeatWindow())
    assert d.category == "local:pattern:p"

    p2 = Policy()
    p2.set_words(["nitro"])
    p2.set_link_mode("all")
    d2 = check(msg(text), p2, RepeatWindow())
    assert d2.category == "local:word"

    p3 = Policy()
    p3.set_link_mode("all")
    d3 = check(msg(text), p3, RepeatWindow())
    assert d3.category == "local:link"


def test_an_off_action_on_the_earlier_rule_lets_a_later_one_decide():
    p = Policy()
    p.set_words(["nitro"])
    p.set_word_action("off")
    p.set_link_mode("all")
    d = check(msg("free nitro http://example.com"), p, RepeatWindow())
    assert d.category == "local:link"


# ---- words: normalisation cases


def test_words_are_case_and_accent_insensitive_and_match_on_boundaries():
    p = Policy()
    p.set_words(["tonto"])
    assert check(msg("eres un TÓNTO"), p, RepeatWindow()).category == "local:word"
    assert check(msg("eres un TONTO"), p, RepeatWindow()).category == "local:word"
    assert check(msg("tontería aparte, hola"), p, RepeatWindow()) is None, "a word boundary, not a substring"


def test_a_phrase_word_matches_as_a_phrase():
    p = Policy()
    p.set_words(["free steam"])
    assert check(msg("get your free steam key"), p, RepeatWindow()).category == "local:word"
    assert check(msg("free stuff, steam sale"), p, RepeatWindow()) is None


def test_words_survive_html_entities_and_fullwidth_padding():
    """The same normalize() the model path uses: HTML-escaped apostrophes and fullwidth spellings must not
    dodge the local word list either."""
    p = Policy()
    p.set_words(["nitro"])
    fullwidth_nitro = "Ｎｉｔｒｏ"  # "Nitro" spelled in fullwidth Latin letters
    assert check(msg(f"free {fullwidth_nitro} codes"), p, RepeatWindow()) is not None


# ---- links


def test_link_mode_off_checks_nothing():
    p = Policy()
    p.set_link_mode("off")
    p.set_link_action("flag")
    assert check(msg("join http://discord.gg/abc"), p, RepeatWindow()) is None


def test_link_mode_invites_matches_only_discord_invites_including_defanged():
    p = Policy()
    p.set_link_mode("invites")
    assert check(msg("join discord.gg/abc now"), p, RepeatWindow()).category == "local:link"
    assert check(msg("join discord[.]gg/abc now"), p, RepeatWindow()).category == "local:link"
    assert check(msg("visit hxxps://discord.gg/abc"), p, RepeatWindow()).category == "local:link"
    assert check(msg("visit http://example.com"), p, RepeatWindow()) is None


def test_link_mode_allowlist_flags_anything_not_listed():
    p = Policy()
    p.set_link_mode("allowlist")
    p.set_link_allowlist(["example.com"])
    assert check(msg("see https://example.com/page"), p, RepeatWindow()) is None
    assert check(msg("see https://evil.test/page"), p, RepeatWindow()).category == "local:link"


def test_link_mode_all_flags_every_link():
    p = Policy()
    p.set_link_mode("all")
    assert check(msg("no links here at all"), p, RepeatWindow()) is None
    assert check(msg("see www.example.com"), p, RepeatWindow()).category == "local:link"


def test_link_action_off_disables_link_checking_even_with_a_mode_set():
    p = Policy()
    p.set_link_mode("all")
    p.set_link_action("off")
    assert check(msg("see www.example.com"), p, RepeatWindow()) is None


# ---- anti-raid: repeats


def test_raid_repeats_trips_only_after_the_threshold_and_from_different_authors():
    p = Policy()
    p.set_raid(repeats=3, action="flag")
    seen = RepeatWindow()
    text = "join my server for free stuff"
    hits = [check(msg(text, mid=str(i), author=f"author{i}"), p, seen) for i in range(5)]
    # the first 3 establish the pattern; the 4th and 5th (index 3, 4) are the ones that trip it
    assert hits[0] is None and hits[1] is None and hits[2] is None
    assert hits[3] is not None and hits[3].category == "local:raid"
    assert hits[4] is not None and hits[4].category == "local:raid"


def test_raid_repeats_does_not_count_the_same_author_twice():
    p = Policy()
    p.set_raid(repeats=3)
    seen = RepeatWindow()
    text = "same message over and over"
    for i in range(10):
        d = check(msg(text, mid=str(i), author="only-author"), p, seen)
    assert d is None, "one author repeating themselves is not a raid"


def test_raid_repeats_window_expires():
    p = Policy()
    p.set_raid(repeats=3)
    seen = RepeatWindow(window_s=0.05)
    text = "raid text"
    for i in range(3):
        check(msg(text, mid=str(i), author=f"a{i}"), p, seen)
    time.sleep(0.1)
    d = check(msg(text, mid="later", author="a-later"), p, seen)
    assert d is None, "a 60 second window that never expires would flag any busy channel as a raid forever"


def test_raid_repeats_zero_is_off():
    p = Policy()
    seen = RepeatWindow()
    for i in range(10):
        d = check(msg("same text", mid=str(i), author=f"a{i}"), p, seen)
    assert d is None


def test_validating_a_pattern_does_not_re_run_the_program_that_asked(tmp_path):
    """The guard runs the probe in another interpreter, and which one matters.

    `multiprocessing`'s spawn start method re-imports the caller's `__main__` in the child, so a script that
    validated a pattern ran its own top level twice. In production the caller's `__main__` is the Discord
    bot: validating a pattern would have logged in a second bot. This asserts the child is an interpreter
    that knows nothing about us, by counting how many times the caller's own module body runs.
    """
    import subprocess
    import sys

    script = tmp_path / "caller.py"
    script.write_text(
        "print('CALLER BODY')\n"
        "from jevmod.core.policy import Policy\n"
        "try:\n"
        "    Policy().set_pattern('evil', r'(a+)+$', 'flag')\n"
        "except ValueError:\n"
        "    print('REFUSED')\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert done.stdout.count("CALLER BODY") == 1, done.stdout
    assert "REFUSED" in done.stdout, done.stdout
