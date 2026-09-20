"""Twitch adapter. Reads chat over Twitch's IRC-over-WebSocket gateway, judges it through the same shared
`ModerationService.moderate()` every other adapter calls, and acts through Twitch's own Helix moderation
API. Chat commands (`!jevmod status`, `!jevmod set ...`, `!jevmod rule ...`) give a channel owner Discord's
core settings surface, not its full command list -- see "what's still missing" below.

    TWITCH_CLIENT_ID=... TWITCH_CLIENT_SECRET=... TWITCH_REFRESH_TOKEN=... TWITCH_BOT_LOGIN=... \\
    TWITCH_CHANNELS=chan1,chan2 TYPESAFE_API_KEY=... python -m jevmod.adapters.twitch_bot

Design decisions, written down because they are the actual content of issue #29, not just its plumbing:

Transport. Twitch offers two ways to read chat: legacy IRC-over-WebSocket, and EventSub's
`channel.chat.message` subscription. This adapter uses IRC-over-WebSocket: EventSub chat needs a
subscription created and kept alive per channel through a second, separate API surface (and, for the
`user.read.chat`-scoped variant, a user token per broadcaster rather than one moderator token covering every
channel it moderates), for no behavioural difference to what arrives -- one chat line at a time, in order.
IRC is one connection, one auth handshake, one place a "the socket dropped" reconnect lives.

Actions. Twitch chat moderation is delete-one-message and time someone out; a permanent ban is a third,
separate action jevmod refuses to reach for, matching the "jevmod cannot ban anybody" promise the terms make
and every other adapter already keeps (see test_offline.py::test_no_adapter_can_ban_anybody, which greps
every adapter file for the literal call shapes that would break that promise). `delete` calls Helix's
single-message delete; `timeout` calls the *same* Helix endpoint Twitch uses for both timeouts and bans
(`POST /moderation/bans`) but -- this is the whole guardrail -- a `duration` field is always attached, every
call, with no code path that omits it. Twitch's own contract is that a `duration`-less call is what makes
that endpoint a permanent ban; `timeout_seconds()` below is the only place a duration is computed, and it
never returns 0 or None. `off`/`flag` produce no Helix call: `flag` has no destination on this platform (see
below) and is a log line only.

Chat velocity and the batch window. Discord's 2 second batching window assumes a few messages between
flushes; a busy Twitch channel can produce dozens in that time, and `ModerationService` bills one Jev
request per batch regardless of how many messages are in it, so a wider window is cheaper, not just
slower. This adapter uses 1.0s instead: half of Discord's window, because chat here reads faster and the
delay before a bad message is acted on is more visible to more people watching it happen live. It is still
bounded by the same `JEVMOD_MAX_BATCH` (default 100) `ModerationService` already enforces for every adapter,
so a viral moment that outruns even a 1 second window degrades the same way it already does elsewhere: the
messages within the cap get judged, the rest are marked `over_batch` and left alone rather than the batch
silently growing without limit.

Auth and rate limits, what the operator has to do. Twitch requires (a) an app registered on the developer
console for `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET`, and (b) a *user* access token (not an app token --
moderation endpoints act as a specific user) for a bot account with the scopes `chat:read`,
`moderator:manage:banned_users` and `moderator:manage:chat_messages`, obtained once through Twitch's OAuth
authorization-code flow and then kept alive here via `TWITCH_REFRESH_TOKEN` (user tokens expire in a few
hours; `HelixClient.refresh` trades the refresh token for a new access token before every reconnect and
whenever a call comes back 401). That bot account must additionally be added as a moderator of every channel
`TWITCH_CHANNELS` names -- Twitch's moderation endpoints 403 for an account that is not one, the same
precondition Reddit's mod-account and Discord's bot-permissions already require. On the chat side, an
unverified bot is limited to 20 IRC messages per 30 seconds per channel by Twitch itself; this adapter's own
chat replies (command output) are the only thing it ever sends into a channel, so that ceiling is not one
normal moderation traffic reaches.

What's still missing, honestly, not silently. `flag` has nowhere to go: Discord and Telegram post a flagged
message into a private log channel/chat the operator configures; Twitch has no equivalent an ordinary bot
account can write to without extra approval (whispers are gated behind Twitch's own extended-access review
as of 2023), so `flag` here is a structured `log.info` line on the process's own logs and nothing else --
visible to whoever runs the bot, invisible to the channel. This adapter has not been run against a live
Twitch channel: doing that needs a registered Twitch app and a real broadcaster's OAuth consent, which is an
account-holder action this change cannot perform on its own. Everything with a right answer independent of
that -- IRC line parsing, the timeout-never-omits-duration guardrail, the command dispatch, the batch/action
wiring -- is unit-tested in tests/test_twitch_local_commands.py; the reconnect loop and the live Helix calls
are not, the same honest gap test_telegram_local_commands.py already documents for python-telegram-bot's own
`Update`/`Context` plumbing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..core import Batcher, ModerationService, Policy, Store
from ..core.policy import ACTIONS
from ..judge import CATEGORIES, Message

log = logging.getLogger("jevmod.twitch")
store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
service = ModerationService(store)

IRC_WS_URL = "wss://irc-ws.chat.twitch.tv:443"
HELIX_BASE = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
BATCH_WINDOW_S = 1.0  # half of Discord's 2s: Twitch chat moves faster (see module docstring)
CMD_PREFIX = "!jevmod"
# Twitch's own documented ceiling for a single timeout (14 days). `timeout_seconds` clamps to this so a
# generous `/mod_set` threshold can never accidentally ask Twitch for something it would refuse or, worse,
# silently reinterpret.
MAX_TIMEOUT_S = 1_209_600


def tenant_of(channel: str) -> str:
    return f"twitch:{channel.lstrip('#').lower()}"


# ---------------------------------------------------------------- IRC line parsing (pure, no socket)
#
# Twitch's IRC-over-WebSocket gateway sends ordinary IRCv3 lines: an optional `@tag=val;...` prefix, an
# optional `:nick!user@host` prefix, a command, and space-separated params with an optional `:trailing`
# capturing everything after the last one (including further spaces). Parsing this is a pure string
# operation -- no socket needed to test it against a captured line.


@dataclass
class IrcMessage:
    tags: dict[str, str] = field(default_factory=dict)
    prefix: str = ""
    command: str = ""
    params: list[str] = field(default_factory=list)
    trailing: str | None = None


def _unescape_tag(value: str) -> str:
    """IRCv3 tag escaping (the four sequences the spec defines): `\\:` -> `;`, `\\s` -> space, `\\\\` -> `\\`,
    `\\r`/`\\n` -> CR/LF. Twitch's own tag values (ids, numbers, display names) essentially never need this,
    but a display name someone set with a semicolon in it would silently corrupt tag parsing without it."""
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({":": ";", "s": " ", "\\": "\\", "r": "\r", "n": "\n"}.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_tags(raw: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for pair in raw.split(";"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        tags[key] = _unescape_tag(value)
    return tags


def parse_irc_line(line: str) -> IrcMessage:
    msg = IrcMessage()
    line = line.rstrip("\r\n")
    if line.startswith("@"):
        raw_tags, _, line = line[1:].partition(" ")
        msg.tags = parse_tags(raw_tags)
    if line.startswith(":"):
        msg.prefix, _, line = line[1:].partition(" ")
    if " :" in line:
        head, _, trailing = line.partition(" :")
        msg.trailing = trailing
    else:
        head = line
    parts = head.split()
    if parts:
        msg.command = parts[0]
        msg.params = parts[1:]
    return msg


def is_privmsg(msg: IrcMessage) -> bool:
    return msg.command == "PRIVMSG" and bool(msg.params) and msg.trailing is not None


def channel_of(msg: IrcMessage) -> str:
    return msg.params[0].lstrip("#") if msg.params else ""


def is_moderator(tags: dict[str, str]) -> bool:
    """True for the broadcaster or a moderator -- the only accounts allowed to run `!jevmod` commands, and
    the same precondition Twitch itself enforces on the Helix moderation calls this adapter makes. `mod=1`
    covers moderators; the broadcaster's own messages carry `mod=0` (they are not "a moderator", they own the
    channel) but always a `broadcaster/1` badge, so both are checked."""
    if tags.get("mod") == "1":
        return True
    badges = tags.get("badges", "")
    return any(b.split("/", 1)[0] == "broadcaster" for b in badges.split(",") if b)


def timeout_seconds(minutes: int) -> int:
    """The one place a Helix `duration` is computed. Always a positive number, clamped to Twitch's documented
    maximum -- never 0, never None, never omitted: an omitted `duration` is what turns this same Helix call
    into a permanent ban on Twitch's side, which is exactly the action jevmod refuses to take."""
    seconds = max(1, int(minutes) * 60)
    return min(seconds, MAX_TIMEOUT_S)


# ---------------------------------------------------------------- Helix request shapes (pure)
#
# What gets sent, not how it's sent: kept separate from the network call so the "never omit duration" and
# "reason is always truncated to what Helix accepts" guarantees are testable without mocking `urllib`.

_HELIX_REASON_MAX = 500  # Helix's own documented limit for /moderation/bans' reason field


def timeout_request_body(user_id: str, policy_timeout_minutes: int, reason: str) -> dict:
    return {
        "data": {
            "user_id": user_id,
            "duration": timeout_seconds(policy_timeout_minutes),
            "reason": reason[:_HELIX_REASON_MAX],
        }
    }


def delete_message_params(broadcaster_id: str, moderator_id: str, message_id: str) -> dict:
    return {"broadcaster_id": broadcaster_id, "moderator_id": moderator_id, "message_id": message_id}


# ---------------------------------------------------------------- chat command parsing (pure)


def parse_command(text: str) -> tuple[str, list[str]] | None:
    """`!jevmod <subcommand> [args...]`, tokenized on whitespace. Returns None for anything that is not a
    `!jevmod` command (including a bare `!jevmod` with no subcommand, which has nothing to dispatch)."""
    parts = text.strip().split()
    if not parts or parts[0].lower() != CMD_PREFIX:
        return None
    if len(parts) < 2:
        return None
    return parts[1].lower(), parts[2:]


def dispatch_status(p: Policy, judged: int, requests: int, tokens: int) -> str:
    """`!jevmod status`. One line, not Discord/Telegram's multi-line reply: an IRC PRIVMSG reply is one chat
    message, and a wall of separate lines reads as flooding a channel jevmod is supposed to be protecting."""
    on = [f"{c} {p.actions[c]}" for c in CATEGORIES if p.actions.get(c, "off") != "off"]
    cats = ", ".join(on) if on else "no categories on"
    return f"jevmod: {cats} · {len(p.rules)} rule(s) · {judged:,} judged this month"


def dispatch_set(p: Policy, args: list[str]) -> str:
    """`!jevmod set <category> <off|flag|delete|timeout> [threshold]` -- same shape and same underlying
    `Policy.set_category` as every other adapter's equivalent command; parity of settings, not a rewrite."""
    if len(args) < 2:
        raise ValueError(f"usage: {CMD_PREFIX} set <category> <{'|'.join(ACTIONS)}> [0.5-0.99]")
    category, action = args[0], args[1]
    threshold = float(args[2]) if len(args) > 2 else None
    p.set_category(category, action, threshold)
    return f"{category} -> {action} at p >= {p.thresholds[category]:.2f}"


def dispatch_rule(p: Policy, args: list[str]) -> str:
    """`!jevmod rule <name> <text...>` or `!jevmod rule <name> remove`."""
    if not args:
        raise ValueError(f"usage: {CMD_PREFIX} rule <name> <rule text> | {CMD_PREFIX} rule <name> remove")
    name = args[0]
    text = " ".join(args[1:])
    p.set_rule(name, None if text.strip().lower() == "remove" else text)
    return f"rule {name}: {p.rules.get(name, 'removed')}"


# ---------------------------------------------------------------- Helix client (network; not unit-tested)


class HelixClient:
    """Blocking `urllib.request` calls, always run through `asyncio.to_thread` by the caller -- the same
    "stdlib HTTP off the event loop" shape `telegram_bot.cmd_pattern` already uses for its own blocking call,
    chosen here so this adapter does not need a second HTTP dependency alongside `websockets`."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = ""

    def refresh(self) -> None:
        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:  # fixed Twitch host, not user-controlled
            data = json.loads(resp.read())
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)

    def _request(self, method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> dict:
        url = f"{HELIX_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(json_body).encode() if json_body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Client-Id", self.client_id)
        req.add_header("Authorization", f"Bearer {self.access_token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                self.refresh()
                req.add_header("Authorization", f"Bearer {self.access_token}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            raise

    def get_user_id(self, login: str) -> str:
        data = self._request("GET", "/users", {"login": login})
        return data["data"][0]["id"]

    def delete_message(self, broadcaster_id: str, moderator_id: str, message_id: str) -> None:
        self._request("DELETE", "/moderation/chat", delete_message_params(broadcaster_id, moderator_id, message_id))

    def apply_timeout(self, broadcaster_id: str, moderator_id: str, user_id: str, minutes: int, reason: str) -> None:
        self._request(
            "POST",
            "/moderation/bans",
            {"broadcaster_id": broadcaster_id, "moderator_id": moderator_id},
            timeout_request_body(user_id, minutes, reason),
        )


# ---------------------------------------------------------------- decision -> Helix action


async def act(helix: HelixClient, broadcaster_id: str, moderator_id: str, tags: dict, d, policy: Policy) -> None:
    if d.action == "none" or d.action == "off":
        return
    reason = f"jevmod: {d.category} p={d.probability:.2f}"
    if d.action == "flag":
        # No channel-visible destination on this platform (see module docstring) -- the process log is the
        # whole of "flag" here, honestly, rather than pretending a chat message would not itself be noise.
        log.info({"event": "flag", "message_id": tags.get("id"), "category": d.category, "p": d.probability})
        return
    message_id = tags.get("id", "")
    user_id = tags.get("user-id", "")
    try:
        if d.action in ("delete", "timeout") and message_id:
            await asyncio.to_thread(helix.delete_message, broadcaster_id, moderator_id, message_id)
        if d.action == "timeout" and user_id:
            # Never a ban: `apply_timeout` always sends a `duration` (see timeout_request_body / module
            # docstring). This is a message-and-cooldown action, the same as every other adapter's `timeout`.
            minutes = policy.timeout_minutes
            await asyncio.to_thread(helix.apply_timeout, broadcaster_id, moderator_id, user_id, minutes, reason)
    except Exception as exc:
        log.warning("cannot act on %s: %s", message_id, exc)


# ---------------------------------------------------------------- run loop (network; not unit-tested)


async def _handle_batch(tenant: str, batch: list[tuple[IrcMessage, HelixClient, str, str]]) -> None:
    policy = service.policy(tenant)
    msgs = [
        Message(
            id=irc.tags.get("id", str(i)),
            text=irc.trailing or "",
            author=irc.tags.get("display-name", ""),
            channel_topic=store.get_meta(tenant).get("topic", f"twitch/{channel_of(irc)}"),
            author_trusted=is_moderator(irc.tags),
        )
        for i, (irc, _helix, _bid, _mid) in enumerate(batch)
    ]
    decisions = await asyncio.to_thread(service.moderate, tenant, msgs)
    for (irc, helix, broadcaster_id, moderator_id), d in zip(batch, decisions, strict=True):
        if d.action != "none":
            await act(helix, broadcaster_id, moderator_id, irc.tags, d, policy)


batcher = Batcher(BATCH_WINDOW_S, _handle_batch)


async def _read_irc(ws, channels: list[str]):
    """Yields parsed `IrcMessage`s, answering Twitch's keepalive `PING` on the same connection without
    surfacing it to the caller -- a bot that does not `PONG` back gets disconnected."""
    async for raw in ws:
        for line in raw.splitlines():
            if not line:
                continue
            msg = parse_irc_line(line)
            if msg.command == "PING":
                await ws.send(f"PONG :{msg.trailing or 'tmi.twitch.tv'}")
                continue
            yield msg


async def run() -> None:
    import websockets

    client_id = os.environ["TWITCH_CLIENT_ID"]
    client_secret = os.environ["TWITCH_CLIENT_SECRET"]
    refresh_token = os.environ["TWITCH_REFRESH_TOKEN"]
    bot_login = os.environ["TWITCH_BOT_LOGIN"]
    channels = [c.strip().lstrip("#") for c in os.environ["TWITCH_CHANNELS"].split(",") if c.strip()]

    helix = HelixClient(client_id, client_secret, refresh_token)
    await asyncio.to_thread(helix.refresh)
    moderator_id = await asyncio.to_thread(helix.get_user_id, bot_login)
    broadcaster_ids = {c: await asyncio.to_thread(helix.get_user_id, c) for c in channels}

    log.info("streaming twitch channels %s", channels)
    async with websockets.connect(IRC_WS_URL) as ws:
        await ws.send(f"PASS oauth:{helix.access_token}")
        await ws.send(f"NICK {bot_login}")
        await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        for c in channels:
            await ws.send(f"JOIN #{c}")
        async for irc in _read_irc(ws, channels):
            if not is_privmsg(irc):
                continue
            channel = channel_of(irc)
            tenant = tenant_of(channel)
            broadcaster_id = broadcaster_ids.get(channel, "")
            text = irc.trailing or ""
            cmd = parse_command(text) if is_moderator(irc.tags) else None
            if cmd is not None:
                name, args = cmd
                p = service.policy(tenant)
                judged, requests, tokens = store.usage(tenant)
                try:
                    if name == "status":
                        reply = dispatch_status(p, judged, requests, tokens)
                    elif name == "set":
                        reply = dispatch_set(p, args)
                        service.save_policy(tenant, p)
                    elif name == "rule":
                        reply = dispatch_rule(p, args)
                        service.save_policy(tenant, p)
                    else:
                        continue
                except ValueError as exc:
                    reply = str(exc)
                await ws.send(f"PRIVMSG #{channel} :{reply}"[:500])
                continue
            if not service.policy(tenant).active():
                continue
            batcher.add(tenant, (irc, helix, broadcaster_id, moderator_id))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
