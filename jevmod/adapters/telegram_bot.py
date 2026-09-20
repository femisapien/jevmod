"""Telegram adapter. Add the bot to a group as admin; it flags by replying in a private admin chat (or the group's
log topic) and can delete or mute when you enable it. Commands for admins: /mod_status, /mod_set, /mod_rule, /mod_log.

    TELEGRAM_TOKEN=... TYPESAFE_API_KEY=... python -m jevmod.adapters.telegram_bot
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from telegram import ChatPermissions, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from ..core import ACTIONS, FREE_MONTHLY, Batcher, ModerationService, Policy, Store
from ..core.policy import LINK_MODES
from ..judge import CATEGORIES, Message

log = logging.getLogger("jevmod.telegram")
store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
service = ModerationService(store)


def tenant_of(chat_id: int) -> str:
    return f"telegram:{chat_id}"


async def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return member.status in ("administrator", "creator")


async def handle_batch(tenant: str, batch: list[tuple[Update, ContextTypes.DEFAULT_TYPE]]) -> None:
    chat_id = batch[0][0].effective_chat.id  # type: ignore[union-attr]
    context = batch[0][1]
    admins = {m.user.id for m in await context.bot.get_chat_administrators(chat_id)}
    # Mirrors Discord's `_trusted`: admins are exempt from judging by default, and `/mod_staff on` can turn
    # that off for a group that wants its moderators held to the same line. Telegram has no per-role trust
    # list to go with it — a group's only distinction is admin vs. member — so this is the whole surface.
    staff_exempt = bool(store.get_meta(tenant).get("staff_exempt", True))
    msgs = []
    for upd, _ in batch:
        m = upd.effective_message
        if m is None:
            continue
        msgs.append(
            Message(
                id=str(m.message_id),
                text=m.text or m.caption or "",
                author=m.from_user.full_name if m.from_user else "",
                channel_topic=store.get_meta(tenant).get("topic", "group chat"),
                author_trusted=bool(staff_exempt and m.from_user and m.from_user.id in admins),
            )
        )
    decisions = await asyncio.to_thread(service.moderate, tenant, msgs)
    policy = service.policy(tenant)
    for (upd, ctx), d in zip(batch, decisions, strict=True):
        if d.reason == "quota":
            if store.note_quota_hit(tenant):
                await _log(
                    ctx,
                    tenant,
                    chat_id,
                    f"jevmod paused this month: the monthly quota of {FREE_MONTHLY:,} judged messages was reached.",
                )
            return
        if d.action == "none":
            continue
        m = upd.effective_message
        if m is None:
            continue
        note = ""
        try:
            if d.action in ("delete", "timeout"):
                await m.delete()
                note = "deleted"
            if d.action == "timeout" and m.from_user:
                until = datetime.now(timezone.utc) + timedelta(minutes=policy.timeout_minutes)
                await ctx.bot.restrict_chat_member(
                    chat_id, m.from_user.id, ChatPermissions(can_send_messages=False), until_date=until
                )
                note = f"deleted, muted {policy.timeout_minutes} min"
        except Exception as exc:
            note = f"could not act: {type(exc).__name__}"
        top = " · ".join(f"{c} {p:.2f}" for c, p in sorted(d.scores.items(), key=lambda kv: -kv[1])[:3])
        text = (
            f"{d.category}  p={d.probability:.2f}  →  {d.action}" + (f" ({note})" if note else "") + "\n"
            f"from {msgs[0].author if len(msgs) == 1 else (m.from_user.full_name if m.from_user else '?')}: "
            f"{(m.text or m.caption or '')[:300]}\n{top}"
        )
        await _log(ctx, tenant, chat_id, text)


async def _log(context: ContextTypes.DEFAULT_TYPE, tenant: str, chat_id: int, text: str) -> None:
    target = store.get_meta(tenant).get("log_chat", chat_id)
    try:
        await context.bot.send_message(int(target), text, disable_web_page_preview=True)
    except Exception as exc:
        log.warning("cannot log to %s: %s", target, exc)


batcher = Batcher(2.0, handle_batch)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.effective_message
    if not m or not update.effective_chat or update.effective_chat.type == "private":
        return
    if not (m.text or m.caption) or (m.from_user and m.from_user.is_bot):
        return
    tenant = tenant_of(update.effective_chat.id)
    if not service.policy(tenant).active():
        return
    batcher.add(tenant, (update, context))


def _reply(update: Update) -> Any:
    assert update.effective_message is not None
    return update.effective_message.reply_text


async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Anti-raid's join counter, the Telegram side of Discord's `on_member_join`. This reuses `service.seen`,
    the exact same in-memory `RepeatWindow` that `local.check()` already uses for repeated messages: one
    sixty-second sliding window per process is the whole mechanism, and a second one here would just be two
    clocks that can disagree. `count()` is keyed by an arbitrary string plus a member id, so the `raid_joins:`
    prefix keeps this window from colliding with the repeated-message window, which is keyed by message text.

    Telegram can report several new members in one service message (someone adding a handful of people at
    once), unlike Discord's one-event-per-member gateway push, so this loops over `new_chat_members`.

    jevmod does not ban, kick or lock a group, and must not start now: tripping this alerts once and stops."""
    m = update.effective_message
    if not m or not m.new_chat_members or not update.effective_chat:
        return
    tenant = tenant_of(update.effective_chat.id)
    policy = service.policy(tenant)
    if not policy.raid_joins:
        return
    bot_id = context.bot.id if context.bot else None
    for member in m.new_chat_members:
        if member.id == bot_id:
            continue  # the bot itself being added to the group is not a join worth counting
        count = service.seen.count(f"raid_joins:{tenant}", str(member.id))
        if count != policy.raid_joins + 1:
            continue  # only the exact join that crosses the threshold alerts, not every one after
        await _log(
            context,
            tenant,
            update.effective_chat.id,
            f"Possible raid: {count} members joined in the last minute, more than the {policy.raid_joins} you "
            "set with /mod_raid. jevmod does not remove members, kick anyone or lock the group — that is a "
            "call for a human, using Telegram's own admin tools.",
        )


# ---------------------------------------------------------------- pure command helpers
#
# Everything below parses already-tokenized command args and mutates a Policy/returns reply text; none of it
# touches an Update, a Context or the network. That is what makes it unit-testable without mocking
# python-telegram-bot's Update/Context objects (see tests/test_telegram_local_commands.py).


def _toggle_list(items: list[str], value: str, action: str) -> list[str]:
    """Pure add/remove for a flat list setting (words, allowlist domains): case/space-normalised, no
    duplicates. Duplicated from discord_bot.py rather than imported from it, because importing discord_bot
    would force discord.py as a dependency of a telegram-only install (see pyproject.toml's separate
    `discord`/`telegram` extras)."""
    out = list(items)
    v = value.strip()
    if action == "add":
        if v and v not in out:
            out.append(v)
    elif action == "remove" and v in out:
        out.remove(v)
    return out


def _chunked_list(items: list[str], limit: int = 3500) -> str:
    """A hundred words (or twenty-five domains) do not read as one long line, and Telegram refuses a message
    over 4096 characters outright. This renders as many as fit under `limit` (default leaves headroom for the
    rest of the reply), in order, then says how many were left off rather than truncating mid-word."""
    if not items:
        return "(none)"
    shown: list[str] = []
    total = 0
    for it in items:
        piece = f"`{it}`"
        added = len(piece) + (2 if shown else 0)  # ", " joiner, except before the first entry
        if total + added > limit:
            break
        shown.append(piece)
        total += added
    text = ", ".join(shown)
    left = len(items) - len(shown)
    if left > 0:
        text += f"\n\n… and {left} more not shown here (still active; this is just the reply, not the list)."
    return text


def _dispatch_link(p: Policy, args: list[str]) -> str:
    """/mod_link <off|invites|allowlist|all> [off|flag|delete|timeout]

    Pure: mutates `p` in place (the caller saves it) and returns the reply text, or raises ValueError with a
    message meant to be shown to the admin verbatim."""
    if not args:
        raise ValueError(f"usage: /mod_link <{'|'.join(LINK_MODES)}> [{'|'.join(ACTIONS)}]")
    mode = args[0]
    action = args[1] if len(args) > 1 else None
    p.set_link_mode(mode)
    if action is not None:
        p.set_link_action(action)
    warn = ""
    if mode == "allowlist" and not p.link_allowlist:
        warn = (
            "\n\nThis will catch every link right now. An empty allowlist means nothing is allowed yet. Add "
            "domains with /mod_linkallow add example.com"
        )
    return f"Links: mode is {mode}, caught links will {p.link_action}.{warn}"


def _dispatch_linkallow(p: Policy, args: list[str]) -> str:
    """/mod_linkallow <add|remove|list> [domain]"""
    if not args or args[0] not in ("add", "remove", "list"):
        raise ValueError("usage: /mod_linkallow <add|remove|list> [domain]")
    action = args[0]
    if action == "list":
        return f"{len(p.link_allowlist)} allowed domain(s):\n{_chunked_list(sorted(p.link_allowlist))}"
    if len(args) < 2 or not args[1].strip():
        raise ValueError("give a domain to add or remove, e.g. example.com")
    domain = args[1].strip().lower()
    p.set_link_allowlist(_toggle_list(p.link_allowlist, domain, action))
    did = "added to" if action == "add" else "removed from"
    return f"{domain} {did} the allowlist. {len(p.link_allowlist)} domain(s) now allowed."


def _dispatch_words(p: Policy, args: list[str]) -> str:
    """/mod_words <add|remove|list> [word or phrase...]  (a phrase with spaces is matched as a whole phrase)"""
    if not args or args[0] not in ("add", "remove", "list"):
        raise ValueError("usage: /mod_words <add|remove|list> [word or phrase]")
    action = args[0]
    if action == "list":
        return (
            f"{len(p.words)} blocked word(s)/phrase(s), action {p.word_action}:\n"
            f"{_chunked_list(sorted(p.words))}"
        )
    word = " ".join(args[1:]).strip()
    if not word:
        raise ValueError("give a word or phrase to add or remove")
    p.set_words(_toggle_list(p.words, word, action))
    did = "added" if action == "add" else "removed"
    return f'"{word}" {did}. {len(p.words)} word(s)/phrase(s) blocked now, action {p.word_action}.'


def _dispatch_pattern(p: Policy, args: list[str]) -> str:
    """/mod_pattern <name> remove   or   /mod_pattern <name> <off|flag|delete|timeout> <regex...>

    `Policy.set_pattern` shells out to check the regex against catastrophic backtracking, which can take up
    to ~5 seconds — the async handler runs this through `asyncio.to_thread`, mirroring `pattern_cmd` in
    discord_bot.py, so it never blocks every other chat's polling loop."""
    if len(args) < 2:
        raise ValueError("usage: /mod_pattern <name> remove | /mod_pattern <name> <off|flag|delete|timeout> <regex>")
    name, second = args[0], args[1]
    key = name.strip().lower().replace(" ", "_")[:30]
    if second == "remove":
        p.set_pattern(name, None)
        return f"Pattern {key} deleted."
    if len(args) < 3:
        raise ValueError("usage: /mod_pattern <name> <off|flag|delete|timeout> <regex>")
    action, pattern = second, " ".join(args[2:])
    p.set_pattern(name, pattern, action)
    return f"Pattern {key} is on: `{p.patterns[key]}`\nWhen it matches jevmod will {p.pattern_actions[key]}."


def _dispatch_raid(p: Policy, args: list[str]) -> str:
    """/mod_raid <joins|-> <repeats|-> [off|flag|delete|timeout]

    "-" leaves that number as it is, mirroring `raid_cmd`'s None-means-leave-it-alone semantics without
    Discord's optional named slash-command parameters, which flat Telegram commands don't have."""
    if len(args) < 2:
        raise ValueError(
            "usage: /mod_raid <joins: 0 or 3-100, or - to leave unchanged> "
            "<repeats: 0 or 3-50, or -> [off|flag|delete|timeout]"
        )

    def _num(tok: str) -> int | None:
        return None if tok == "-" else int(tok)

    try:
        joins = _num(args[0])
        repeats = _num(args[1])
    except ValueError as exc:
        raise ValueError(f"joins and repeats must be whole numbers or -: {exc}") from exc
    action = args[2] if len(args) > 2 else None
    p.set_raid(joins, repeats, action)
    joins_txt = f"alert once after {p.raid_joins} joins in 60 seconds" if p.raid_joins else "off"
    repeats_txt = (
        f"{p.raid_action} after {p.raid_repeats} identical messages in 60 seconds" if p.raid_repeats else "off"
    )
    return (
        f"Raid joins: {joins_txt}\nRaid repeats: {repeats_txt}\n\n"
        "jevmod does not ban, kick or lock the group for either of these — it alerts and, for repeats, acts "
        "on the message the way /mod_set acts on a category."
    )


def _parse_staff_arg(args: list[str]) -> bool:
    """/mod_staff <on|off>. Returns whether admins should now be judged like everyone else. Split out from
    the store write so the token parsing has a right answer that's testable without a Telegram Update."""
    if not args or args[0].lower() not in ("on", "off"):
        raise ValueError("usage: /mod_staff <on|off>  (on = admins are judged too, off = admins exempt, default)")
    return args[0].lower() == "on"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    judged, requests, tokens = store.usage(tenant)
    lines = [f"{c}: {p.actions.get(c, 'off')} at p ≥ {p.thresholds.get(c, 0.9):.2f}" for c in CATEGORIES]
    lines += [f'rule {n}: {p.rule_actions.get(n, "flag")} · "{r}"' for n, r in p.rules.items()]
    # Local rules run before every cost gate and cost nothing, so parity with Discord's /mod status means
    # showing them here too — a rule an admin cannot see is one they forget they set.
    if p.link_mode != "off":
        allow = f", {len(p.link_allowlist)} domain(s) allowed" if p.link_mode == "allowlist" else ""
        lines.append(f"links: {p.link_mode} → {p.link_action}{allow}")
    if p.words:
        lines.append(f"blocked words: {len(p.words)} → {p.word_action}")
    lines += [f'pattern {n}: {p.pattern_actions.get(n, "flag")} · `{r}`' for n, r in p.patterns.items()]
    if p.raid_joins or p.raid_repeats:
        parts = []
        if p.raid_joins:
            parts.append(f"alert after {p.raid_joins} joins/60s")
        if p.raid_repeats:
            parts.append(f"{p.raid_action} after {p.raid_repeats} repeats/60s")
        lines.append("anti-raid: " + "; ".join(parts))
    cap = f"/{FREE_MONTHLY:,}" if FREE_MONTHLY else ""
    lines.append(f"\n{judged:,}{cap} judged this month · {requests} Jev requests · {tokens:,} tokens")
    await _reply(update)("\n".join(lines))  # type: ignore[union-attr]


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mod_set <category> <action> [threshold]"""
    if not await _is_admin(update, context):
        return
    args = context.args or []
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    try:
        p.set_category(args[0], args[1], float(args[2]) if len(args) > 2 else None)
    except (IndexError, ValueError) as exc:
        await _reply(update)(f"usage: /mod_set <category> <off|flag|delete|timeout> [0.5-0.99]\n{exc}")  # type: ignore[union-attr]
        return
    service.save_policy(tenant, p)
    await _reply(update)(f"{args[0]} → {args[1]} at p ≥ {p.thresholds[args[0]]:.2f}")  # type: ignore[union-attr]


async def cmd_rule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mod_rule <name> <text...>   or   /mod_rule <name> remove"""
    if not await _is_admin(update, context):
        return
    args = context.args or []
    if not args:
        await _reply(update)("usage: /mod_rule <name> <rule text> | /mod_rule <name> remove")  # type: ignore[union-attr]
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    text = " ".join(args[1:])
    try:
        p.set_rule(args[0], None if text.strip().lower() == "remove" else text)
    except ValueError as exc:
        await _reply(update)(str(exc))  # type: ignore[union-attr]
        return
    service.save_policy(tenant, p)
    await _reply(update)(f"rules: {p.rules}")  # type: ignore[union-attr]


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run in the chat where you want decisions logged (a private admins group works well)."""
    if not await _is_admin(update, context):
        return
    args = context.args or []
    if not args:
        await _reply(update)("usage: /mod_log <chat id of the group to moderate>  (run this in the log chat)")  # type: ignore[union-attr]
        return
    store.set_meta(tenant_of(int(args[0])), log_chat=update.effective_chat.id)  # type: ignore[union-attr]
    await _reply(update)("decisions for that group will be logged here")  # type: ignore[union-attr]


async def cmd_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    store.set_meta(tenant_of(update.effective_chat.id), topic=" ".join(context.args or [])[:200])  # type: ignore[union-attr]
    await _reply(update)("topic saved")  # type: ignore[union-attr]


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    try:
        text = _dispatch_link(p, context.args or [])
    except ValueError as exc:
        await _reply(update)(str(exc))  # type: ignore[union-attr]
        return
    service.save_policy(tenant, p)
    await _reply(update)(text)  # type: ignore[union-attr]


async def cmd_linkallow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    try:
        text = _dispatch_linkallow(p, context.args or [])
    except ValueError as exc:
        await _reply(update)(str(exc))  # type: ignore[union-attr]
        return
    service.save_policy(tenant, p)
    await _reply(update)(text)  # type: ignore[union-attr]


async def cmd_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    try:
        text = _dispatch_words(p, context.args or [])
    except ValueError as exc:
        await _reply(update)(str(exc))  # type: ignore[union-attr]
        return
    service.save_policy(tenant, p)
    await _reply(update)(text)  # type: ignore[union-attr]


async def cmd_pattern(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    try:
        # to_thread: Policy.set_pattern shells out to validate the regex, which can take up to ~5s — well
        # past what should ever block the event loop every other chat's polling shares.
        text = await asyncio.to_thread(_dispatch_pattern, p, context.args or [])
    except ValueError as exc:
        await _reply(update)(str(exc))  # type: ignore[union-attr]
        return
    service.save_policy(tenant, p)
    await _reply(update)(text)  # type: ignore[union-attr]


async def cmd_raid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    try:
        text = _dispatch_raid(p, context.args or [])
    except ValueError as exc:
        await _reply(update)(str(exc))  # type: ignore[union-attr]
        return
    service.save_policy(tenant, p)
    await _reply(update)(text)  # type: ignore[union-attr]


async def cmd_staff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Whether admins are judged like everyone else. Off (the default) exempts them, same as Discord's
    `/mod staff`; Telegram has no separate "trusted role" concept to go with it, since a group only
    distinguishes admin from member."""
    if not await _is_admin(update, context):
        return
    try:
        judged = _parse_staff_arg(context.args or [])
    except ValueError as exc:
        await _reply(update)(str(exc))  # type: ignore[union-attr]
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    store.set_meta(tenant, staff_exempt=not judged)
    await _reply(update)(  # type: ignore[union-attr]
        "Admins are judged like everyone else now. Your own messages included."
        if judged
        else "Admins are exempt again: never judged."
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("set TELEGRAM_TOKEN (@BotFather → /newbot)")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("mod_status", cmd_status))
    app.add_handler(CommandHandler("mod_set", cmd_set))
    app.add_handler(CommandHandler("mod_rule", cmd_rule))
    app.add_handler(CommandHandler("mod_log", cmd_log))
    app.add_handler(CommandHandler("mod_topic", cmd_topic))
    app.add_handler(CommandHandler("mod_link", cmd_link))
    app.add_handler(CommandHandler("mod_linkallow", cmd_linkallow))
    app.add_handler(CommandHandler("mod_words", cmd_words))
    app.add_handler(CommandHandler("mod_pattern", cmd_pattern))
    app.add_handler(CommandHandler("mod_raid", cmd_raid))
    app.add_handler(CommandHandler("mod_staff", cmd_staff))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))
    app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, on_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
