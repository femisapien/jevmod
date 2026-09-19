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

from ..core import RULE_THRESHOLD, Batcher, Decision, ModerationService, Policy, Store
from ..core.policy import DEFAULT_ACTIONS, DEFAULT_THRESHOLDS
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
    staff_exempt = bool(store.get_meta(tenant).get("staff_exempt", True))
    msgs = [
        Message(
            id=str(m.id),
            text=m.content,
            author=str(m.author.id),  # kept only in your local log for erasure requests; never sent to Jev
            channel_topic=topics.get(str(m.channel.id), getattr(m.channel, "topic", "") or "general chat"),
            author_trusted=_trusted(m.author, trusted, staff_exempt),
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


def _trusted(author: discord.User | discord.Member, trusted_roles: set[int], staff_exempt: bool = True) -> bool:
    """Roles the owner marked are never judged. Staff are exempt by default, which `/mod staff` can turn off for
    a server that wants its moderators held to the same line."""
    if not isinstance(author, discord.Member):
        return False
    if trusted_roles & {r.id for r in author.roles}:
        return True
    return staff_exempt and author.guild_permissions.manage_messages


# What a category is called when a person reads it. The keys stay as they are for the API and the store.
LABEL = {c: CATEGORIES[c].get("label", c) for c in CATEGORIES}


def label(category: str | None) -> str:
    """`minors` reads as 'messages from children' and means the opposite, so nothing user-facing uses the key."""
    if not category:
        return "a rule"
    if category.startswith("rule:"):
        return f'your rule "{category[5:]}"'
    return LABEL.get(category, category)


def category_of(title: str) -> str:
    """The key behind a flag's title, which reads `Deleted — scam / phishing`.

    The buttons need the key and the reader needs the label, so the title carries the label and this maps it
    back. It used to take the first word of the title, which stopped working the moment the title got prettier.
    """
    tail = title.split(" — ", 1)[-1].strip()
    for key, text in LABEL.items():
        if text == tail:
            return key
    if tail.startswith('your rule "') and tail.endswith('"'):
        return "rule:" + tail[len('your rule "') : -1]
    return tail if tail in LABEL else ""


def how_sure(p: float) -> str:
    """Words, not a percentage. Nobody outside this codebase knows what 87% confidence is 87% of."""
    if p >= 0.95:
        return "very sure"
    if p >= 0.85:
        return "sure"
    if p >= 0.70:
        return "fairly sure"
    return "not very sure"


batcher = Batcher(2.0, handle_batch)


@bot.event
async def on_ready() -> None:
    bot.add_view(FeedbackView())  # so the buttons on flags posted before this restart still answer
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


@bot.event
async def on_message_edit(_before: discord.Message, after: discord.Message) -> None:
    """Judge edits too: otherwise a member posts a harmless line and edits it into whatever they wanted."""
    if after.content != _before.content:
        await on_message(after)


class FeedbackView(discord.ui.View):
    """Two buttons under every flag. The view is persistent: its custom ids are fixed and the category is read
    back from the embed title when clicked, so the buttons keep working after the bot restarts."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Be less strict about this", style=discord.ButtonStyle.secondary, custom_id="jevmod:fp")
    async def wrong(self, itx: discord.Interaction, _button: discord.ui.Button) -> None:
        await _apply_feedback(itx, 0.03)

    @discord.ui.button(label="Be more strict about this", style=discord.ButtonStyle.secondary, custom_id="jevmod:ok")
    async def right(self, itx: discord.Interaction, _button: discord.ui.Button) -> None:
        await _apply_feedback(itx, -0.02)


async def _apply_feedback(itx: discord.Interaction, delta: float) -> None:
    """Move that category's line and say where it landed. Anyone who can see the log channel may do this."""
    if not itx.guild_id or not itx.message or not itx.message.embeds:
        return
    category = category_of(itx.message.embeds[0].title or "")
    tenant = tenant_of(itx.guild_id)
    policy = service.policy(tenant)
    if not category or (category not in policy.thresholds and not category.startswith("rule:")):
        await itx.response.send_message(
            "This flag is from an older version of jevmod, so these buttons cannot tell which setting to "
            "change. The next one will work.",
            ephemeral=True,
        )
        return
    before = policy.thresholds.get(category, RULE_THRESHOLD)
    new = policy.nudge(category, delta)
    if new == before:
        await itx.response.send_message(
            f"{label(category)} is experimental, so its setting does not move.", ephemeral=True
        )
        return
    service.save_policy(tenant, policy)
    softer = delta > 0
    await itx.response.send_message(
        f"Done. From now on jevmod acts on **{label(category)}** "
        + ("only when it is more sure, so it will act less often." if softer else "sooner, so it will act more often.")
        + "\n\nThis changed the setting for the whole server, not just this message. `/mod status` shows where "
        "everything sits and `/mod reset` puts it all back.",
        ephemeral=True,
    )
    # The owner cannot see an ephemeral reply, so leave the trace where they will find it.
    with contextlib.suppress(Exception):
        await itx.channel.send(  # type: ignore[union-attr]
            f"{itx.user.mention} made jevmod {'less' if softer else 'more'} strict about "
            f"**{label(category)}** for the whole server."
        )


async def act(guild: discord.Guild, m: discord.Message, d: Decision) -> None:
    tenant = tenant_of(guild.id)
    policy = service.policy(tenant)
    note = ""
    # `timeout` times the author out and leaves the message; only `delete` removes it. They used to be the same
    # branch, so a category set to timeout silently deleted as well, which the site does not promise.
    try:
        if d.action == "delete":
            await m.delete()
            note = "deleted"
        elif d.action == "timeout" and isinstance(m.author, discord.Member):
            await m.author.timeout(
                timedelta(minutes=policy.timeout_minutes),
                reason=f"jevmod: {label(d.category)}, {how_sure(d.probability)}",
            )
            note = f"timed out {policy.timeout_minutes} min"
    except discord.Forbidden:
        note = "Drag the jevmod role above your members in Server Settings, Roles, and it will work."
    if note and "missing" not in note:
        what = "was deleted" if d.action == "delete" else f"got you muted for {policy.timeout_minutes} minutes"
        quoted = m.content[:400].replace("\n", " ")
        with contextlib.suppress(Exception):  # DMs closed
            # Their own words back, not a number. They cannot argue with a percentage and neither can the
            # moderator they are about to message.
            await m.author.send(
                f"Your message in **{guild.name}** #{m.channel} {what} automatically, because it looked like "
                f"{label(d.category)}.\n\n> {quoted}\n\n"
                "No person reviewed this before it happened. If it is wrong, say so in the server and a "
                "moderator can pass it to whoever runs it."
            )
    channel = await log_channel(guild, tenant)
    if channel:
        did = {"flag": "Flagged", "delete": "Deleted", "timeout": "Muted the member"}.get(d.action, d.action)
        problem = "missing" in note
        embed = discord.Embed(
            title=(f"Could not act on {label(d.category)}" if problem else f"{did} — {label(d.category)}"),
            description=m.content[:1000],
            colour=0xD9A441 if problem else (0x2FBF83 if d.action == "flag" else 0xDC2626),
        )
        embed.add_field(name="who", value=m.author.mention, inline=True)
        embed.add_field(name="where", value=getattr(m.channel, "mention", str(m.channel)), inline=True)
        # A moderator needs the conversation, not a screenshot of one line. A deleted message has no link left.
        if d.action == "delete":
            embed.add_field(name="the message", value="Deleted. Discord cannot restore it.", inline=False)
        else:
            embed.add_field(name="go to it", value=f"[open the message]({m.jump_url})", inline=False)
        if problem:
            embed.add_field(name="what to do", value=note, inline=False)
        embed.set_footer(text=f"jevmod was {how_sure(d.probability)} about this one")
        await channel.send(embed=embed, view=FeedbackView())


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
        # Channel overwrites beat guild-level permissions, so the bot needs an explicit one or it cannot read,
        # post or react in the channel it just created, which breaks the log and the feedback reactions.
        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True,
            ),
        }
        # Denying @everyone leaves the channel visible only to Administrators, so a plain Moderator role could
        # not read the flags or use the reactions. Every role that can already moderate messages gets access.
        for role in guild.roles:
            if role.permissions.manage_messages or role.permissions.manage_guild:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                )
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
    """Reacting by hand still works, for flags posted before the buttons existed and for moderators who
    prefer it. The bot no longer adds these reactions itself."""
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
        await msg.reply(f"noted: the line for **{category}** is now {new:.0%}", mention_author=False)


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    """Create the log channel and explain the two things that surprise every new owner: staff are never judged,
    so testing it yourself shows nothing, and the bot only flags until someone turns on more."""
    tenant = tenant_of(guild.id)
    channel = await log_channel(guild, tenant)
    if not channel:
        log.info("joined guild %s but could not create a log channel", guild.id)
        return
    policy = service.policy(tenant)
    kinds = "\n".join(f"- {label(c)}" for c in policy.enabled_categories())
    await channel.send(
        "**jevmod is watching this server.** It reads each message and decides how likely it is to be one "
        f"of these:\n{kinds}\n\n"
        "**Right now it deletes nothing.** Anything it catches lands here, and you decide whether it was "
        "right. Turn on deleting later with `/mod set`, once you have seen a week of it.\n\n"
        "**Trying it on yourself will look broken.** jevmod ignores your moderators, and you are one, so "
        "your own messages are never checked. Type `/mod test` and any sentence to see what it would say.\n\n"
        "`/mod status` shows how it is set up. Every catch here carries two buttons to make jevmod stricter "
        "or gentler about that kind of thing."
    )


@bot.event
async def on_guild_remove(guild: discord.Guild) -> None:
    """Kicked or left: forget everything about that server."""
    store.delete_tenant(tenant_of(guild.id))
    log.info("left guild %s; data deleted", guild.id)


# ------------------------------------------------------------------ /mod
mod = app_commands.Group(
    name="mod",
    description="What jevmod caught, and how it is set up",
    # Manage Messages, not Manage Server: the log channel is opened to moderators, so the commands that explain
    # what is in it have to be too. The ones that change settings ask for Manage Server themselves, below.
    default_permissions=discord.Permissions(manage_messages=True),
)


async def owner_only(itx: discord.Interaction) -> bool:
    """True when this member may change settings. Moderators can look; changing is for whoever runs the server."""
    perms = getattr(itx.user, "guild_permissions", None)
    if perms and perms.manage_guild:
        return True
    await itx.response.send_message(
        "Only someone who can manage the server can change this. You can see how it is set up with "
        "`/mod status`, and try any text with `/mod test`.",
        ephemeral=True,
    )
    return False


@mod.command(name="status", description="Settings and this month's usage")
async def status(itx: discord.Interaction) -> None:
    tenant = tenant_of(itx.guild_id or 0)
    p = service.policy(tenant)
    judged, requests, tokens = store.usage(tenant)
    lines = []
    for c in CATEGORIES:
        action = p.actions.get(c, "off")
        if action == "off":
            lines.append(f"**{label(c)}**: not checked")
        else:
            does = {
                "flag": "tells you",
                "delete": "deletes the message",
                "timeout": f"mutes the member for {p.timeout_minutes} minutes",
            }.get(action, action)
            lines.append(f"**{label(c)}**: {does}, once it is {how_sure(p.thresholds.get(c, 0.9))}")
    lines += [f'**rule {n}**: {p.rule_actions.get(n, "flag")} · "{r}"' for n, r in p.rules.items()]
    plan = store.plan(tenant)
    q = store.quota_for(tenant)
    quota = f"{judged:,}/{q:,} judged this month ({plan})" if q else f"{judged:,} judged this month ({plan}, unlimited)"
    lines.append(f"\n{quota}")
    await itx.response.send_message("\n".join(lines), ephemeral=True)


@mod.command(name="test", description="What would jevmod say about this message? Judges it without acting.")
@app_commands.describe(message="The text to rate. Nothing is deleted and nobody is timed out.")
async def test_cmd(itx: discord.Interaction, message: str) -> None:
    """Judge a message ignoring who sent it. This exists because the first thing an owner does is test the bot
    on themselves, and staff are never judged, so the honest answer is a command that says so out loud."""
    tenant = tenant_of(itx.guild_id or 0)
    await itx.response.defer(ephemeral=True, thinking=True)
    # `channel_topics` is the key `/mod topic` writes. This read used `topics`, so /mod test never saw the
    # topic an owner had set, and the one verification path the bot recommends reported off-topic as dead.
    topics = store.get_meta(tenant).get("channel_topics", {})
    msg = Message(
        id=f"test-{itx.id}",
        text=message,
        author=str(itx.user.id),
        channel_topic=topics.get(str(itx.channel_id), getattr(itx.channel, "topic", "") or "general chat"),
        author_trusted=False,  # the point of the command: judge it as if a member had said it
    )
    decision = (await asyncio.to_thread(service.moderate, tenant, [msg]))[0]
    if not decision.judged:
        await itx.followup.send(f"not sent to the model: {decision.reason}", ephemeral=True)
        return
    policy = service.policy(tenant)
    await itx.followup.send(_explain(decision, policy), ephemeral=True)


WHAT_HAPPENS = {
    "flag": "It would be posted to the log channel for your moderators. The message stays up and the member is "
    "not told.",
    "delete": "It would be deleted, and the member would get a direct message saying an automated system "
    "removed it and how to appeal.",
    "timeout": "The member would be timed out, and would get a direct message saying so and how to appeal. The "
    "message stays up.",
}


def _bar(p: float, width: int = 18) -> str:
    filled = max(0, min(width, round(p * width)))
    return "#" * filled + "." * (width - filled)


def _explain(decision: Decision, policy: Policy) -> str:
    """Percentages and a bar per category, then what would actually happen to the message."""
    scores = sorted(decision.scores.items(), key=lambda kv: -kv[1])
    shown = [(c, p) for c, p in scores if p >= 0.01][:5] or scores[:3]
    rows = []
    for category, p in shown:
        line = policy.thresholds.get(category, 0.9)
        enough = p >= line and policy.actions.get(category, "off") != "off"
        # the bar carries the reading and the marker carries your setting, so the two are comparable at a glance
        rows.append(f"{label(category)[:22]:<24}{_bar(p)}  {'acts' if enough else 'not enough'}")
    table = "```\n" + "\n".join(rows) + "\n```"

    if decision.action == "none":
        head = "**jevmod would leave this alone.**"
        tail = f"The closest it came was {label(shown[0][0])}, and even there it was only {how_sure(shown[0][1])}."
    else:
        # an acting decision always carries its category; name it so the type checker knows too
        category = decision.category or "a rule"
        head = f"**jevmod would treat this as {label(category)},** and it is {how_sure(decision.probability)}."
        tail = WHAT_HAPPENS.get(decision.action, "")
    footer = (
        "Nothing happened to anyone: this only reads the text you typed. `/mod set` changes how strict any of these is."
    )
    return f"{head}\n{table}\n{tail}\n\n{footer}"


def _as_probability(value: float | None) -> float | None:
    """The bot talks in percentages, so 75 and 0.75 both mean the same line. Anything above 1 is read as a
    percentage, which is also what someone typing 80 into `/mod set` means."""
    if value is None:
        return None
    return value / 100 if value > 1 else value


@mod.command(name="reset", description="Put every setting back the way it started")
async def reset_cmd(itx: discord.Interaction) -> None:
    """The buttons move settings a little at a time, so after a busy week nobody remembers where they were."""
    if not await owner_only(itx):
        return
    tenant = tenant_of(itx.guild_id or 0)
    p = service.policy(tenant)
    kept = dict(p.rules)
    p.thresholds = dict(DEFAULT_THRESHOLDS)
    p.actions = dict(DEFAULT_ACTIONS)
    service.save_policy(tenant, p)
    rules = f" Your {len(kept)} rule(s) were left alone." if kept else ""
    await itx.response.send_message(
        "Every category is back to how jevmod ships: it tells you and deletes nothing." + rules, ephemeral=True
    )


@mod.command(name="set", description="Choose what jevmod does about one kind of message")
@app_commands.describe(
    category="Which kind of message.",
    action="What to do about it.",
    threshold="How sure jevmod must be, 50 to 99. Higher acts less often. Leave empty to keep what you have.",
)
@app_commands.choices(
    # A dropdown, not free text. The help here used to name five of the nine categories, so the other four
    # could only be reached by someone who already knew their exact spelling.
    category=[app_commands.Choice(name=LABEL[c][:100], value=c) for c in CATEGORIES],
    action=[
        app_commands.Choice(name="do not check this at all", value="off"),
        app_commands.Choice(name="tell me, delete nothing", value="flag"),
        app_commands.Choice(name="delete the message", value="delete"),
        app_commands.Choice(name="mute the member for a while", value="timeout"),
    ],
)
async def set_cmd(itx: discord.Interaction, category: str, action: str, threshold: float | None = None) -> None:
    if not await owner_only(itx):
        return
    tenant = tenant_of(itx.guild_id or 0)
    p = service.policy(tenant)
    try:
        p.set_category(category, action, _as_probability(threshold))
    except ValueError as exc:
        await itx.response.send_message(str(exc), ephemeral=True)
        return
    service.save_policy(tenant, p)
    does = {
        "off": "is not checked any more",
        "flag": "will be reported here",
        "delete": "will have the message deleted",
        "timeout": f"will mute the member for {p.timeout_minutes} minutes",
    }.get(action, action)
    # Off-topic is judged against the channel's topic. Without one the adapter substitutes "general chat",
    # which in testing flagged nothing at all, so turning it on without a topic is a silent no-op.
    warn = ""
    if category == "offtopic" and action != "off":
        topics = store.get_meta(tenant).get("channel_topics", {})
        if not topics:
            warn = (
                "\n\n**This will not do anything yet.** Off-topic is judged against what a channel is for, and "
                "no channel here has been given one. Run `/mod topic` in each channel you want checked, with a "
                "sentence saying what belongs there."
            )
    await itx.response.send_message(
        f"**{label(category)}** {does}, once jevmod is {how_sure(p.thresholds[category])}.{warn}", ephemeral=True
    )


RULE_ADVICE = (
    "**Rules are read the way you wrote them, so write them the way you would tell a member.** Name the "
    'things you mean: not "no self promo" but "do not advertise your own youtube channel, twitch stream or '
    'discord server". In testing the short version missed two thirds of the real cases and the long one '
    "caught all of them."
)


@mod.command(name="rule", description="Write a rule in your own words and jevmod will enforce it")
@app_commands.describe(
    name="a short name for the rule, so you can change it later",
    text="the rule, as you would say it to a member. Leave empty to delete the rule.",
    action="what to do when it is broken: flag, delete or timeout",
    threshold="How sure jevmod must be, 50 to 99. Leave empty for 80.",
)
async def rule_cmd(
    itx: discord.Interaction, name: str, text: str | None = None, action: str = "flag", threshold: float | None = None
) -> None:
    if not await owner_only(itx):
        return
    tenant = tenant_of(itx.guild_id or 0)
    p = service.policy(tenant)
    try:
        p.set_rule(name, text, action, _as_probability(threshold))
    except ValueError as exc:
        await itx.response.send_message(str(exc), ephemeral=True)
        return
    service.save_policy(tenant, p)
    key = name.strip().lower().replace(" ", "_")[:30]
    if key in p.rules:
        th = p.rule_thresholds.get(key, RULE_THRESHOLD)
        head = (
            f'Rule **{key}** is on: "{p.rules[key]}"\nWhen it is broken jevmod will '
            f"{p.rule_actions[key]}, once it is {how_sure(th)}."
        )
        await itx.response.send_message(head + _rule_warnings(p.rules[key]), ephemeral=True)
    else:
        await itx.response.send_message(f"Rule **{key}** deleted.", ephemeral=True)


def _rule_warnings(text: str) -> str:
    """Three ways a rule fails silently, all three measured against real Jev before being written here."""
    out = []
    if len(text.split()) < 4:
        out.append(
            "\n\n**That rule is probably too short to work.** A one word rule never fired once in testing. "
            + RULE_ADVICE
        )
    lowered = text.lower()
    if any(w in lowered for w in (" is fine", " is ok", " is okay", "allowed", "you can ", "feel free")):
        out.append(
            "\n\n**A rule can only forbid something, not permit it.** Written this way it will never fire, and "
            "it does not switch off any category either. To allow something, turn that category off with "
            "`/mod set`."
        )
    if any(w in lowered for w in ("regular", "veteran", "new member", "newcomer", "trusted", "been here")):
        out.append(
            "\n\n**An exception about who the member is cannot work.** jevmod is never told who wrote a "
            'message, so it can only go by what the message says, and anyone can type "I have been here for '
            'years". Use `/mod trust` to exempt a role instead.'
        )
    return "".join(out)


@mod.command(name="trust", description="Toggle a role whose messages are never judged")
async def trust_cmd(itx: discord.Interaction, role: discord.Role) -> None:
    if not await owner_only(itx):
        return
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


@mod.command(name="staff", description="Whether moderators are judged like everyone else")
@app_commands.describe(judged="True judges anyone who can manage messages. False exempts them, the default.")
async def staff_cmd(itx: discord.Interaction, judged: bool) -> None:
    if not await owner_only(itx):
        return
    tenant = tenant_of(itx.guild_id or 0)
    store.set_meta(tenant, staff_exempt=not judged)
    await itx.response.send_message(
        "Moderators are judged like everyone else now. Your own messages included."
        if judged
        else "Moderators are exempt again. Anyone who can manage messages is never judged.",
        ephemeral=True,
    )


@mod.command(name="topic", description="Say what this channel is for, so off-topic checking can work here")
@app_commands.describe(topic="A full sentence saying what belongs here and what does not. One word is not enough.")
async def topic_cmd(itx: discord.Interaction, topic: str) -> None:
    if not await owner_only(itx):
        return
    tenant = tenant_of(itx.guild_id or 0)
    topics = dict(store.get_meta(tenant).get("channel_topics", {}))
    topics[str(itx.channel_id)] = topic.strip()[:200]
    store.set_meta(tenant, channel_topics=topics)
    # Measured: a one word topic loses real off-topic messages, and the default "general chat" catches nothing
    # at all. An owner who sets a vague topic gets silence and no way to know why.
    warn = (
        "\n\nThat topic is very short. Off-topic checking compares each message to this sentence, so a short "
        "topic catches almost nothing. Say what belongs here and what does not."
        if len(topic.split()) < 5
        else ""
    )
    todo = (
        "\n\nOff-topic checking is still switched off. Turn it on with `/mod set offtopic flag`."
        if service.policy(tenant).actions.get("offtopic", "off") == "off"
        else ""
    )
    await itx.response.send_message(f"This channel is about: {topic}{warn}{todo}", ephemeral=True)


@mod.command(name="log", description="Log decisions in this channel")
async def log_cmd(itx: discord.Interaction) -> None:
    if not await owner_only(itx):
        return
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
            f"`{r['category']} {float(r['p']):.0%} {r['action']}` {r['text'][:80] or 'message ' + str(r['message_id'])}"
            for r in rows
        ),
        ephemeral=True,
    )


@mod.command(name="upgrade", description="Payment link for the Pro plan of this server, or the billing portal")
async def upgrade_cmd(itx: discord.Interaction) -> None:
    if not await owner_only(itx):
        return
    tenant = tenant_of(itx.guild_id or 0)
    if not _billing_enabled():
        await itx.response.send_message(
            "This copy of jevmod is self-hosted: there is nothing to pay. Raise JEVMOD_MONTHLY_QUOTA on the server.",
            ephemeral=True,
        )
        return
    try:
        from ..api.billing import checkout_url
    except ImportError:
        # Billing is not part of the open package. A copy without it is by definition self-hosted.
        await itx.response.send_message(
            "This copy of jevmod has no billing built in, so there is nothing to pay. Raise "
            "JEVMOD_MONTHLY_QUOTA on the server to lift the limit.",
            ephemeral=True,
        )
        return

    plan = store.plan(tenant)
    what = "manage or cancel the subscription" if plan != "free" else "upgrade this server to Pro"
    await itx.response.send_message(
        f"Link to {what} (valid for this server only, opens Stripe): {checkout_url(tenant)}", ephemeral=True
    )


def _billing_enabled() -> bool:
    return bool(os.environ.get("STRIPE_PRICE_ID") and os.environ.get("JEVMOD_PUBLIC_URL"))


@mod.command(name="forget", description="Delete everything jevmod stored about this server (GDPR)")
async def forget_cmd(itx: discord.Interaction) -> None:
    if not await owner_only(itx):
        return
    tenant = tenant_of(itx.guild_id or 0)
    # Deleting the local rows does not cancel anything at Stripe, so a paying owner would keep being charged
    # with no record left here to explain it. Say so before deleting, and leave the portal link in reach.
    paying = store.plan(tenant) != "free"
    store.delete_tenant(tenant)
    note = "all settings, usage and decision logs for this server were deleted"
    if paying:
        note += (
            ". This did not cancel your Pro subscription: Stripe will keep charging the card until you cancel "
            "it in Stripe's billing portal."
        )
    await itx.response.send_message(note, ephemeral=True)


@mod.command(name="forget_user", description="Delete this member's entries from the decision log (erasure request)")
async def forget_user_cmd(itx: discord.Interaction, member: discord.Member) -> None:
    if not await owner_only(itx):
        return
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
