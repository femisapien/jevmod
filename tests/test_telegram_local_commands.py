"""L3: the Telegram surface for local rules (`/mod_link`, `/mod_linkallow`, `/mod_words`, `/mod_pattern`,
`/mod_raid`, `/mod_staff`) and the `on_new_members` anti-raid join counter.

Like tests/test_discord_local_commands.py, this tests the parts that have a right answer without a live
bot: the pure dispatch functions the commands are built from (they take parsed args + a Policy and return
reply text or raise ValueError, never touching an Update or the network) and the join-counting/alerting
logic in `on_new_members` against a mocked Update/Context, the same way test_discord_local_commands.py
mocks a Discord guild and member. The command callbacks themselves (`cmd_link`, `cmd_words`, ...) are not
covered here: exercising them needs a mocked `telegram.Update`/`Context` with working `effective_message`,
`effective_chat` and `context.bot` plumbing, which is framework wiring rather than logic with a right
answer, and is genuinely not covered by this suite.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

telegram = pytest.importorskip("telegram")

from jevmod.core import Policy  # noqa: E402

# ---- _toggle_list: pure add/remove, no Telegram


def test_toggle_add_appends_once():
    from jevmod.adapters.telegram_bot import _toggle_list

    assert _toggle_list(["a"], "b", "add") == ["a", "b"]


def test_toggle_add_is_idempotent():
    from jevmod.adapters.telegram_bot import _toggle_list

    assert _toggle_list(["a", "b"], "b", "add") == ["a", "b"]


def test_toggle_remove_drops_it():
    from jevmod.adapters.telegram_bot import _toggle_list

    assert _toggle_list(["a", "b"], "a", "remove") == ["b"]


def test_toggle_does_not_mutate_the_input_list():
    from jevmod.adapters.telegram_bot import _toggle_list

    original = ["a"]
    _toggle_list(original, "b", "add")
    assert original == ["a"]


# ---- _chunked_list: many entries cannot be dumped into one reply without thought


def test_chunked_list_empty_reads_as_none():
    from jevmod.adapters.telegram_bot import _chunked_list

    assert _chunked_list([]) == "(none)"


def test_chunked_list_truncates_and_says_how_many_were_left_off():
    from jevmod.adapters.telegram_bot import _chunked_list

    words = [f"word{i}" for i in range(500)]
    text = _chunked_list(words, limit=200)
    assert "more not shown" in text
    shown = text.split("\n\n")[0].count("`") // 2
    assert shown < len(words)


# ---- _dispatch_link


def test_dispatch_link_sets_mode_and_action():
    from jevmod.adapters.telegram_bot import _dispatch_link

    p = Policy()
    text = _dispatch_link(p, ["all", "delete"])
    assert p.link_mode == "all"
    assert p.link_action == "delete"
    assert "delete" in text


def test_dispatch_link_no_args_raises_usage():
    from jevmod.adapters.telegram_bot import _dispatch_link

    p = Policy()
    with pytest.raises(ValueError, match="usage: /mod_link"):
        _dispatch_link(p, [])


def test_dispatch_link_unknown_mode_raises():
    from jevmod.adapters.telegram_bot import _dispatch_link

    p = Policy()
    with pytest.raises(ValueError):
        _dispatch_link(p, ["nonsense"])


def test_dispatch_link_empty_allowlist_warns():
    from jevmod.adapters.telegram_bot import _dispatch_link

    p = Policy()
    text = _dispatch_link(p, ["allowlist"])
    assert "will catch every link" in text


# ---- _dispatch_linkallow


def test_dispatch_linkallow_add_then_list():
    from jevmod.adapters.telegram_bot import _dispatch_linkallow

    p = Policy()
    _dispatch_linkallow(p, ["add", "example.com"])
    assert p.link_allowlist == ["example.com"]
    text = _dispatch_linkallow(p, ["list"])
    assert "example.com" in text


def test_dispatch_linkallow_remove():
    from jevmod.adapters.telegram_bot import _dispatch_linkallow

    p = Policy()
    p.set_link_allowlist(["example.com"])
    _dispatch_linkallow(p, ["remove", "example.com"])
    assert p.link_allowlist == []


def test_dispatch_linkallow_missing_domain_raises():
    from jevmod.adapters.telegram_bot import _dispatch_linkallow

    p = Policy()
    with pytest.raises(ValueError, match="give a domain"):
        _dispatch_linkallow(p, ["add"])


def test_dispatch_linkallow_bad_action_raises():
    from jevmod.adapters.telegram_bot import _dispatch_linkallow

    p = Policy()
    with pytest.raises(ValueError, match="usage: /mod_linkallow"):
        _dispatch_linkallow(p, ["nonsense"])


# ---- _dispatch_words


def test_dispatch_words_add_phrase_with_spaces():
    from jevmod.adapters.telegram_bot import _dispatch_words

    p = Policy()
    text = _dispatch_words(p, ["add", "buy", "now", "cheap"])
    assert p.words == ["buy now cheap"]
    assert "buy now cheap" in text


def test_dispatch_words_remove():
    from jevmod.adapters.telegram_bot import _dispatch_words

    p = Policy()
    p.set_words(["spam"])
    _dispatch_words(p, ["remove", "spam"])
    assert p.words == []


def test_dispatch_words_missing_word_raises():
    from jevmod.adapters.telegram_bot import _dispatch_words

    p = Policy()
    with pytest.raises(ValueError, match="give a word"):
        _dispatch_words(p, ["add"])


def test_dispatch_words_list_shows_action():
    from jevmod.adapters.telegram_bot import _dispatch_words

    p = Policy()
    p.set_words(["spam"])
    p.set_word_action("delete")
    text = _dispatch_words(p, ["list"])
    assert "delete" in text and "spam" in text


# ---- _dispatch_pattern


def test_dispatch_pattern_add_then_remove():
    from jevmod.adapters.telegram_bot import _dispatch_pattern

    p = Policy()
    text = _dispatch_pattern(p, ["scamlink", "flag", "free", "nitro"])
    assert "scamlink" in p.patterns
    assert p.patterns["scamlink"] == "free nitro"
    assert "scamlink" in text

    text2 = _dispatch_pattern(p, ["scamlink", "remove"])
    assert "scamlink" not in p.patterns
    assert "deleted" in text2


def test_dispatch_pattern_too_few_args_raises():
    from jevmod.adapters.telegram_bot import _dispatch_pattern

    p = Policy()
    with pytest.raises(ValueError, match="usage: /mod_pattern"):
        _dispatch_pattern(p, ["onlyname"])


def test_dispatch_pattern_bad_action_raises():
    from jevmod.adapters.telegram_bot import _dispatch_pattern

    p = Policy()
    with pytest.raises(ValueError):
        _dispatch_pattern(p, ["name", "nonsense", "abc"])


# ---- _dispatch_raid


def test_dispatch_raid_sets_joins_and_repeats():
    from jevmod.adapters.telegram_bot import _dispatch_raid

    p = Policy()
    text = _dispatch_raid(p, ["5", "10", "delete"])
    assert p.raid_joins == 5
    assert p.raid_repeats == 10
    assert p.raid_action == "delete"
    assert "alert once after 5 joins" in text


def test_dispatch_raid_dash_leaves_value_unchanged():
    from jevmod.adapters.telegram_bot import _dispatch_raid

    p = Policy()
    p.set_raid(joins=5, repeats=10)
    _dispatch_raid(p, ["-", "20"])
    assert p.raid_joins == 5
    assert p.raid_repeats == 20


def test_dispatch_raid_non_numeric_raises():
    from jevmod.adapters.telegram_bot import _dispatch_raid

    p = Policy()
    with pytest.raises(ValueError, match="whole numbers"):
        _dispatch_raid(p, ["abc", "10"])


def test_dispatch_raid_out_of_range_raises():
    from jevmod.adapters.telegram_bot import _dispatch_raid

    p = Policy()
    with pytest.raises(ValueError):
        _dispatch_raid(p, ["1", "10"])  # 1 is below the 3-100 range Policy.set_raid enforces


def test_dispatch_raid_too_few_args_raises():
    from jevmod.adapters.telegram_bot import _dispatch_raid

    p = Policy()
    with pytest.raises(ValueError, match="usage: /mod_raid"):
        _dispatch_raid(p, ["5"])


# ---- _parse_staff_arg


def test_parse_staff_on():
    from jevmod.adapters.telegram_bot import _parse_staff_arg

    assert _parse_staff_arg(["on"]) is True


def test_parse_staff_off():
    from jevmod.adapters.telegram_bot import _parse_staff_arg

    assert _parse_staff_arg(["off"]) is False


def test_parse_staff_missing_raises():
    from jevmod.adapters.telegram_bot import _parse_staff_arg

    with pytest.raises(ValueError, match="usage: /mod_staff"):
        _parse_staff_arg([])


def test_parse_staff_bad_token_raises():
    from jevmod.adapters.telegram_bot import _parse_staff_arg

    with pytest.raises(ValueError):
        _parse_staff_arg(["maybe"])


# ---- on_new_members: the join counter and the one-message trip, Telegram's side of on_member_join


def _reload_bot(tmp_path):
    os.environ["JEVMOD_DB"] = str(tmp_path / "join.sqlite")
    import importlib

    from jevmod.adapters import telegram_bot

    importlib.reload(telegram_bot)
    return telegram_bot


def _update_with_new_members(chat_id: int, member_ids: list[int]) -> "telegram.Update":
    chat = MagicMock(spec=telegram.Chat)
    chat.id = chat_id
    members = []
    for mid in member_ids:
        user = MagicMock(spec=telegram.User)
        user.id = mid
        members.append(user)
    message = MagicMock(spec=telegram.Message)
    message.new_chat_members = members
    update = MagicMock(spec=telegram.Update)
    update.effective_chat = chat
    update.effective_message = message
    return update


def _context_with_bot(bot_id: int = -1):
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.id = bot_id
    ctx.bot.send_message = AsyncMock()
    return ctx


def test_join_below_threshold_sends_nothing(tmp_path):
    bot_module = _reload_bot(tmp_path)
    tenant = bot_module.tenant_of(1)
    p = bot_module.service.policy(tenant)
    p.set_raid(joins=3, repeats=0)
    bot_module.service.save_policy(tenant, p)
    ctx = _context_with_bot()

    asyncio.run(bot_module.on_new_members(_update_with_new_members(1, [10, 11]), ctx))
    ctx.bot.send_message.assert_not_awaited()


def test_join_at_threshold_plus_one_alerts_exactly_once(tmp_path):
    bot_module = _reload_bot(tmp_path)
    tenant = bot_module.tenant_of(1)
    p = bot_module.service.policy(tenant)
    p.set_raid(joins=3, repeats=0)
    bot_module.service.save_policy(tenant, p)
    ctx = _context_with_bot()

    for member_id in range(1, 6):  # 5 distinct joins against a threshold of 3, one at a time like Discord
        asyncio.run(bot_module.on_new_members(_update_with_new_members(1, [member_id]), ctx))

    ctx.bot.send_message.assert_awaited_once()  # the 4th join trips it; the 5th must not alert again
    (_target, message), _kwargs = ctx.bot.send_message.call_args
    assert "Possible raid" in message
    assert "does not remove members, kick anyone or lock the group" in message


def test_raid_joins_off_never_counts_or_alerts(tmp_path):
    bot_module = _reload_bot(tmp_path)
    tenant = bot_module.tenant_of(1)
    assert bot_module.service.policy(tenant).raid_joins == 0  # default
    ctx = _context_with_bot()

    for member_id in range(1, 10):
        asyncio.run(bot_module.on_new_members(_update_with_new_members(1, [member_id]), ctx))
    ctx.bot.send_message.assert_not_awaited()


def test_bot_itself_joining_is_not_counted(tmp_path):
    """A group creator adding the bot must not itself read as one join toward the raid threshold."""
    bot_module = _reload_bot(tmp_path)
    tenant = bot_module.tenant_of(1)
    p = bot_module.service.policy(tenant)
    p.set_raid(joins=3, repeats=0)
    bot_module.service.save_policy(tenant, p)
    ctx = _context_with_bot(bot_id=999)

    # the bot's own id arrives inside new_chat_members when it is added; three more real joins should still
    # need the same threshold, not be one join closer because the bot was skipped incorrectly.
    asyncio.run(bot_module.on_new_members(_update_with_new_members(1, [999]), ctx))
    ctx.bot.send_message.assert_not_awaited()
    for member_id in (1, 2, 3):
        asyncio.run(bot_module.on_new_members(_update_with_new_members(1, [member_id]), ctx))
    ctx.bot.send_message.assert_not_awaited()  # only 3 real joins so far, threshold is 3 (trips on the 4th)


def test_multiple_new_members_in_one_update_are_each_counted(tmp_path):
    """Telegram can report several members in a single service message; Discord's on_member_join never sees
    that shape (one gateway event per member), so this is the one behavior genuinely specific to Telegram."""
    bot_module = _reload_bot(tmp_path)
    tenant = bot_module.tenant_of(1)
    p = bot_module.service.policy(tenant)
    p.set_raid(joins=3, repeats=0)
    bot_module.service.save_policy(tenant, p)
    ctx = _context_with_bot()

    asyncio.run(bot_module.on_new_members(_update_with_new_members(1, [1, 2, 3, 4, 5]), ctx))
    ctx.bot.send_message.assert_awaited_once()  # the 4th member in the batch trips it, the 5th must not repeat
