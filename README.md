# jevmod

Moderation for communities and apps, powered by [Jev](https://typesafe.ai) (TypeSafe's System One model).
Every message gets a probability for **spam, scam, harassment, adult content, off-topic, self-harm, doxxing,
sexual content involving minors** and for **your own rules written in plain language**. You own the thresholds and the actions. Every decision is logged with its numbers.

Flag-only by default: nothing is deleted until you turn that on. Fails open: if Jev is unreachable, messages are
left alone and the failure is logged.

Cost, measured: about 1,050 input tokens per judged message with all eight categories on, at Jev's list price
of $0.042 per million, so **$0.000045 per message**. A community with 20,000 judged messages a month costs
under $1 to run. Turn categories off and the price drops with them.

Pick your door:

| you are | you get | start |
|---|---|---|
| a community owner, not technical | a Discord, Telegram or Reddit bot you tune with commands | [Run the bot](#1-community-owner-run-the-bot) |
| a developer with user content | `pip install jevmod`: a CLI, a function or one HTTP call | [Developer](#2-developer-cli-package-and-http-api) |
| a team that must self-host | Docker image and compose file | [Self-host](#3-self-host-docker-and-compose) |

---

## 1. Community owner: run the bot

You need two things: a **TypeSafe API key** (free tier at [console.typesafe.ai](https://console.typesafe.ai)) and a
bot token from the platform. Keys are never pasted into chat or files that go to git; they live in environment
variables or a `.env` file that stays on your machine.

### Discord

1. [Developer Portal](https://discord.com/developers/applications) → New Application → Bot → **Reset Token** (copy
   it) → enable **Message Content Intent**. No other privileged intent is needed.
2. OAuth2 → URL Generator → scopes `bot` + `applications.commands`; permissions: Read Messages, Send Messages,
   Manage Messages, Moderate Members, Manage Channels, Embed Links, Add Reactions. Open the URL, add it to your server.
3. Run it:

```bash
pip install "jevmod[discord]"
export TYPESAFE_API_KEY=...   # Windows: set TYPESAFE_API_KEY=...
export DISCORD_TOKEN=...
jevmod discord
```

The bot creates a private `#jevmod-log` channel and starts flagging. Type `/mod status` to see the settings.

| command (server managers only) | what |
|---|---|
| `/mod status` | settings and this month's usage |
| `/mod set <category> <action> [threshold]` | `spam`, `scam`, `harassment`, `nsfw`, `offtopic`, `selfharm`, `doxxing`, `minors` → `off`, `flag`, `delete`, `timeout` |
| `/mod rule <name> <text> [action] [threshold]` | a rule in your words: "No politics. News about the game is fine." (max 5) |
| `/mod trust <role>` | messages from that role are never judged |
| `/mod topic <text>` | what the current channel is for (used by `offtopic`) |
| `/mod log` | log decisions in the current channel instead |
| `/mod recent` | last decisions with probabilities |
| `/mod forget` / `/mod forget_user @member` | delete everything stored about the server / one member |

React **❌** on a log entry to mark a false positive (threshold for that category goes up a notch), **✅** to confirm
a correct call (down a notch, never below 0.5). Two clicks a day calibrate the bot to your community.

### Telegram

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Add the bot to your group and make it an **admin** (delete messages, restrict members).
3. `pip install "jevmod[telegram]"`, set `TYPESAFE_API_KEY` and `TELEGRAM_TOKEN`, run `jevmod telegram`.

Admin commands in the group: `/mod_status`, `/mod_set <category> <action> [threshold]`, `/mod_rule <name> <text>`,
`/mod_topic <text>`. Run `/mod_log <group chat id>` inside a private admins chat to receive the decisions there.

### Reddit

Reddit's API terms restrict commercial use and require registration for moderation bots. jevmod's Reddit adapter is
for **your own subreddit with your own credentials**, non-commercial. Create a "script" app at
[reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) with a moderator account, then
`pip install "jevmod[reddit]"`, fill the `REDDIT_*` variables from `.env.example`, run `jevmod reddit`. It reports
by default; removal and bans are opt-in in the policy.

### What the bot sends where

Only the **message text** and the **channel topic** are sent to TypeSafe's API for judgment. Author names and ids
are never sent. TypeSafe's terms apply to that service. Locally, jevmod keeps a decision log (category,
probabilities, action, the first 300 characters of the text) for 30 days, then deletes it. `/mod forget` deletes
everything at once; leaving the server does the same automatically. Members whose message is removed get a
direct message saying an automated system did it and how to appeal to the moderators.

---

## 2. Developer: CLI, package and HTTP API

### CLI

```bash
pip install jevmod                     # TYPESAFE_API_KEY in the environment
jevmod check "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"
# scam 0.97                    'FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro'  [scam 0.97, spam 0.95, ...]

cat comments.txt | jevmod check --json --rule "No politics. Game news is fine." -   # one message per line
```

Exit code 0 when nothing triggers, 1 when something does, 2 on error: usable in a shell script or a CI job that
screens user-submitted text. `--topic` enables the off-topic check, `--threshold` sets one for every category,
`--json` prints one object per line with every probability.

### Python

```bash
pip install jevmod      # TYPESAFE_API_KEY in the environment
```

```python
from jevmod import Moderator, Policy

mod = Moderator()
d = mod.check("FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro", channel_topic="gaming")
d.action, d.category, d.probability  # ('flag', 'scam', 0.97)
d.scores  # {'spam': 0.95, 'scam': 0.97, 'harassment': 0.03, 'nsfw': 0.01}

# your thresholds, your actions, your rules
p = Policy()
p.set_category("scam", "delete", 0.7)
p.set_rule("no_politics", "No political discussion. Game news is fine.", action="flag", threshold=0.8)
mod = Moderator(policy=p)
decisions = mod.check_many(["...", "...", "..."], channel_topic="support")  # one Jev request for the batch
```

`check_many` is the cheap path: every message that passes the pre-filter goes to Jev in one request. Messages under
eight letters without a link, trusted authors and repeats of already-judged text are never sent.

### HTTP API

Run it (`jevmod api`, or the Docker image) with `JEVMOD_ADMIN_TOKEN` set, then mint a key per tenant:

```bash
curl -X POST localhost:8080/v1/keys -H "Authorization: Bearer $JEVMOD_ADMIN_TOKEN" \
     -H "Content-Type: application/json" -d '{"tenant":"my-app","label":"prod"}'
# {"api_key":"jm_...","note":"shown once; stored hashed"}
```

```bash
curl -X POST localhost:8080/v1/moderate -H "Authorization: Bearer jm_..." -H "Content-Type: application/json" -d '{
  "messages": [
    {"id":"a","text":"FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro","channel_topic":"gaming"},
    {"id":"b","text":"Anyone know if the patch fixed the inventory bug?","channel_topic":"gaming"}
  ]}'
```

```json
{"request_id":"9f1c…","decisions":[
  {"message_id":"a","action":"flag","category":"scam","probability":0.97,"scores":{"spam":0.95,"scam":0.97,"harassment":0.03,"nsfw":0.01},"judged":true,"reason":"jev"},
  {"message_id":"b","action":"none","category":null,"probability":0.0,"scores":{"spam":0.02,"scam":0.01,"harassment":0.02,"nsfw":0.01},"judged":true,"reason":"jev"}],
 "usage":{"judged_this_month":2,"jev_requests_this_month":1,"input_tokens_this_month":1180}}
```

| endpoint | what |
|---|---|
| `POST /v1/moderate` | up to 50 messages → decisions. `X-Request-Id` is echoed for tracing. |
| `GET/PUT /v1/policy` | thresholds, actions, rules, timeout minutes for this tenant |
| `GET /v1/decisions?limit=50` | the audit log (probabilities, action, 300 chars of text) |
| `DELETE /v1/tenant` | forget this tenant entirely |
| `POST /v1/keys` (admin) | mint a tenant key; keys are stored hashed |
| `GET /v1/health`, `GET /metrics` | liveness and Prometheus counters |

OpenAPI docs at `/docs`; a ready-made Postman collection in `docs/jevmod.postman_collection.json`. Any chatbot, forum or comment system that can make an HTTP call can use it; the Discord,
Telegram and Reddit bots are just adapters over the same service.

---

## 3. Self-host: Docker and compose

One image, one environment variable picks the role (`api`, `discord`, `telegram`, `reddit`). SQLite on a volume.

```bash
cp .env.example .env                # fill TYPESAFE_API_KEY and the tokens you use
docker compose up -d                # the API on :8080
docker compose --profile discord up -d    # add the Discord bot; --profile telegram likewise
```

Any host that runs a container works: a 4 $/month VM with `docker compose`, Fly.io or Railway with a volume for
the SQLite file. No cloud-specific deployment is required or provided.

Failure policy: Jev unreachable → decisions come back `reason="error_open"`, nothing is acted on, one warning per
batch is logged. Free quota (5,000 judged messages per tenant per month) exceeded → judging pauses, the owner is
told once, nothing is deleted while paused.

---

## Categories

| category | true when | default |
|---|---|---|
| `spam` | unsolicited promotion, invite farming, bare link drops, mass mentions | flag ≥ 0.85 |
| `scam` | fake giveaways, phishing domains, impersonated support, "DM me for a deal" | flag ≥ 0.75 |
| `harassment` | insults, slurs, threats, targeted abuse, in any language | flag ≥ 0.75 |
| `nsfw` | sexual or gore content for a general audience (below the threshold means SFW) | flag ≥ 0.80 |
| `offtopic` | unrelated to `channel_topic`; needs a topic to mean anything | off, 0.90 |
| `selfharm` | the author is in crisis or considering self-harm; flag so moderators reach out, never punish | flag ≥ 0.80 |
| `doxxing` | reveals or hunts private data about a real person | flag ≥ 0.80 |
| `minors` | sexualises a minor or shows grooming behaviour | flag ≥ 0.70 |
| `rule:<name>` | your rule in plain language, exceptions included, up to 5 | flag ≥ 0.80 |

Every check returns all enabled categories at once, in one request. Questions follow TypeSafe's `llm_guardrails`
cookbook (one yes/no question per hazard with explicit true/false criteria).

## How good is it

The judge was red-teamed with 98 labelled messages across unicode evasion (fullwidth, zalgo, homoglyphs, split
links), six languages, gaming slang that must not be flagged, prompt injection inside messages, custom rules and
very short or very long inputs. The set lives in `tests/data/redteam.csv` and runs as a regression suite against the
real API. Current scoreboard with default thresholds:

| block | messages | false positives | false negatives |
|---|---|---|---|
| evasion | 16 | 0 | 0 |
| languages (es, pt, fr, de, ru, ja) | 20 | 0 | 0 |
| clean gaming chat | 20 | 0 | 0 |
| injection attempts | 8 | 0 | 0 |
| custom rules | 14 | 0 | 2 |
| length extremes | 11 | 0 | 0 |
| adult content | 5 | 0 | 0 |

The two misses in custom rules are both borderline politics ("trans rights are human rights, and the new character…"
at 0.64; "ugh the elections tomorrow, whatever, tonight we raid" at 0.77 with the rule threshold at 0.80). Jev's
probabilities move about ±0.03 between runs, so anything within that band of a threshold will flip; your
community's ❌/✅ moves the line to where you want it. One hundred messages is a regression suite, not a benchmark; numbers on your own
traffic will differ, and `/mod recent` shows you exactly where.

## Development

```bash
git clone https://github.com/ohernandezdev/jevmod && cd jevmod
python -m venv .venv && .venv/Scripts/pip install -e ".[all,dev]"
ruff check . && mypy jevmod && pytest          # offline tests run without a key; the rest need TYPESAFE_API_KEY
```

## License

MIT. jevmod is an independent project by Omar Hernandez and is not affiliated with TypeSafe, Discord, Telegram or
Reddit. Moderation decisions are probabilistic; you are responsible for the thresholds and actions you configure
and for complying with the platforms' terms and the laws that apply to your community.
