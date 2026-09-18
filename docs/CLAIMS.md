# Claims on jevmod.dev

Every sentence on the site that carries a number or an absolute has a `data-claim="C##"` attribute and one row
here. `scripts/site/check_claims.py` verifies both directions and every source.

Source formats:

- `path:line` (repository-relative): the line must exist and contain the `token`, or, when `token` is empty, at
  least one word of 4 or more characters from the sentence.
- `tests/test_x.py::test_y`: the test function must exist.
- `docs/img/name.webp`: a screenshot that shows the statement; the file must exist.

Id ranges: C01 to C39 belong to `/`, C40 to C79 to `/developers/`, C80 and up to `/privacy/` and `/terms/`.

## Claims from / and /developers/ (filled by the coordinator from agents A and B)

| id | page | sentence | source | token | verified |
|---|---|---|---|---|---|

## Claims on /privacy/

| id | page | sentence | source | token | verified |
|---|---|---|---|---|---|
| C80 | /privacy/ | For each message it judges, the bot sends the message text and the topic of the channel to Jev, the model run by TypeSafe. | jevmod/judge.py:144 | channel_topic | yes |
| C81 | /privacy/ | It does not send the author's name, the author's id or the server's name. Messages are numbered by position inside the request and nothing else identifies them. | jevmod/judge.py:141 | author | yes |
| C82 | /privacy/ | The author's id is kept only in the bot's own log so that erasure requests can be honoured. | jevmod/adapters/discord_bot.py:47 | erasure | yes |
| C83 | /privacy/ | Messages from members who can manage messages, and from roles you mark as trusted with /mod trust, are never sent to the model. | jevmod/adapters/discord_bot.py:65 | manage_messages | yes |
| C84 | /privacy/ | The bot writes a record only when a message crosses one of your thresholds and gets an action (flag, delete or time out). | jevmod/core/service.py:75 | action | yes |
| C85 | /privacy/ | A message that passes is not written anywhere. | jevmod/core/service.py:76 | log_decision | yes |
| C86 | /privacy/ | Each stored record holds: the message id, the author id, the first 80 characters of the channel topic, the category, its probability, the action taken, the probability of every category asked, a request id and a timestamp. | jevmod/core/store.py:264 | channel_topic | yes |
| C87 | /privacy/ | The record has a text column, but the hosted bot runs with JEVMOD_KEEP_TEXT_CHARS set to 0, so that column is always empty. | deploy/demo/docker-compose.traefik.yml:46 | JEVMOD_KEEP_TEXT_CHARS | yes |
| C88 | /privacy/ | The store cuts the text to that many characters before writing it, and with 0 nothing of the text is written. | jevmod/core/store.py:269 | keep_text_chars | yes |
| C89 | /privacy/ | A test in the repository checks that setting. | tests/test_offline.py::test_keep_text_chars_env_and_zero | | yes |
| C90 | /privacy/ | Per server and per calendar month the bot also counts judged messages, model requests and tokens, for the quota. | jevmod/core/store.py:51 | judged | yes |
| C91 | /privacy/ | Decision records are kept for 30 days. | jevmod/core/store.py:32 | retention_days | yes |
| C92 | /privacy/ | Older records are deleted before every batch is judged. | jevmod/core/service.py:52 | purge_expired | yes |
| C93 | /privacy/ | Your settings (thresholds, actions, rules, trusted roles, channel topics, the id of the log channel) are stored for as long as the bot is in your server. | jevmod/core/store.py:48 | policy | yes |
| C94 | /privacy/ | Every flagged message is posted to a log channel as an embed that contains the first 500 characters of the message text. | jevmod/adapters/discord_bot.py:114 | content | yes |
| C95 | /privacy/ | That embed also mentions the author and the channel. | jevmod/adapters/discord_bot.py:117 | author | yes |
| C96 | /privacy/ | The log channel is created with the everyone role unable to read it. | jevmod/adapters/discord_bot.py:137 | read_messages | yes |
| C97 | /privacy/ | When a message is deleted or a member is timed out, the member receives a direct message from the bot with the server name, the channel, the category and the confidence, and a note to contact the server's moderators. | jevmod/adapters/discord_bot.py:104 | send | yes |
| C98 | /privacy/ | /mod forget deletes the server's settings, usage counters, decision records, API keys and subscription row. | jevmod/adapters/discord_bot.py:324 | delete_tenant | yes |
| C99 | /privacy/ | /mod forget_user @member deletes that member's decision records and replies with how many were removed. | jevmod/adapters/discord_bot.py:332 | delete_user | yes |
| C100 | /privacy/ | Kicking the bot, or the bot leaving the server, deletes everything stored about that server. | jevmod/adapters/discord_bot.py:188 | delete_tenant | yes |
| C101 | /privacy/ | All /mod commands require the Manage Server permission. | jevmod/adapters/discord_bot.py:194 | manage_guild | yes |
| C102 | /privacy/ | Payment for the Pro plan happens on a Stripe Checkout page opened from /mod upgrade. | jevmod/api/billing.py:76 | checkout | yes |
| C103 | /privacy/ | jevmod stores, per server: the Stripe customer id, the subscription id, the price id, the subscription status and the end of the current period. | jevmod/core/store.py:58 | subscription_id | yes |
| C104 | /privacy/ | Stripe notifies jevmod of changes through a webhook; when a subscription is cancelled or stops being active the server goes back to the Free plan. | jevmod/api/billing.py:128 | free | yes |
| C105 | /privacy/ | Managing or cancelling the subscription happens in Stripe's billing portal, reached through the same /mod upgrade command. | jevmod/api/billing.py:96 | billing_portal | yes |
| C106 | /privacy/ | The demo on the front page accepts up to 300 characters of text. | jevmod/api/demo.py:35 | MAX_CHARS | yes |
| C107 | /privacy/ | Each check is logged by the operator with the text, the category, the probabilities, a hash of your IP address, the country header set by the proxy, and the number of tokens it cost. | jevmod/api/demo.py:54 | ip_hash | yes |
| C108 | /privacy/ | The IP address is hashed with SHA-256 and a salt before it is stored; the address itself is not kept. | jevmod/api/demo.py:85 | sha256 | yes |
| C109 | /privacy/ | Each address may run 6 checks per minute and 40 per day. | jevmod/api/demo.py:34 | PER_DAY | yes |
| C110 | /privacy/ | The demo has a monthly spend cap, $0.50 by default, and answers with an error once it is reached. | jevmod/api/demo.py:32 | BUDGET_USD | yes |
| C111 | /privacy/ | A self-hosted Umami instance at analytics.hernandezbastos.es counts page views; it does not use cookies. | docs/privacy/index.html:13 | analytics.hernandezbastos.es | yes |
| C112 | /privacy/ | A self-hosted copy keeps up to 300 characters of each flagged message by default; set JEVMOD_KEEP_TEXT_CHARS=0 to keep none. | jevmod/core/store.py:40 | JEVMOD_KEEP_TEXT_CHARS | yes |
| C113 | /privacy/ | View Channels: to receive the messages it judges. | jevmod/adapters/discord_bot.py:78 | on_message | yes |
| C114 | /privacy/ | Send Messages: to post decisions in the log channel. | jevmod/adapters/discord_bot.py:120 | send | yes |
| C115 | /privacy/ | Manage Channels: to create the private #jevmod-log channel the first time it needs it. | jevmod/adapters/discord_bot.py:139 | create_text_channel | yes |
| C116 | /privacy/ | Manage Messages: to delete a message, only when you set a category or rule to delete or timeout. | jevmod/adapters/discord_bot.py:93 | delete | yes |
| C117 | /privacy/ | Moderate Members: to time a member out, only when you set a category or rule to timeout. | jevmod/adapters/discord_bot.py:96 | timeout | yes |
| C118 | /privacy/ | Add Reactions: to add the reactions under each log entry. | jevmod/adapters/discord_bot.py:121 | add_reaction | yes |
| C119 | /privacy/ | Embed Links: the log entry is an embed. | jevmod/adapters/discord_bot.py:112 | Embed | yes |
| C120 | /privacy/ | Read Message History: to fetch the log entry you reacted to, so it can adjust the threshold. | jevmod/adapters/discord_bot.py:174 | fetch_message | yes |
| C121 | /privacy/ | Message Content intent: without it Discord does not deliver message text to bots. | jevmod/adapters/discord_bot.py:25 | message_content | yes |
| C122 | /privacy/ | If a permission is missing, the bot records "missing permissions to act" in the log entry and does nothing else. | jevmod/adapters/discord_bot.py:101 | missing permissions | yes |
| C123 | /privacy/ | The bot has no code path that bans anyone; the only actions it knows are off, flag, delete and timeout. | jevmod/core/policy.py:10 | ACTIONS | yes |

## Claims on /terms/

| id | page | sentence | source | token | verified |
|---|---|---|---|---|---|
| C130 | /terms/ | jevmod is free software under the MIT License. | LICENSE:1 | MIT | yes |
| C131 | /terms/ | It is provided as is, without warranty of any kind. | LICENSE:15 | AS IS | yes |
| C132 | /terms/ | jevmod is an independent project by Omar Hernandez and is not affiliated with TypeSafe, Discord, Telegram or Reddit. | DISCLAIMER.md:16 | affiliation | yes |
| C133 | /terms/ | By default every category except offtopic is set to flag: the message is reported to your log channel and nothing else happens. | jevmod/core/policy.py:23 | DEFAULT_ACTIONS | yes |
| C134 | /terms/ | The offtopic category is off by default. | jevmod/core/policy.py:28 | offtopic | yes |
| C135 | /terms/ | The bot deletes a message or times a member out only for a category or rule you have set to delete or timeout with /mod set or /mod rule. | jevmod/adapters/discord_bot.py:214 | timeout | yes |
| C136 | /terms/ | A time out lasts 10 minutes. | jevmod/core/policy.py:44 | timeout_minutes | yes |
| C137 | /terms/ | The bot never bans anyone: its only actions are off, flag, delete and timeout. | jevmod/core/policy.py:10 | ACTIONS | yes |
| C138 | /terms/ | Thresholds go from 0.50 to 0.99. | jevmod/core/policy.py:155 | 0.99 | yes |
| C139 | /terms/ | You can add up to 5 rules in your own words. | jevmod/core/policy.py:69 | custom rules | yes |
| C140 | /terms/ | Decisions are probabilities from a machine-learning model compared with thresholds you set; there will be false positives and false negatives. | DISCLAIMER.md:6 | Probabilistic | yes |
| C141 | /terms/ | You are responsible for the actions you enable, for the rules you write, for telling your members that automated moderation is in use, and for complying with the law that applies to your community. | DISCLAIMER.md:9 | responsible | yes |
| C142 | /terms/ | The Free plan covers 5,000 judged messages per server per month. | .env.example:40 | 5000 | yes |
| C143 | /terms/ | The Pro plan costs $3.99 per server per month. | PRODUCT.md:71 | 3.99 | yes |
| C144 | /terms/ | Pro covers 50,000 judged messages per server per month. | .env.example:41 | 50000 | yes |
| C145 | /terms/ | Judged means sent to the model: the counter grows only by messages the model receives, so messages skipped by the local filters or answered from the cache do not count. | jevmod/core/service.py:69 | judged_messages | yes |
| C146 | /terms/ | When a server reaches its quota, judging pauses until the next calendar month and nothing is deleted while paused. | jevmod/adapters/discord_bot.py:153 | Nothing is deleted | yes |
| C147 | /terms/ | The bot posts one notice in the log channel the first time a month the quota is reached. | jevmod/adapters/discord_bot.py:147 | note_quota_hit | yes |
| C148 | /terms/ | Pro is a monthly subscription paid through Stripe Checkout, one price per server, started with /mod upgrade. | jevmod/api/billing.py:77 | subscription | yes |
| C149 | /terms/ | You can cancel at any time from Stripe's billing portal, reached with the same /mod upgrade command once you subscribe. | jevmod/api/billing.py:96 | billing_portal | yes |
| C150 | /terms/ | When the subscription ends the server returns to the Free plan. | jevmod/api/billing.py:128 | free | yes |
| C151 | /terms/ | A period already paid is not refunded, except by writing to the operator through the contact below; refunds are handled by hand. | PRODUCT.md:82 | refunds are manual | yes |
| C152 | /terms/ | There is no service level agreement; jevmod is not the right tool if you need one. | DISCLAIMER.md:24 | SLA | yes |
| C153 | /terms/ | If the model cannot be reached, the bot takes no action on that batch of messages and lets them through. | jevmod/core/service.py:67 | error_open | yes |
| C155 | /terms/ | The selfharm category exists to alert moderators so a person can reach out. It is not a medical or crisis service and must not be used as one. | DISCLAIMER.md:19 | reach out | yes |
| C156 | /terms/ | It is flag-only by design in the defaults. | jevmod/core/policy.py:21 | flag-only | yes |
