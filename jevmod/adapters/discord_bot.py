"""Discord adapter on top of ModerationService.

Plug and play: invite it, it flags into a private #jevmod-log; tune with /mod.

DISCORD_TOKEN=... TYPESAFE_API_KEY=... python -m jevmod.adapters.discord_bot
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import timedelta

import discord
from discord import app_commands

from ..core import RULE_THRESHOLD, Batcher, Decision, ModerationService, Store
from ..judge import CATEGORIES, Message

log = logging.getLogger("jevmod.discord")

intents = discord.Intents.default()
intents.message_content = True  # the only privileged intent we need
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
service = ModerationService(store)


def tenant_of(guild_id: int) -> str:
    return f"discord:{guild_id}"


async def handle_batch(tenant: str, batch: list[discord.Message]) -> None:
    guild = batch[0].guild
    if guild is None:
        return
    meta = store.get_meta(tenant)
    trusted = set(meta.get("trusted_roles", []))
    topics = meta.get("channel_topics", {})
    msgs = [
        Message(
            id=str(m.id),
            text=m.content,
            author=str(m.author.id),  # kept only in your local log for erasure requests; never sent to Jev
            channel_topic=topics.get(str(m.channel.id), getattr(m.channel, "topic", "") or "general chat"),
            author_trusted=_trusted(m.author, trusted),
        )
        for m in batch
    ]
    decisions = await asyncio.to_thread(service.moderate, tenant, msgs)
    for m, d in zip(batch, decisions, strict=True):
        if d.reason == "quota":
            await _notify_quota_once(guild, tenant)
            return
        if d.action != "none":
            await act(guild, m, d)


def _trusted(author: discord.User | discord.Member, trusted_roles: set[int]) -> bool:
    if not isinstance(author, discord.Member):
        return False
    return author.guild_permissions.manage_messages or bool(trusted_roles & {r.id for r in author.roles})


batcher = Batcher(2.0, handle_batch)


@bot.event
async def on_ready() -> None:
    await tree.sync()
    log.info("discord ready as %s in %d guilds", bot.user, len(bot.guilds))


@bot.event
async def on_message(msg: discord.Message) -> None:
    if msg.author.bot or not msg.guild or not msg.content:
        return
    tenant = tenant_of(msg.guild.id)
    if not service.policy(tenant).active():
        return
    batcher.add(tenant, msg)


async def act(guild: discord.Guild, m: discord.Message, d: Decision) -> None:
    tenant = tenant_of(guild.id)
    policy = service.policy(tenant)
    note = ""
    try:
        if d.action in ("delete", "timeout"):
            await m.delete()
            note = "deleted"
        if d.action == "timeout" and isinstance(m.author, discord.Member):
            await m.author.timeout(
                timedelta(minutes=policy.timeout_minutes), reason=f"jevmod: {d.category} p={d.probability:.2f}"
            )
            note = f"deleted, timed out {policy.timeout_minutes} min"
    except discord.Forbidden:
        note = "missing permissions to act"
    if d.action in ("delete", "timeout") and "missing" not in note:
        with contextlib.suppress(Exception):  # DMs closed
            await m.author.send(
                f"Your message in **{guild.name}** #{m.channel} was removed by an automated moderation system "
                f"(reason: {d.category}, confidence {d.probability:.0%}). If you think this was a mistake, contact the "
                "server's moderators; they can review the decision and adjust the rules."
            )
    channel = await log_channel(guild, tenant)
    if channel:
        top = " · ".join(f"{c} {p:.2f}" for c, p in sorted(d.scores.items(), key=lambda kv: -kv[1])[:3])
        embed = discord.Embed(
            title=f"{d.category}  p={d.probability:.2f}  →  {d.action}" + (f" ({note})" if note else ""),
            description=m.content[:500],
            colour=0x2FBF83 if d.action == "flag" else 0xD9A441,
        )
        embed.add_field(name="author", value=m.author.mention, inline=True)
        embed.add_field(name="channel", value=getattr(m.channel, "mention", str(m.channel)), inline=True)
        embed.set_footer(text=f"{top}   ·   ❌ false positive (raises threshold)  ·  ✅ correct (lowers it a notch)")
        sent = await channel.send(embed=embed)
        await sent.add_reaction("❌")
        await sent.add_reaction("✅")


async def log_channel(guild: discord.Guild, tenant: str) -> discord.TextChannel | None:
    meta = store.get_meta(tenant)
    if meta.get("log_channel"):
        ch = guild.get_channel(int(meta["log_channel"]))
        if isinstance(ch, discord.TextChannel):
            return ch
    existing = discord.utils.get(guild.text_channels, name="jevmod-log")
    if existing:
        store.set_meta(tenant, log_channel=existing.id)
        return existing
    try:
        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False)
        }
        ch = await guild.create_text_channel("jevmod-log", overwrites=overwrites, reason="jevmod decisions log")
        store.set_meta(tenant, log_channel=ch.id)
        return ch
    except discord.Forbidden:
        return None


async def _notify_quota_once(guild: discord.Guild, tenant: str) -> None:
    if not store.note_quota_hit(tenant):
        return
    ch = await log_channel(guild, tenant)
    if ch:
        await ch.send(
            f"jevmod paused for this month: the {store.plan(tenant)} plan covers {store.quota_for(tenant):,} judged "
            "messages. Messages are not being judged until next month. Nothing is deleted while paused."
            + (" `/mod upgrade` lifts the limit." if store.plan(tenant) == "free" and _billing_enabled() else "")
        )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    """❌ = false positive (threshold up), ✅ = confirmed (threshold down a notch, floor 0.5)."""
    emoji = str(payload.emoji)
    if emoji not in ("❌", "✅") or (bot.user and payload.user_id == bot.user.id) or not payload.guild_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    tenant = tenant_of(guild.id)
    meta = store.get_meta(tenant)
    if str(payload.channel_id) != str(meta.get("log_channel")):
        return
    channel = guild.get_channel(payload.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    msg = await channel.fetch_message(payload.message_id)
    if not msg.embeds or not msg.embeds[0].title:
        return
    category = msg.embeds[0].title.split()[0]
    policy = service.policy(tenant)
    if category in policy.thresholds or category.startswith("rule:"):
        new = policy.nudge(category, 0.03 if emoji == "❌" else -0.02)
        service.save_policy(tenant, policy)
        await msg.reply(f"noted: threshold for **{category}** is now {new:.2f}", mention_author=False)


@bot.event
async def on_guild_remove(guild: discord.Guild) -> None:
    """Kicked or left: forget everything about that server."""
    store.delete_tenant(tenant_of(guild.id))
    log.info("left guild %s; data deleted", guild.id)


# ------------------------------------------------------------------ /mod
mod = app_commands.Group(
    name="mod", description="jevmod settings", default_permissions=discord.Permissions(manage_guild=True)
)


@mod.command(name="status", description="Settings and this month's usage")
async def status(itx: discord.Interaction) -> None:
    tenant = tenant_of(itx.guild_id or 0)
    p = service.policy(tenant)
    judged, requests, tokens = store.usage(tenant)
    lines = [f"**{c}**: {p.actions.get(c, 'off')} at p ≥ {p.thresholds.get(c, 0.9):.2f}" for c in CATEGORIES]
    lines += [f'**rule {n}**: {p.rule_actions.get(n, "flag")} · "{r}"' for n, r in p.rules.items()]
    plan = store.plan(tenant)
    q = store.quota_for(tenant)
    quota = f"{judged:,}/{q:,} judged this month ({plan})" if q else f"{judged:,} judged this month ({plan}, unlimited)"
    lines.append(f"\n{quota} · {requests} Jev requests · {tokens:,} tokens")
    await itx.response.send_message("\n".join(lines), ephemeral=True)


@mod.command(name="set", description="Action and threshold for a category")
@app_commands.describe(
    category="spam, scam, harassment, nsfw, offtopic", action="off, flag, delete, timeout", threshold="0.5 to 0.99"
)
async def set_cmd(itx: discord.Interaction, category: str, action: str, threshold: float | None = None) -> None:
    tenant = tenant_of(itx.guild_id or 0)
    p = service.policy(tenant)
    try:
        p.set_category(category, action, threshold)
    except ValueError as exc:
        await itx.response.send_message(str(exc), ephemeral=True)
        return
    service.save_policy(tenant, p)
    await itx.response.send_message(f"**{category}** → {action} at p ≥ {p.thresholds[category]:.2f}", ephemeral=True)


@mod.command(name="rule", description="Add or remove a rule in plain language")
@app_commands.describe(
    name="short name",
    text="the rule as you would tell a member, exceptions included; empty to remove",
    action="flag, delete, timeout",
    threshold="0.5 to 0.99 (default 0.80)",
)
async def rule_cmd(
    itx: discord.Interaction, name: str, text: str | None = None, action: str = "flag", threshold: float | None = None
) -> None:
    tenant = tenant_of(itx.guild_id or 0)
    p = service.policy(tenant)
    try:
        p.set_rule(name, text, action, threshold)
    except ValueError as exc:
        await itx.response.send_message(str(exc), ephemeral=True)
        return
    service.save_policy(tenant, p)
    key = name.strip().lower().replace(" ", "_")[:30]
    if key in p.rules:
        th = p.rule_thresholds.get(key, RULE_THRESHOLD)
        await itx.response.send_message(
            f'rule **{key}** → {p.rule_actions[key]} at p ≥ {th:.2f}: "{p.rules[key]}"', ephemeral=True
        )
    else:
        await itx.response.send_message(f"rule **{key}** removed", ephemeral=True)


@mod.command(name="trust", description="Toggle a role whose messages are never judged")
async def trust_cmd(itx: discord.Interaction, role: discord.Role) -> None:
    tenant = tenant_of(itx.guild_id or 0)
    roles = list(store.get_meta(tenant).get("trusted_roles", []))
    if role.id in roles:
        roles.remove(role.id)
        msg = f"{role.mention} is judged again"
    else:
        roles.append(role.id)
        msg = f"{role.mention} is trusted: never judged"
    store.set_meta(tenant, trusted_roles=roles)
    await itx.response.send_message(msg, ephemeral=True)


@mod.command(name="topic", description="What this channel is for (used by the offtopic check)")
async def topic_cmd(itx: discord.Interaction, topic: str) -> None:
    tenant = tenant_of(itx.guild_id or 0)
    topics = dict(store.get_meta(tenant).get("channel_topics", {}))
    topics[str(itx.channel_id)] = topic.strip()[:200]
    store.set_meta(tenant, channel_topics=topics)
    await itx.response.send_message(f"this channel is about: {topic}", ephemeral=True)


@mod.command(name="log", description="Log decisions in this channel")
async def log_cmd(itx: discord.Interaction) -> None:
    store.set_meta(tenant_of(itx.guild_id or 0), log_channel=itx.channel_id)
    await itx.response.send_message("decisions will be logged here", ephemeral=True)


@mod.command(name="recent", description="Last decisions with probabilities")
async def recent_cmd(itx: discord.Interaction) -> None:
    rows = store.recent_decisions(tenant_of(itx.guild_id or 0), 10)
    if not rows:
        await itx.response.send_message("no decisions yet", ephemeral=True)
        return
    await itx.response.send_message(
        "\n".join(
            f"`{r['category']} {r['p']:.2f} {r['action']}` {r['text'][:80] or 'message ' + str(r['message_id'])}"
            for r in rows
        ),
        ephemeral=True,
    )


@mod.command(name="upgrade", description="Payment link for the Pro plan of this server, or the billing portal")
async def upgrade_cmd(itx: discord.Interaction) -> None:
    tenant = tenant_of(itx.guild_id or 0)
    if not _billing_enabled():
        await itx.response.send_message(
            "This copy of jevmod is self-hosted: there is nothing to pay. Raise JEVMOD_MONTHLY_QUOTA on the server.",
            ephemeral=True,
        )
        return
    from ..api.billing import checkout_url

    plan = store.plan(tenant)
    what = "manage or cancel the subscription" if plan != "free" else "upgrade this server to Pro"
    await itx.response.send_message(
        f"Link to {what} (valid for this server only, opens Stripe): {checkout_url(tenant)}", ephemeral=True
    )


def _billing_enabled() -> bool:
    return bool(os.environ.get("STRIPE_PRICE_ID") and os.environ.get("JEVMOD_PUBLIC_URL"))


@mod.command(name="forget", description="Delete everything jevmod stored about this server (GDPR)")
async def forget_cmd(itx: discord.Interaction) -> None:
    store.delete_tenant(tenant_of(itx.guild_id or 0))
    await itx.response.send_message(
        "all settings, usage and decision logs for this server were deleted", ephemeral=True
    )


@mod.command(name="forget_user", description="Delete this member's entries from the decision log (erasure request)")
async def forget_user_cmd(itx: discord.Interaction, member: discord.Member) -> None:
    n = store.delete_user(tenant_of(itx.guild_id or 0), str(member.id))
    await itx.response.send_message(f"deleted {n} log entries for {member.mention}", ephemeral=True)


tree.add_command(mod)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("set DISCORD_TOKEN (Developer Portal → Bot → Reset Token)")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
