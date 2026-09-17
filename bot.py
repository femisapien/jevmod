"""jevmod: Discord moderation with Jev. Plug and play: invite the bot, it flags in #jevmod-log; tune with /mod.

    set DISCORD_TOKEN=...  and  TYPESAFE_API_KEY=...
    .venv/Scripts/python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import timedelta

import discord
from discord import app_commands

from jevmod.judge import CATEGORIES, Judge, Message
from jevmod.store import ACTIONS, FREE_MONTHLY, Store

log = logging.getLogger("jevmod")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BATCH_WINDOW_S = 2.0  # messages from one guild within this window share one Jev request

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
_judge: Judge | None = None


def get_judge() -> Judge:
    global _judge
    if _judge is None:
        _judge = Judge()  # created on first use so the module imports without a key
    return _judge

pending: dict[int, list[discord.Message]] = defaultdict(list)
flush_tasks: dict[int, asyncio.Task] = {}


# ------------------------------------------------------------------ moderation loop
@bot.event
async def on_ready() -> None:
    await tree.sync()
    log.info("logged in as %s in %d guilds", bot.user, len(bot.guilds))


@bot.event
async def on_message(msg: discord.Message) -> None:
    if msg.author.bot or not msg.guild or not msg.content:
        return
    cfg = store.get(msg.guild.id)
    if not cfg.enabled_categories() and not cfg.rules:
        return
    if store.over_quota(cfg):
        return
    pending[msg.guild.id].append(msg)
    if msg.guild.id not in flush_tasks or flush_tasks[msg.guild.id].done():
        flush_tasks[msg.guild.id] = asyncio.create_task(_flush_later(msg.guild.id))


async def _flush_later(guild_id: int) -> None:
    await asyncio.sleep(BATCH_WINDOW_S)
    batch, pending[guild_id] = pending[guild_id], []
    if not batch:
        return
    guild = batch[0].guild
    cfg = store.get(guild_id)
    trusted = set(cfg.trusted_roles)
    msgs = [
        Message(
            id=str(m.id),
            text=m.content,
            author=m.author.display_name,
            channel_topic=cfg.channel_topics.get(str(m.channel.id), getattr(m.channel, "topic", "") or "general chat"),
            author_trusted=bool(m.author.guild_permissions.manage_messages or trusted & {r.id for r in m.author.roles}),
        )
        for m in batch
    ]
    judge = get_judge()
    before = (judge.requests, judge.input_tokens, judge.judged_messages)
    try:
        verdicts = await asyncio.to_thread(judge.judge, msgs, cfg.enabled_categories(), cfg.rules)
    except Exception as exc:  # fail open: never block a community because Jev is down
        log.warning("judge failed for guild %s: %s", guild_id, exc)
        return
    store.add_usage(
        guild_id,
        judge.judged_messages - before[2],
        judge.requests - before[0],
        judge.input_tokens - before[1],
    )
    for m, v in zip(batch, verdicts, strict=True):
        if not v.judged:
            continue
        hits = [(c, p, cfg.actions.get(c, "off")) for c, p in v.scores.items() if p >= cfg.thresholds.get(c, 1.0)]
        hits += [(f"rule:{n}", p, cfg.rule_actions.get(n, "flag")) for n, p in v.custom.items() if p >= 0.75]
        hits = [h for h in hits if h[2] != "off"]
        if not hits:
            continue
        category, p, action = max(hits, key=lambda h: (ACTIONS.index(h[2]), h[1]))
        await _act(guild, m, category, p, action, v)


async def _act(guild: discord.Guild, m: discord.Message, category: str, p: float, action: str, v) -> None:
    cfg = store.get(guild.id)
    store.log_decision(guild.id, m.channel.id, m.id, m.author.id, category, p, action, m.content)
    note = ""
    try:
        if action in ("delete", "timeout"):
            await m.delete()
            note = "deleted"
        if action == "timeout":
            await m.author.timeout(timedelta(minutes=cfg.timeout_minutes), reason=f"jevmod: {category} p={p:.2f}")
            note = f"deleted, timed out {cfg.timeout_minutes} min"
    except discord.Forbidden:
        note = "missing permissions to act"
    channel = await _log_channel(guild, cfg)
    if channel:
        scores = " · ".join(f"{c} {q:.2f}" for c, q in sorted({**v.scores, **v.custom}.items(), key=lambda kv: -kv[1])[:3])
        embed = discord.Embed(
            title=f"{category}  p={p:.2f}  →  {action}" + (f" ({note})" if note else ""),
            description=m.content[:500],
            colour=0x2FBF83 if action == "flag" else 0xD9A441,
        )
        embed.add_field(name="author", value=m.author.mention, inline=True)
        embed.add_field(name="channel", value=m.channel.mention, inline=True)
        embed.set_footer(text=f"{scores}   ·   react ❌ if this was wrong")
        sent = await channel.send(embed=embed)
        await sent.add_reaction("❌")


async def _log_channel(guild: discord.Guild, cfg) -> discord.TextChannel | None:
    if cfg.log_channel:
        ch = guild.get_channel(cfg.log_channel)
        if isinstance(ch, discord.TextChannel):
            return ch
    existing = discord.utils.get(guild.text_channels, name="jevmod-log")
    if existing:
        cfg.log_channel = existing.id
        store.save(cfg)
        return existing
    try:
        overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False)}
        ch = await guild.create_text_channel("jevmod-log", overwrites=overwrites, reason="jevmod decisions log")
        cfg.log_channel = ch.id
        store.save(cfg)
        return ch
    except discord.Forbidden:
        return None


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    """A moderator reacting ❌ on a log entry means 'false positive': nudge that category's threshold up."""
    if str(payload.emoji) != "❌" or payload.user_id == (bot.user.id if bot.user else 0):
        return
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if not guild:
        return
    cfg = store.get(guild.id)
    if payload.channel_id != cfg.log_channel:
        return
    channel = guild.get_channel(payload.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    msg = await channel.fetch_message(payload.message_id)
    if not msg.embeds or not msg.embeds[0].title:
        return
    category = msg.embeds[0].title.split()[0]
    if category in cfg.thresholds:
        cfg.thresholds[category] = min(0.99, round(cfg.thresholds[category] + 0.03, 2))
        store.save(cfg)
        await msg.reply(f"noted: threshold for **{category}** is now {cfg.thresholds[category]:.2f}", mention_author=False)


# ------------------------------------------------------------------ /mod commands
mod = app_commands.Group(name="mod", description="jevmod settings", default_permissions=discord.Permissions(manage_guild=True))


@mod.command(name="status", description="What jevmod is doing in this server and this month's usage")
async def status(itx: discord.Interaction) -> None:
    cfg = store.get(itx.guild_id)
    judged, requests, tokens = store.usage(itx.guild_id)
    lines = [f"**{c}**: {cfg.actions[c]} at p ≥ {cfg.thresholds[c]:.2f}" for c in CATEGORIES]
    lines += [f"**rule {n}**: {cfg.rule_actions.get(n, 'flag')} · \"{r}\"" for n, r in cfg.rules.items()]
    quota = f"{judged}/{FREE_MONTHLY} judged this month (free plan)" if cfg.plan == "free" else f"{judged} judged this month (pro)"
    lines.append(f"\n{quota} · {requests} Jev requests · {tokens:,} tokens · log: {f'<#{cfg.log_channel}>' if cfg.log_channel else 'auto'}")
    await itx.response.send_message("\n".join(lines), ephemeral=True)


@mod.command(name="set", description="Set the action and threshold for a category")
@app_commands.describe(category="spam, scam, harassment, nsfw, offtopic", action="off, flag, delete, timeout", threshold="0.5 to 0.99")
async def set_cmd(itx: discord.Interaction, category: str, action: str, threshold: float | None = None) -> None:
    cfg = store.get(itx.guild_id)
    if category not in CATEGORIES or action not in ACTIONS:
        await itx.response.send_message(f"category must be one of {', '.join(CATEGORIES)}; action one of {', '.join(ACTIONS)}", ephemeral=True)
        return
    cfg.actions[category] = action
    if threshold is not None:
        cfg.thresholds[category] = max(0.5, min(0.99, threshold))
    store.save(cfg)
    await itx.response.send_message(f"**{category}** → {action} at p ≥ {cfg.thresholds[category]:.2f}", ephemeral=True)


@mod.command(name="rule", description="Add or remove a rule in plain language (e.g. 'no politics')")
@app_commands.describe(name="short name", text="the rule as you would say it to a member; leave empty to remove", action="flag, delete, timeout")
async def rule_cmd(itx: discord.Interaction, name: str, text: str | None = None, action: str = "flag") -> None:
    cfg = store.get(itx.guild_id)
    name = name.strip().lower().replace(" ", "_")[:30]
    if not text:
        cfg.rules.pop(name, None)
        cfg.rule_actions.pop(name, None)
        store.save(cfg)
        await itx.response.send_message(f"rule **{name}** removed", ephemeral=True)
        return
    if len(cfg.rules) >= 5 and name not in cfg.rules:
        await itx.response.send_message("up to 5 custom rules per server", ephemeral=True)
        return
    cfg.rules[name] = text.strip()[:200]
    cfg.rule_actions[name] = action if action in ACTIONS else "flag"
    store.save(cfg)
    await itx.response.send_message(f"rule **{name}** → {cfg.rule_actions[name]}: \"{cfg.rules[name]}\"", ephemeral=True)


@mod.command(name="trust", description="Toggle a role whose messages are never judged")
async def trust_cmd(itx: discord.Interaction, role: discord.Role) -> None:
    cfg = store.get(itx.guild_id)
    if role.id in cfg.trusted_roles:
        cfg.trusted_roles.remove(role.id)
        msg = f"{role.mention} is judged again"
    else:
        cfg.trusted_roles.append(role.id)
        msg = f"{role.mention} is trusted: never judged"
    store.save(cfg)
    await itx.response.send_message(msg, ephemeral=True)


@mod.command(name="topic", description="Tell jevmod what this channel is for (used by the offtopic check)")
async def topic_cmd(itx: discord.Interaction, topic: str) -> None:
    cfg = store.get(itx.guild_id)
    cfg.channel_topics[str(itx.channel_id)] = topic.strip()[:200]
    store.save(cfg)
    await itx.response.send_message(f"this channel is about: {topic}", ephemeral=True)


@mod.command(name="log", description="Use this channel for jevmod's decision log")
async def log_cmd(itx: discord.Interaction) -> None:
    cfg = store.get(itx.guild_id)
    cfg.log_channel = itx.channel_id
    store.save(cfg)
    await itx.response.send_message("decisions will be logged here", ephemeral=True)


@mod.command(name="recent", description="Last decisions with their probabilities")
async def recent_cmd(itx: discord.Interaction) -> None:
    rows = store.recent_decisions(itx.guild_id, 10)
    if not rows:
        await itx.response.send_message("no decisions yet", ephemeral=True)
        return
    lines = [f"`{cat} {p:.2f} {act}` {text[:80]}" for _, cat, p, act, text in rows]
    await itx.response.send_message("\n".join(lines), ephemeral=True)


tree.add_command(mod)

if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("set DISCORD_TOKEN (Discord Developer Portal → Bot → Reset Token)")
    bot.run(token, log_handler=None)
