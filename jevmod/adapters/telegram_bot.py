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

from ..core import FREE_MONTHLY, Batcher, ModerationService, Store
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
                author_trusted=bool(m.from_user and m.from_user.id in admins),
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
                    f"jevmod paused this month: free plan covers {FREE_MONTHLY:,} judged messages.",
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


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    tenant = tenant_of(update.effective_chat.id)  # type: ignore[union-attr]
    p = service.policy(tenant)
    judged, requests, tokens = store.usage(tenant)
    lines = [f"{c}: {p.actions.get(c, 'off')} at p ≥ {p.thresholds.get(c, 0.9):.2f}" for c in CATEGORIES]
    lines += [f'rule {n}: {p.rule_actions.get(n, "flag")} · "{r}"' for n, r in p.rules.items()]
    lines.append(f"\n{judged:,}/{FREE_MONTHLY:,} judged this month · {requests} Jev requests · {tokens:,} tokens")
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
    app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, on_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
