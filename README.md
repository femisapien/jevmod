# jevmod

Discord moderation with Jev (TypeSafe): every message judged for spam, scams, harassment, adult content, off-topic
and your own plain-language rules, with a probability per category, for a fraction of a cent per message.

Plug and play: invite the bot and it starts **flagging** into a private `#jevmod-log` channel. Nothing is deleted
until you say so. Tune with `/mod`.

## Run it (self-hosted)

1. Discord Developer Portal → New Application → Bot → **Reset Token** (copy it) → enable **Message Content Intent**
   and **Server Members Intent**.
2. OAuth2 → URL Generator → scopes `bot` + `applications.commands`; permissions: Read Messages, Send Messages,
   Manage Messages, Moderate Members, Manage Channels, Embed Links, Add Reactions. Open the URL, add it to your server.
3. ```
   set DISCORD_TOKEN=...            # from step 1
   set TYPESAFE_API_KEY=...         # https://console.typesafe.ai/settings/keys
   pip install typesafe-sdk "discord.py>=2.3"
   python bot.py
   ```

## Commands (server managers only)

| command | what |
|---|---|
| `/mod status` | current settings and this month's usage |
| `/mod set <category> <action> [threshold]` | `spam`, `scam`, `harassment`, `nsfw`, `offtopic` → `off`, `flag`, `delete`, `timeout` |
| `/mod rule <name> <text> [action]` | a rule in your words: "no politics", "English only in #general" (max 5) |
| `/mod trust <role>` | messages from that role are never judged |
| `/mod topic <text>` | what the current channel is for (used by `offtopic`) |
| `/mod log` | log decisions in the current channel |
| `/mod recent` | last decisions with probabilities |

React ❌ on a log entry to mark a false positive: the threshold for that category moves up a notch.

## Cost controls

Messages from moderators and trusted roles, messages under three words (unless they carry a link), and repeats of
already-judged text never reach Jev. Messages from one server within a 2-second window share one request. Only the
categories you enabled are asked. Measured: about 300 input tokens per judged message, $0.000013 at Jev's list price.
A server with 20,000 judged messages a month costs about $0.25 to run.

Free plan: 5,000 judged messages per server per month. Pro: unlimited, planned at $5/month.

## Data

Message text, author display name and the channel topic are sent to TypeSafe's API for judgment and not stored by
jevmod except in your own `jevmod.sqlite` decision log. TypeSafe's terms apply to that service. jevmod fails open:
if Jev is unreachable, messages are left alone.
