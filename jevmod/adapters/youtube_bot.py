"""YouTube adapter. Polls a live stream's chat through the YouTube Data API's `liveChatMessages.list`,
judges it through the same shared `ModerationService.moderate()` every other adapter calls, and acts
through the same API's message-delete and live-chat-ban endpoints. Chat commands (`!jevmod status`,
`!jevmod set ...`, `!jevmod rule ...`) give a channel owner Discord's core settings surface, the same flat
shape Twitch uses, not its full command list -- see "what's still missing" below.

    YOUTUBE_CLIENT_ID=... YOUTUBE_CLIENT_SECRET=... YOUTUBE_REFRESH_TOKEN=... \\
    YOUTUBE_CHANNEL_ID=... YOUTUBE_VIDEO_ID=... TYPESAFE_API_KEY=... python -m jevmod.adapters.youtube_bot

Design decisions, written down because they are the actual content of issue #30, not just its plumbing:

Getting the messages at all, and what the quota actually allows. `liveChatMessages.list` is a polling
endpoint, not a push subscription -- read that first, checked against the live docs and Google's own quota
calculator rather than assumed, per the standing rule to verify before declaring a limit rather than
guessing at one. The googleapis quota calculator (developers.google.com/youtube/v3/determine_quota_cost)
prices it at **1 unit per call** against the **default 10,000 units/day** every new project gets; a project's
default daily allowance therefore covers roughly 10,000 polls a day if `liveChatMessages.list` were the only
thing consuming it, before spending anything on `liveChatMessages.delete` or `liveChatBans.insert` (50 units
each) or the reply that a chat command costs (`liveChatMessages.insert`, also 50). That number matters
because a live stream is not intermittent the way a Discord server is: a single 24-hour stream polled once
every 5 seconds is 17,280 calls a day on its own, past the default allowance before a single moderation
action or command reply is spent. Two things make this tractable rather than a hard blocker: the response
itself carries `pollingIntervalMillis`, YouTube's own throttle telling the client how long to wait before
asking again (see "the batch window" below, this is not a fixed constant the way Discord's or Twitch's is);
and the ceiling is a *default* a project starts with, raisable through the ordinary Cloud Console quota
request form -- the same kind of one-time operator action the OAuth section below already requires, not a
recurring cost this adapter pays per message. `liveChatMessages.streamList`, a genuinely push-based
server-streaming alternative added to the docs since Twitch's adapter was written, exists and would remove
polling from the equation entirely, but its actual wire protocol is not documented as plain REST/JSON the
way the rest of the Data API is (the reference page frames its errors in gRPC status-code terms), and no
worked example of calling it without Google's heavier client stack turned up in the time this change had to
verify one honestly. Reaching for it on a guess -- adding a dependency and a code path this change cannot
prove works -- is worse than a documented, quota-accounted `.list` poll that is provably correct against the
same docs everything else in this module cites. `.list` is what ships; `.streamList` is a documented, not
yet verified, follow-up (see "what's still missing").

What it can do, and what has nowhere to go. YouTube's Data API offers deleting a single chat message
(`liveChatMessages.delete`) and banning a user from a live chat (`liveChatBans.insert`), which takes a
`type` of `permanent` or `temporary` with an optional `banDurationSeconds` for the temporary kind. jevmod
does not ban. `delete` maps to the delete endpoint. `timeout` maps to the *same* ban endpoint Twitch's
adapter reasoned about -- but unlike Twitch, where an omitted field is what silently turns a call into a
permanent ban, YouTube's endpoint makes the two cases two different, explicit values of `type`; this
adapter's `ban_request_body()` is the one place that value is set, and it is hardcoded to the literal string
`"temporary"` with `banDurationSeconds` always attached -- there is no code path that can pass `"permanent"`,
which is the guardrail `test_offline.py::test_no_adapter_can_ban_anybody` checks for by grepping every
adapter file for call shapes a ban would need. `off`/`flag` reach no endpoint: like Twitch, there is no
per-channel destination an ordinary bot account can post a private flag into (a YouTube live chat has no
notion of a moderator-only side channel the way a Discord server does), so `flag` here is a structured
`log.info` line on the process's own logs -- visible to whoever runs the bot, invisible to the channel,
exactly the same honest gap Twitch's module documents.

Who is allowed to, and what the operator has to obtain. Deleting a message or banning a user requires "the
channel owner or a moderator of the live chat," per the delete endpoint's own docs, and an OAuth *user*
token (not an API key) carrying at least one of the `youtube` or `youtube.force-ssl` scopes -- the same
"a user token for an account that already has standing on the platform" shape Twitch and Reddit both
require, obtained once through Google's OAuth authorization-code flow for a bot/moderator account and kept
alive here via `YOUTUBE_REFRESH_TOKEN` (access tokens expire in about an hour; `YouTubeClient.refresh`
trades the refresh token for a new access token before every run and whenever a call comes back 401, the
same shape `HelixClient.refresh` uses for Twitch). `youtube.force-ssl` is a *restricted* Google OAuth scope:
a self-hosted operator moderating their own channel adds themselves as a test user on their own OAuth
client and never needs Google's review at all (Google's "Testing" publishing status allows up to 100 test
users with no verification step) -- the same shape this repository already assumes for every adapter, where
the operator brings their own credentials. A *hosted*, multi-tenant product onboarding channels it does not
own is a different application in Google's own terms and would need to clear Google's OAuth verification
process for a restricted scope, and possibly a CASA security assessment, before it could add arbitrary third
-party channels; that is a jevmod-hosted concern, not a limitation of this adapter or this repository, and it
does not block a self-hosted operator from running this exactly the way they already run Twitch's.

The batch window. Discord's window is a fixed 2 seconds; Twitch's is a fixed 1 second because chat moves
faster there. Polling changes the question entirely: this adapter has no timer of its own to pick, because
the window *is* whatever `pollingIntervalMillis` the previous `.list` response said to wait before asking
again -- YouTube is already deciding, server-side, how long to accumulate messages before handing them back
in one page, and every message on one page becomes exactly one batch handed to `ModerationService.moderate`
in one call, matching the "one Jev request per batch" economics every other adapter relies on. This adapter
therefore does not use the shared `Batcher` class the other four import: `Batcher` exists to coalesce
irregular, push-driven arrivals behind a fixed timer, and a poll loop is already exactly that coalescing,
done by the server instead of by this process. `poll_wait_s()` is the one place that value is read, floored
at `MIN_POLL_WAIT_S` (2 seconds) so a quiet chat or an API hiccup returning something implausibly small
cannot turn this into the tight loop `rateLimitExceeded` exists to punish.

What's still missing, honestly, not silently. `flag` has nowhere to go, the same gap Twitch documents for
the same underlying reason (no private per-channel destination). `liveChatMessages.streamList`, the
push-based alternative to polling, is a documented follow-up, not a limitation being reached for silently:
see the quota section above for exactly why it was not used. This adapter expects `YOUTUBE_VIDEO_ID` to name
an *already live* broadcast at startup -- it resolves that video's `liveChatId` once
(`videos.list(part=liveStreamingDetails)`, 1 quota unit) and polls that chat until the process is restarted
for the next stream; it does not watch a channel for when a stream starts (YouTube gives no cheap way to do
that: polling `liveBroadcasts.list(broadcastStatus=active, mine=true)` on some interval to auto-discover a
new stream is possible but spends quota on every check whether or not anyone is live, and was left out
rather than guessed at). A chat command's reply costs 50 quota units (`liveChatMessages.insert`) same as a
moderation action, so `!jevmod status/set/rule` are not free the way Twitch's IRC replies are -- worth
knowing, not worth a special case, since these commands are rare next to ordinary chat volume. This adapter
has not been run against a live YouTube stream: doing that needs a registered Google Cloud OAuth client and a
real channel owner's consent, which is an account-holder action this change cannot perform on its own.
Everything with a right answer independent of that -- the quota-cost numbers, the never-a-permanent-ban
guardrail, the poll-interval flooring, the command dispatch, the batch/action wiring -- is unit-tested in
tests/test_youtube_local_commands.py; the poll loop and the live API calls are not, the same honest gap
test_twitch_local_commands.py already documents for Twitch's own reconnect loop and live Helix calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from ..core import Batcher, ModerationService, Policy, Store
from ..core.policy import ACTIONS
from ..judge import CATEGORIES, Message

log = logging.getLogger("jevmod.youtube")
store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
service = ModerationService(store)

_ = Batcher  # not used here -- see "the batch window" in the module docstring for why

API_BASE = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CMD_PREFIX = "!jevmod"
# YouTube does not document a maximum for `banDurationSeconds` the way Twitch documents a 14-day cap for its
# own timeout endpoint. 24 hours is this adapter's own conservative ceiling, chosen so a generous policy
# `timeout_minutes` can never ask the API for something open-ended -- not a number YouTube publishes.
MAX_TIMEOUT_S = 86_400
# A floor under `pollingIntervalMillis`, not YouTube's own suggestion: see "the batch window" above. Nothing
# in this codebase should poll faster than once every two seconds no matter what a response claims.
MIN_POLL_WAIT_S = 2.0
_GOOGLE_REASON_MAX = 500  # liveChatBans has no documented reason field; the ban body carries none


def tenant_of(channel_id: str) -> str:
    return f"youtube:{channel_id}"


def timeout_seconds(minutes: int) -> int:
    """The one place a ban `banDurationSeconds` is computed. Always positive, clamped to `MAX_TIMEOUT_S`."""
    seconds = max(1, int(minutes) * 60)
    return min(seconds, MAX_TIMEOUT_S)


# ---------------------------------------------------------------- API request shapes (pure)
#
# What gets sent, not how it's sent: kept separate from the network call so the "type is always temporary,
# never permanent" guarantee is testable without mocking `urllib`.


def ban_request_body(live_chat_id: str, banned_channel_id: str, policy_timeout_minutes: int) -> dict:
    return {
        "snippet": {
            "liveChatId": live_chat_id,
            "type": "temporary",  # hardcoded: see module docstring, this is the whole guardrail
            "banDurationSeconds": timeout_seconds(policy_timeout_minutes),
            "bannedUserDetails": {"channelId": banned_channel_id},
        }
    }


def delete_message_params(message_id: str) -> dict:
    return {"id": message_id}


def poll_wait_s(polling_interval_millis: int | None) -> float:
    """`pollingIntervalMillis` from the previous `.list` response, floored at `MIN_POLL_WAIT_S`. A missing or
    non-positive value (a malformed response, or a first call before one exists) falls back to the floor
    rather than a guess at what YouTube meant."""
    if not polling_interval_millis or polling_interval_millis <= 0:
        return MIN_POLL_WAIT_S
    return max(MIN_POLL_WAIT_S, polling_interval_millis / 1000.0)


# ---------------------------------------------------------------- chat item parsing (pure)


def is_trusted(author_details: dict) -> bool:
    """The channel owner or a moderator -- the only accounts `liveChatMessages.delete` and `liveChatBans.insert`
    already require to be the *caller*, and the same accounts jevmod exempts from judging everywhere else
    (Discord's `manage_messages`, Twitch's `is_moderator`). YouTube puts both as plain booleans on
    `authorDetails`, no badge string to parse the way Twitch's IRC tags need."""
    return bool(author_details.get("isChatOwner")) or bool(author_details.get("isChatModerator"))


def is_text_message(item: dict) -> bool:
    """Only ordinary chat lines are judged or actioned. Super Chats, membership milestones and the like carry
    a `displayMessage` too, but deleting or timing someone out over a paid Super Chat is a different, murkier
    feature than "read the words and judge them" -- out of scope the same way Reddit's adapter never follows
    a link post's URL to judge the page behind it."""
    return item.get("snippet", {}).get("type") == "textMessageEvent"


def message_text(item: dict) -> str:
    return item.get("snippet", {}).get("displayMessage", "") or ""


def author_name(item: dict) -> str:
    return item.get("authorDetails", {}).get("displayName", "") or ""


def author_channel_id(item: dict) -> str:
    return item.get("authorDetails", {}).get("channelId", "") or ""


# ---------------------------------------------------------------- chat command parsing (pure)
#
# Duplicated from twitch_bot.py rather than imported: importing it would tie this adapter's import to
# Twitch's module (and, transitively, nothing heavy here, but the other adapters draw the same line for
# their own optional dependencies -- see telegram_bot.py's `_toggle_list` comment -- and this keeps every
# adapter importable on its own).


def parse_command(text: str) -> tuple[str, list[str]] | None:
    """`!jevmod <subcommand> [args...]`, tokenized on whitespace. None for anything that is not a `!jevmod`
    command, including a bare `!jevmod` with no subcommand."""
    parts = text.strip().split()
    if not parts or parts[0].lower() != CMD_PREFIX:
        return None
    if len(parts) < 2:
        return None
    return parts[1].lower(), parts[2:]


def dispatch_status(p: Policy, judged: int, requests: int, tokens: int) -> str:
    """`!jevmod status`. One line, same reasoning as Twitch's: a reply here costs 50 quota units
    (`liveChatMessages.insert`), so a wall of separate lines is not just noisy, it is not free."""
    on = [f"{c} {p.actions[c]}" for c in CATEGORIES if p.actions.get(c, "off") != "off"]
    cats = ", ".join(on) if on else "no categories on"
    return f"jevmod: {cats} · {len(p.rules)} rule(s) · {judged:,} judged this month"


def dispatch_set(p: Policy, args: list[str]) -> str:
    """`!jevmod set <category> <off|flag|delete|timeout> [threshold]`."""
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


# ---------------------------------------------------------------- Data API client (network; not unit-tested)


class YouTubeClient:
    """Blocking `urllib.request` calls, always run through `asyncio.to_thread` by the caller -- the same
    "stdlib HTTP off the event loop" shape `HelixClient` uses for Twitch, chosen here for the same reason:
    it needs no dependency beyond the standard library, so this adapter adds none at all (unlike Twitch's
    `websockets`, required because IRC-over-WebSocket has no REST equivalent to fall back on)."""

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
        with urllib.request.urlopen(req, timeout=10) as resp:  # fixed Google host, not user-controlled
            data = json.loads(resp.read())
        self.access_token = data["access_token"]

    def _request(self, method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> dict:
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(json_body).encode() if json_body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
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

    def resolve_live_chat_id(self, video_id: str) -> str:
        """1 quota unit, spent once per run, not once per poll -- see the module docstring's quota section."""
        data = self._request("GET", "/videos", {"part": "liveStreamingDetails", "id": video_id})
        items = data.get("items", [])
        if not items:
            raise RuntimeError(f"video {video_id} not found or has no live chat")
        chat_id = items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
        if not chat_id:
            raise RuntimeError(f"video {video_id} has no active live chat (is it actually live?)")
        return chat_id

    def list_messages(self, live_chat_id: str, page_token: str | None) -> dict:
        params = {"liveChatId": live_chat_id, "part": "id,snippet,authorDetails"}
        if page_token:
            params["pageToken"] = page_token
        return self._request("GET", "/liveChat/messages", params)

    def delete_message(self, message_id: str) -> None:
        self._request("DELETE", "/liveChat/messages", delete_message_params(message_id))

    def apply_timeout(self, live_chat_id: str, banned_channel_id: str, minutes: int) -> None:
        self._request(
            "POST",
            "/liveChat/bans",
            {"part": "snippet"},
            ban_request_body(live_chat_id, banned_channel_id, minutes),
        )

    def send_reply(self, live_chat_id: str, text: str) -> None:
        """A chat command's reply -- 50 quota units (`liveChatMessages.insert`), see the module docstring."""
        self._request(
            "POST",
            "/liveChat/messages",
            {"part": "snippet"},
            {
                "snippet": {
                    "liveChatId": live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {"messageText": text[:200]},
                }
            },
        )


# ---------------------------------------------------------------- decision -> API action


async def act(client: YouTubeClient, live_chat_id: str, item: dict, d, policy: Policy) -> None:
    if d.action in ("none", "off"):
        return
    message_id = item.get("id", "")
    channel_id = author_channel_id(item)
    if d.action == "flag":
        # No channel-visible destination on this platform (module docstring) -- the process log is the whole
        # of "flag" here, the same honest gap Twitch's adapter documents.
        log.info({"event": "flag", "message_id": message_id, "category": d.category, "p": d.probability})
        return
    try:
        if d.action in ("delete", "timeout") and message_id:
            await asyncio.to_thread(client.delete_message, message_id)
        if d.action == "timeout" and channel_id:
            # Never a ban: `ban_request_body` always sends `type: "temporary"` with a `banDurationSeconds`
            # (see module docstring / ban_request_body). A message-and-cooldown action, same as every other
            # adapter's `timeout`.
            await asyncio.to_thread(client.apply_timeout, live_chat_id, channel_id, policy.timeout_minutes)
    except Exception as exc:
        log.warning("cannot act on %s: %s", message_id, exc)


# ---------------------------------------------------------------- run loop (network; not unit-tested)


async def _handle_page(tenant: str, client: YouTubeClient, live_chat_id: str, items: list[dict]) -> None:
    text_items = [i for i in items if is_text_message(i)]
    if not text_items:
        return
    policy = service.policy(tenant)
    commands, judged_items = [], []
    for item in text_items:
        text = message_text(item)
        trusted = is_trusted(item.get("authorDetails", {}))
        cmd = parse_command(text) if trusted else None
        if cmd is not None:
            commands.append((item, cmd))
        else:
            judged_items.append(item)

    for _item, (name, args) in commands:
        judged, requests, tokens = store.usage(tenant)
        try:
            if name == "status":
                reply = dispatch_status(policy, judged, requests, tokens)
            elif name == "set":
                reply = dispatch_set(policy, args)
                service.save_policy(tenant, policy)
            elif name == "rule":
                reply = dispatch_rule(policy, args)
                service.save_policy(tenant, policy)
            else:
                continue
        except ValueError as exc:
            reply = str(exc)
        await asyncio.to_thread(client.send_reply, live_chat_id, reply)

    if not judged_items or not policy.active():
        return
    msgs = [
        Message(
            id=item.get("id", ""),
            text=message_text(item),
            author=author_name(item),
            channel_topic=store.get_meta(tenant).get("topic", "youtube live chat"),
            author_trusted=is_trusted(item.get("authorDetails", {})),
        )
        for item in judged_items
    ]
    decisions = await asyncio.to_thread(service.moderate, tenant, msgs)
    by_id = {item.get("id", ""): item for item in judged_items}
    for d in decisions:
        if d.action != "none":
            await act(client, live_chat_id, by_id[d.message_id], d, policy)


async def run() -> None:
    client_id = os.environ["YOUTUBE_CLIENT_ID"]
    client_secret = os.environ["YOUTUBE_CLIENT_SECRET"]
    refresh_token = os.environ["YOUTUBE_REFRESH_TOKEN"]
    channel_id = os.environ["YOUTUBE_CHANNEL_ID"]
    video_id = os.environ["YOUTUBE_VIDEO_ID"]

    client = YouTubeClient(client_id, client_secret, refresh_token)
    await asyncio.to_thread(client.refresh)
    live_chat_id = await asyncio.to_thread(client.resolve_live_chat_id, video_id)
    tenant = tenant_of(channel_id)

    log.info("polling youtube live chat %s for channel %s", live_chat_id, channel_id)
    page_token: str | None = None
    while True:
        resp = await asyncio.to_thread(client.list_messages, live_chat_id, page_token)
        items = resp.get("items", [])
        page_token = resp.get("nextPageToken", page_token)
        if items:
            await _handle_page(tenant, client, live_chat_id, items)
        await asyncio.sleep(poll_wait_s(resp.get("pollingIntervalMillis")))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
