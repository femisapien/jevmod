# Claims on jevmod.dev

Every sentence on the site that carries a number or an absolute has a `data-claim="C##"` attribute and one row
here. `scripts/site/check_claims.py` verifies both directions and every source.

Source formats:

- `path:line` (repository-relative): the line must exist and contain the `token`, or, when `token` is empty, at
  least one word of 4 or more characters from the sentence.
- `tests/test_x.py::test_y`: the test function must exist.
- `docs/img/name.webp`: a screenshot that shows the statement; the file must exist.

Id ranges: C01 to C39 belong to `/`, C40 to C79 to `/developers/`, C80 and up to `/privacy/` and `/terms/`.

## Claims on /

| id | page | sentence | source | token | verified |
|---|---|---|---|---|---|
| C01 | / | Rates every message in your Discord server for spam, scams, harassment and four more. | jevmod/core/policy.py:25 | DEFAULT_ACTIONS | yes |
| C01b | / | The hosted bot is not running yet, so there is nothing to add to a server today. A copy you run yourself works now. It needs a Discord bot token and a TypeSafe key. | PRODUCT.md:76; PRODUCT.md:78; README.md:218 | Needed from Omar; DISCORD_TOKEN; SQLite on a volume | yes |
| C02 | / | Deletes only if you turn that on. | jevmod/core/policy.py:22 | flag | yes |
| C03 | / | It flags. It does not act until you say so. | jevmod/core/policy.py:25 | DEFAULT_ACTIONS | yes |
| C04 | / | A flagged message appears there with its category, its probability and the message. | jevmod/adapters/discord_bot.py:116; jevmod/adapters/discord_bot.py:124 | d.probability; description | yes |
| C04b | / | Nothing is posted when the bot cannot create or reach that channel, and nothing is judged at all while the server is over its monthly quota or the model is unreachable. | jevmod/adapters/discord_bot.py:168; jevmod/core/service.py:53; jevmod/core/service.py:68 | Forbidden; over_quota; error_open | yes |
| C05 | / | Members see nothing. | jevmod/adapters/discord_bot.py:149 | read_messages=False | yes |
| C06 | / | Nine questions. Seven asked by default. | jevmod/core/policy.py:11; jevmod/core/policy.py:25 | DEFAULT_THRESHOLDS; DEFAULT_ACTIONS | yes |
| C07 | / | Every category you have on gets its own probability from 0 to 1. Over the line for that category, the message is flagged. Off-topic and written by a model are off until you turn them on, so a new server gets seven numbers. A message the local filters settle is never sent to the model and gets no numbers at all. | jevmod/core/policy.py:91; jevmod/core/policy.py:30; jevmod/core/policy.py:34; jevmod/judge.py:95 | thresholds.get; offtopic; ai_generated; min_chars | yes |
| C08 | / | A message with nothing to do with the channel's topic. Off by default; /mod set offtopic flag turns it on. | jevmod/core/policy.py:30 | offtopic | yes |
| C09 | / | Sexual comments about someone under 18, or an adult building private trust with a child. | jevmod/categories.json:62 | building private trust | yes |
| C39 | / | A message that reads as assistant output rather than someone typing. Off by default; `/mod set ai_generated flag` turns it on. On our test set it separates model output from real chat almost perfectly, AUROC 0.971. At a realistic 2 in 100 rate of pasted model text the projected precision is 0.19 to 0.37, so most flags would be wrong. An experimental category can only flag: jevmod refuses to set it to delete or time out, and the reactions never move its line. | jevmod/core/policy.py:34; jevmod/core/policy.py:24; benchmark/ai_detect/REPORT.md:9; benchmark/ai_detect/REPORT.md:12; tests/test_offline.py::test_ai_generated_is_opt_in_and_not_nudged | ai_generated; EXPERIMENTAL; 0.971; 0.19-0.37; | yes |
| C39b | / | The live demo is closed right now. The example buttons still show what jevmod answered for them on 2026-09-18; run `jevmod check` with your own key for a live one. | docs/site.js:136 | RECORDED | yes |
| C10 | / | Add up to five rules in your own words. | jevmod/core/policy.py:76 | >= 5 | yes |
| C11 | / | Three commands cover most days. | jevmod/adapters/discord_bot.py:238; jevmod/adapters/discord_bot.py:254; jevmod/adapters/discord_bot.py:186 | name="set"; name="rule"; threshold | yes |
| C12 | / | /mod set scam delete 0.7 moves scam from flagging to deleting, with the line at 0.7. | jevmod/adapters/discord_bot.py:240 | delete | yes |
| C13 | / | React with the cross on a log entry when the bot was wrong and the line for that category moves up 0.03. The check moves it down 0.02. | jevmod/adapters/discord_bot.py:206 | 0.03 | yes |
| C14 | / | Time out, 10 minutes, needs Moderate Members. | jevmod/core/policy.py:47; jevmod/adapters/discord_bot.py:98 | timeout_minutes; timeout | yes |
| C15 | / | It cannot ban anyone. | jevmod/core/policy.py:10 | ACTIONS | yes |
| C16 | / | Roles you mark as trusted are never judged, and neither is anyone who can Manage Messages. | jevmod/adapters/discord_bot.py:65; jevmod/judge.py:87 | manage_messages; author_trusted | yes |
| C17 | / | A drawing of a cross on a log entry. The bot answers: noted: threshold for scam is now 0.78. | jevmod/adapters/discord_bot.py:208; jevmod/core/policy.py:13 | noted: threshold; 0.75 | yes |
| C18 | / | Measured on 2,531 public messages with human labels. | BENCHMARK.md:3 | 2,531 | yes |
| C18b | / | The four numbers below come from 1,680 of those messages, OpenAI's moderation set. The other 851 are 351 Civil Comments and 500 YouTube spam comments. | BENCHMARK.md:23; BENCHMARK.md:24; BENCHMARK.md:25 | 1,680; 351; 500 | yes |
| C19 | / | 0.93 harassment AUROC. At the line it ships with it catches 78 of every 100. | BENCHMARK.md:40; benchmark/results/report.md:4 | 0.930; 0.78 | yes |
| C20 | / | 0.98 sexual content AUROC. At the line it ships with it catches 89 of every 100. | BENCHMARK.md:44; benchmark/results/report.md:10 | 0.982; 0.89 | yes |
| C21 | / | 0.99 self-harm AUROC. At the line it ships with it catches 59 of every 100. | BENCHMARK.md:48; benchmark/results/report.md:14 | 0.992; 0.59 | yes |
| C22 | / | 0.98 minors AUROC. At the line it ships with it catches 41 of every 100. | BENCHMARK.md:50; benchmark/results/report.md:8 | 0.977; 0.41 | yes |
| C23 | / | AUROC measures how well the scores rank messages: 1.0 is a perfect ranking, 0.5 a coin flip. | BENCHMARK.md:29 | AUROC | yes |
| C23b | / | AUROC says nothing about how much gets caught, because that depends on the line, and the lines jevmod ships with are high. On the YouTube spam set it catches 36 of every 100. | BENCHMARK.md:30; benchmark/results/report.md:28 | not depend on the threshold; 0.36 | yes |
| C24 | / | On OpenAI's moderation set jevmod has the best AUROC in every category it was compared on, against Llama Guard 3, ShieldGemma and toxic-bert. | BENCHMARK.md:67 | best ranking quality | yes |
| C24b | / | On the any-violation row it ties with ShieldGemma 2B, both at 0.939. | benchmark/results/report.md:16; benchmark/results/report.md:18 | 0.939; 0.939 | yes |
| C24c | / | Five categories have numbers here: harassment, sexual content, self-harm, minors and spam. Scam, doxxing and off-topic have no labelled public set in this benchmark, so they were not measured. Written by a model was measured separately. | benchmark/results/report.md:2; benchmark/ai_detect/REPORT.md:1 | category; AI-generated | yes |
| C25 | / | What it will never do. | jevmod/core/policy.py:10 | ACTIONS | yes |
| C26 | / | It has no ban permission and no ban command. | jevmod/core/policy.py:10; PRODUCT.md:79 | ACTIONS; permissions integer | yes |
| C27 | / | If the model does not answer, the bot does nothing with that batch. Nothing is removed on a guess. | jevmod/core/service.py:68 | error_open | yes |
| C28 | / | The hosted bot runs with JEVMOD_KEEP_TEXT_CHARS set to 0, so it stores no message text. | deploy/demo/docker-compose.traefik.yml:46 | JEVMOD_KEEP_TEXT_CHARS | yes |
| C28b | / | A copy you run yourself keeps the first 300 characters of a flagged message until you set that variable to 0. | jevmod/core/store.py:40 | JEVMOD_KEEP_TEXT_CHARS | yes |
| C29 | / | Messages that pass are not stored at all. | jevmod/core/service.py:76 | action != | yes |
| C30 | / | Only the text and the channel topic go to the model. | jevmod/judge.py:141 | no author names | yes |
| C31 | / | Free for 5,000 judged messages a month. Pro is $3.99 a month. You cannot buy it yet. | .env.example:40; PRODUCT.md:71; PRODUCT.md:76 | 5000; 3.99; Needed from Omar | yes |
| C31b | / | /mod upgrade is the command that starts a subscription. On a Free server it opens Stripe Checkout; once the server is on Pro the same command opens the billing portal instead. | jevmod/adapters/discord_bot.py:326; jevmod/api/billing.py:81; jevmod/api/billing.py:101 | name="upgrade"; checkout.Session; billing_portal | yes |
| C31c | / | Today that command answers that there is nothing to pay, because no Stripe keys are set on the server. | jevmod/adapters/discord_bot.py:331; PRODUCT.md:76 | nothing to pay; Needed from Omar | yes |
| C32 | / | Price: $0 free, $3.99 per server per month for Pro and not on sale yet, $0 to run it yourself plus what you pay TypeSafe. | PRODUCT.md:71; PRODUCT.md:76 | 3.99; Needed from Omar | yes |
| C32b | / | Cancel any time in Stripe's billing portal. Once a server is on Pro, /mod upgrade opens that portal. | jevmod/api/billing.py:101; jevmod/api/billing.py:79 | billing_portal; portal | yes |
| C33 | / | Judged messages a month: 5,000 free, 50,000 Pro, no limit with your own key. | .env.example:40; .env.example:40 | 5000; 50000 | yes |
| C34 | / | Where the data lives: jevmod's server, 30 days; your machine if you run it yourself. | jevmod/core/store.py:32 | retention_days | yes |
| C35 | / | Messages under eight letters without a link, and messages from trusted authors, are settled locally and do not count. | jevmod/judge.py:95; jevmod/judge.py:88 | letters < min_chars; trusted author | yes |
| C35b | / | A repeat of text the bot judged before with the same channel topic and the same categories on does not count either. That cache lives in the running bot's memory, holds an answer for 24 hours, and is empty again after a restart. | jevmod/judge.py:188; jevmod/judge.py:101; jevmod/judge.py:109 | topic; 86400; self.cache | yes |
| C36 | / | For each flagged message the hosted bot writes one row and keeps it 30 days: a timestamp, the server, a request id, the message id, the author id, the first 80 characters of the channel topic, the category, its probability, the action taken, and the probability of every category asked. | jevmod/core/store.py:257; jevmod/core/store.py:264; jevmod/core/store.py:32 | INSERT INTO decisions; channel_topic; retention_days | yes |
| C36b | / | The row has a text column too, and the hosted bot leaves it empty. | deploy/demo/docker-compose.traefik.yml:46; jevmod/core/store.py:269 | JEVMOD_KEEP_TEXT_CHARS; keep_text_chars | yes |
| C37 | / | Messages that pass are not kept. | jevmod/core/service.py:77 | log_decision | yes |
| C38 | / | /mod forget deletes everything stored about your server, and so does kicking the bot. | jevmod/adapters/discord_bot.py:354; jevmod/adapters/discord_bot.py:213 | delete_tenant; forget everything | yes |
| C38b | / | Neither one touches Stripe. Cancel a Pro subscription in the billing portal first, or it keeps charging. | jevmod/core/store.py:297; jevmod/api/billing.py:101 | delete_tenant; billing_portal | yes |
| C38c | / | The hosted bot is not open yet, so the way to use jevmod today is to run the container in your own Discord server. | PRODUCT.md:76; README.md:218 | Needed from Omar; SQLite on a volume | yes |

## Claims on /developers/

| id | page | sentence | source | token | verified |
|---|---|---|---|---|---|
| C40 | /developers/ | Python, npm, CLI, HTTP, MCP and three bots over one core. MIT. | README.md:218; LICENSE:1 | discord; MIT | yes |
| C41 | /developers/ | Real output: the CLI on four messages, then one HTTP call. | docs/jevmod.gif | | yes |
| C42 | /developers/ | Every check returns all enabled categories at once, in one request. Messages under eight letters without a link and messages from trusted authors are never sent. Text already judged by the same process is answered from a cache that lives in memory and expires after 24 hours; its key is the text, the channel topic and the enabled categories. | jevmod/judge.py:85; jevmod/judge.py:101; jevmod/judge.py:186 | min_chars; cache_ttl_s: int = 86400; def _key | yes |
| C43 | /developers/ | Up to 50 messages in, one decision each out. The X-Request-Id you send comes back as request_id and as a response header. | jevmod/api/server.py:48; jevmod/api/server.py:125 | max_length=50; X-Request-Id | yes |
| C44 | /developers/ | Admin only. Mints the tenant key for this jevmod server, the jm_ bearer token the other endpoints ask for, and stores only its hash. It is not the TypeSafe key: the server still needs TYPESAFE_API_KEY to reach the model. | jevmod/api/server.py:82; jevmod/keys.py:14 | sha256; TYPESAFE_API_KEY | yes |
| C45 | /developers/ | A static copy of the OpenAPI document and a Postman collection are on this site. | docs/openapi.json; docs/jevmod.postman_collection.json | | yes |
| C46 | /developers/ | Only the message text and the channel topic are sent to Jev. Author names and ids stay local. | jevmod/judge.py:141 | no author names | yes |
| C47 | /developers/ | Text is NFKC-normalised and stripped of combining marks before judging and caching, so fullwidth, zalgo and zero-width tricks meet the same thresholds as plain text. | jevmod/judge.py:54; jevmod/judge.py:56 | NFKC; combining | yes |
| C48 | /developers/ | Tested on 2,531 public messages with human labels. | BENCHMARK.md:3 | 2,531 | yes |
| C49 | /developers/ | 0.93 harassment, AUROC on the 1,680 OpenAI eval messages. | benchmark/results/report.md:4 | 0.930 | yes |
| C50 | /developers/ | 0.98 sexual content, AUROC on the 1,680 OpenAI eval messages. | benchmark/results/report.md:10 | 0.982 | yes |
| C51 | /developers/ | 0.99 self-harm, AUROC on the 1,680 OpenAI eval messages. | benchmark/results/report.md:14 | 0.992 | yes |
| C52 | /developers/ | 0.98 minors, AUROC on the 1,680 OpenAI eval messages. | benchmark/results/report.md:8 | 0.977 | yes |
| C53 | /developers/ | Same 2,531 messages for all four systems: 1,680 from OpenAI's moderation eval, 351 from Civil Comments, 500 from the YouTube spam collection. Thresholds are each system's defaults; nobody was tuned on this data. | BENCHMARK.md:23; BENCHMARK.md:24; BENCHMARK.md:25; BENCHMARK.md:30 | 1,680; 351; 500; default threshold | yes |
| C54 | /developers/ | The table: AUROC and F1 at each system's default threshold, nine rows of measured values for four systems. | benchmark/results/report.md:2 | F1@default | yes |
| C55 | /developers/ | Where it loses: toxic-bert wins Civil Comments because it was trained on Civil Comments. On text it has not seen, OpenAI's set, it is the weakest of the four. | BENCHMARK.md:74 | trained on Civil Comments | yes |
| C56 | /developers/ | Llama Guard only gives a probability for unsafe at all; its per-category numbers use that probability when it named the category and 0 otherwise, which under-reports it. Quantised weights may cost both open models a little against fp16. | BENCHMARK.md:34; BENCHMARK.md:118 | unsafe at all; quantised | yes |
| C57 | /developers/ | Above 0.9 the probabilities match observed rates within a few points; between 0.5 and 0.85 they run high, which is why the shipped thresholds sit mostly at 0.75 to 0.85 (minors 0.70, off-topic 0.90). A 0.6 is a maybe, not a 60%. | BENCHMARK.md:108; BENCHMARK.md:111 | above 0.9; 0.75 to 0.85 | yes |
| C58 | /developers/ | $0.042 per 1,000 judged messages: 2.5 M input tokens for 2,504 messages at $0.042 per million. | BENCHMARK.md:84 | 0.042 | yes |
| C59 | /developers/ | 1,005 input tokens per message with seven categories on, measured. | BENCHMARK.md:91 | 1,005 | yes |
| C60 | /developers/ | 22 ms per message, amortised in batches of 25, about 550 ms per request. | BENCHMARK.md:84 | 22 ms | yes |
| C61 | /developers/ | Messages that reach Jev. jevmod never sends messages under eight letters without a link or messages from trusted authors, and text the same process judged in the last 24 hours is answered from memory, so your bill is for a subset of traffic. | jevmod/judge.py:85; jevmod/judge.py:88; jevmod/judge.py:101 | min_chars; trusted author; cache_ttl_s: int = 86400 | yes |
| C62 | /developers/ | $0.30 is the benchmark's assumption for a consumer-class card. | BENCHMARK.md:85 | $0.30/h | yes |
| C63 | /developers/ | Constants: 1,005 input tokens per judged message and 49 ms per message for Llama Guard, measured on 2,531 messages (RTX 5080); Jev $0.042 and Claude Haiku 4.5 $1.00 per million input tokens at list price; the 1.2 factor is prompt overhead. | docs/site.js:59; BENCHMARK.md:85; BENCHMARK.md:92 | TOK = 1005; 49 ms; per million input tokens | yes |
| C64 | /developers/ | Roles: api, demo, hosted, discord, telegram, reddit. demo serves the try-it endpoint of this site and hosted serves the billing webhook and the admin panel. SQLite on a volume. A $4/month VM, Fly.io or Railway with a volume is enough. | jevmod/__main__.py:59; jevmod/api/hosted.py:2; README.md:225 | hosted; operator panel; $4/month | yes |
| C65 | /developers/ | Fails open: if Jev is unreachable, decisions come back with reason="error_open" and nothing is acted on. The failure is logged. | jevmod/core/service.py:68; jevmod/core/service.py:63 | error_open; log.warning | yes |
| C66 | /developers/ | JEVMOD_MONTHLY_QUOTA is 0 by default, unlimited. Set it and judging pauses for a tenant after that many judged messages in a month, and nothing is deleted while it is paused. Every decision comes back with reason quota, and the Discord and Telegram bots post one notice the first time it happens in a month. | jevmod/core/store.py:18; jevmod/core/service.py:54; jevmod/adapters/discord_bot.py:173 | JEVMOD_MONTHLY_QUOTA; quota; note_quota_hit | yes |
| C67 | /developers/ | JEVMOD_KEEP_TEXT_CHARS is how many characters of a flagged message the decision log keeps, 300 by default. 0 stores no text at all. Rows older than 30 days are purged on every batch. | jevmod/core/store.py:40; jevmod/core/store.py:32 | JEVMOD_KEEP_TEXT_CHARS; retention_days | yes |
| C68 | /developers/ | jevmod, MIT. An independent project by Omar Hernandez, not affiliated with TypeSafe, Discord, Telegram or Reddit. | DISCLAIMER.md:16; LICENSE:1 | affiliation; MIT | yes |
| C157 | /developers/ | Everything below needs a TypeSafe API key from console.typesafe.ai. jevmod init stores it in the operating system keyring; TYPESAFE_API_KEY in the environment wins over the keyring and is all the npm package reads. Without a key jevmod check prints one error line and exits 2, and the Python and npm calls raise. | jevmod/keys.py:14; jevmod/cli.py:100; packages/jevmod-js/src/judge.ts:42 | TYPESAFE_API_KEY; exit 2; TYPESAFE_API_KEY | yes |
| C158 | /developers/ | Seven paths, eight operations. | jevmod/api/server.py:145; jevmod/api/server.py:150; jevmod/api/server.py:181 | app.get("/v1/policy; app.put("/v1/policy; /v1/keys | yes |
| C159 | /developers/ | Where it loses at the shipped thresholds: Llama Guard 3 has the better F1 on OpenAI self-harm, 0.825 against 0.714, and on any violation, 0.787 against 0.762. | BENCHMARK.md:49; BENCHMARK.md:53 | 0.825; 0.787 | yes |
| C160 | /developers/ | The four figures below come from one of the three sets: the 1,680 messages of OpenAI's moderation eval. The other 851 messages are in the table further down. | BENCHMARK.md:23; BENCHMARK.md:24 | 1,680; 351 | yes |
| C161 | /developers/ | Recall at the thresholds the bots ship with: harassment 0.78, nsfw 0.89, self-harm 0.59, minors 0.41, YouTube spam 0.36. | benchmark/results/report.md:4; benchmark/results/report.md:14; benchmark/results/report.md:28 | 0.78; 0.59; 0.36 | yes |
| C162 | /developers/ | Self-harm ranks at 0.992 and still misses two of every five labelled cases at its threshold of 0.80. | benchmark/results/report.md:14; jevmod/core/policy.py:17 | 0.992; selfharm | yes |
| C163 | /developers/ | Measured categories: harassment, nsfw, self-harm, minors and spam. scam, doxxing and offtopic have no benchmark rows. ai_generated was measured in a separate run on 520 texts. | benchmark/results/report.md:2; benchmark/ai_detect/REPORT.md:3 | category; 520 texts | yes |
| C164 | /developers/ | A drawing of the /admin panel layout, not a capture. The panel belongs to the hosted role, not to api, and it needs JEVMOD_ADMIN_TOKEN. | docs/img/admin-panel.svg; jevmod/api/hosted.py:14; jevmod/api/billing.py:149 | ; make_router; JEVMOD_ADMIN_TOKEN | yes |

## Claims on /privacy/

| id | page | sentence | source | token | verified |
|---|---|---|---|---|---|
| C80 | /privacy/ | For each message it judges, the bot sends the message text and the topic of the channel to Jev, the model run by TypeSafe. | jevmod/judge.py:144 | channel_topic | yes |
| C81 | /privacy/ | It does not send the author's name, the author's id or the server's name. Messages are numbered by position inside the request and nothing else identifies them. | jevmod/judge.py:141 | author | yes |
| C82 | /privacy/ | The author's id is kept only in the bot's own log so that erasure requests can be honoured. | jevmod/adapters/discord_bot.py:47 | erasure | yes |
| C83 | /privacy/ | Messages from members who can manage messages, and from roles you mark as trusted with /mod trust, are never sent to the model. | jevmod/adapters/discord_bot.py:65 | manage_messages | yes |
| C84 | /privacy/ | The bot writes a record only when a message crosses one of your thresholds and gets an action (flag, delete or time out). | jevmod/core/service.py:76 | action | yes |
| C85 | /privacy/ | A message that passes is not written anywhere. | jevmod/core/service.py:77 | log_decision | yes |
| C86 | /privacy/ | Each stored record holds: the message id, the author id, the first 80 characters of the channel topic, the category, its probability, the action taken, the probability of every category asked, a request id and a timestamp. | jevmod/core/store.py:264 | channel_topic | yes |
| C87 | /privacy/ | The record has a text column, but the hosted bot runs with JEVMOD_KEEP_TEXT_CHARS set to 0, so that column is always empty. | deploy/demo/docker-compose.traefik.yml:46 | JEVMOD_KEEP_TEXT_CHARS | yes |
| C88 | /privacy/ | The store cuts the text to that many characters before writing it, and with 0 nothing of the text is written. | jevmod/core/store.py:269 | keep_text_chars | yes |
| C89 | /privacy/ | A test in the repository checks that setting. | tests/test_offline.py::test_keep_text_chars_env_and_zero | | yes |
| C90 | /privacy/ | Per server and per calendar month the bot also counts judged messages, model requests and tokens, for the quota. | jevmod/core/store.py:51 | judged | yes |
| C91 | /privacy/ | Decision records are kept for 30 days. | jevmod/core/store.py:32 | retention_days | yes |
| C92 | /privacy/ | Older records are deleted before every batch is judged. | jevmod/core/service.py:52 | purge_expired | yes |
| C93 | /privacy/ | Your settings (thresholds, actions, rules, trusted roles, channel topics, the id of the log channel) are stored for as long as the bot is in your server. | jevmod/core/store.py:48 | policy | yes |
| C94 | /privacy/ | Every flagged message is posted to a log channel as an embed that contains the first 500 characters of the message text. | jevmod/adapters/discord_bot.py:124 | content | yes |
| C95 | /privacy/ | That embed also mentions the author and the channel. | jevmod/adapters/discord_bot.py:114 | author | yes |
| C96 | /privacy/ | The log channel is created with the everyone role unable to read it. | jevmod/adapters/discord_bot.py:149 | read_messages | yes |
| C97 | /privacy/ | When a message is deleted or a member is timed out, the member receives a direct message from the bot with the server name, the channel, the category and the confidence, and a note to contact the server's moderators. | jevmod/adapters/discord_bot.py:114 | send | yes |
| C98 | /privacy/ | /mod forget deletes the server's settings, usage counters, decision records, API keys and subscription row. | jevmod/adapters/discord_bot.py:354 | delete_tenant | yes |
| C99 | /privacy/ | /mod forget_user @member deletes that member's decision records and replies with how many were removed. | jevmod/adapters/discord_bot.py:366 | delete_user | yes |
| C100 | /privacy/ | Kicking the bot, or the bot leaving the server, deletes everything stored about that server. | jevmod/adapters/discord_bot.py:214 | delete_tenant | yes |
| C101 | /privacy/ | All /mod commands require the Manage Server permission. | jevmod/adapters/discord_bot.py:220 | manage_guild | yes |
| C102 | /privacy/ | Payment for the Pro plan happens on a Stripe Checkout page opened from /mod upgrade. | jevmod/api/billing.py:73 | checkout | yes |
| C103 | /privacy/ | jevmod stores, per server: the Stripe customer id, the subscription id, the price id, the subscription status and the end of the current period. | jevmod/core/store.py:58 | subscription_id | yes |
| C104 | /privacy/ | Stripe notifies jevmod of changes through a webhook; when a subscription is cancelled or stops being active the server goes back to the Free plan. | jevmod/api/billing.py:135 | free | yes |
| C105 | /privacy/ | Managing or cancelling the subscription happens in Stripe's billing portal, reached through the same /mod upgrade command. | jevmod/api/billing.py:101 | billing_portal | yes |
| C106 | /privacy/ | The demo on the front page accepts up to 300 characters of text. | jevmod/api/demo.py:35 | MAX_CHARS | yes |
| C107 | /privacy/ | Each check is logged by the operator with the text, the category, the probabilities, a hash of your IP address, the country header set by the proxy, and the number of tokens it cost. | jevmod/api/demo.py:57 | ip_hash | yes |
| C108 | /privacy/ | The IP address is hashed with SHA-256 and a salt before it is stored; the address itself is not kept. | jevmod/api/demo.py:107 | sha256 | yes |
| C109 | /privacy/ | Each address may run 6 checks per minute and 40 per day. | jevmod/api/demo.py:34 | PER_DAY | yes |
| C110 | /privacy/ | The demo has a monthly spend cap, $0.50 by default, and answers with an error once it is reached. | jevmod/api/demo.py:32 | BUDGET_USD | yes |
| C111 | /privacy/ | A self-hosted Umami instance at analytics.hernandezbastos.es counts page views; it does not use cookies. | docs/privacy/index.html:23 | analytics.hernandezbastos.es | yes |
| C124 | /privacy/ | Demo records are deleted 90 days after they are written; the deletion runs when the demo is used. | jevmod/api/demo.py:39; jevmod/api/demo.py:125 | DEMO_RETENTION_DAYS; purge_expired | yes |
| C125 | /privacy/ | The invite link asks for those eight permissions and no others. | PRODUCT.md:80; docs/index.html:40 | 1099511721040 | yes |
| C112 | /privacy/ | A self-hosted copy keeps up to 300 characters of each flagged message by default; set JEVMOD_KEEP_TEXT_CHARS=0 to keep none. | jevmod/core/store.py:40 | JEVMOD_KEEP_TEXT_CHARS | yes |
| C113 | /privacy/ | View Channels: to receive the messages it judges. | jevmod/adapters/discord_bot.py:78 | on_message | yes |
| C114 | /privacy/ | Send Messages: to post decisions in the log channel. | jevmod/adapters/discord_bot.py:114 | send | yes |
| C115 | /privacy/ | Manage Channels: to create the private #jevmod-log channel the first time it needs it. | jevmod/adapters/discord_bot.py:165 | create_text_channel | yes |
| C116 | /privacy/ | Manage Messages: to delete a message, only when you set a category or rule to delete or timeout. | jevmod/adapters/discord_bot.py:98 | delete | yes |
| C117 | /privacy/ | Moderate Members: to time a member out, only when you set a category or rule to timeout. | jevmod/adapters/discord_bot.py:98 | timeout | yes |
| C118 | /privacy/ | Add Reactions: to add the reactions under each log entry. | jevmod/adapters/discord_bot.py:131 | add_reaction | yes |
| C119 | /privacy/ | Embed Links: the log entry is an embed. | jevmod/adapters/discord_bot.py:122 | Embed | yes |
| C120 | /privacy/ | Read Message History: to fetch the log entry you reacted to, so it can adjust the threshold. | jevmod/adapters/discord_bot.py:200 | fetch_message | yes |
| C121 | /privacy/ | Message Content intent: without it Discord does not deliver message text to bots. | jevmod/adapters/discord_bot.py:25 | message_content | yes |
| C122 | /privacy/ | If a permission is missing, the bot records "missing permissions to act" in the log entry and does nothing else. | jevmod/adapters/discord_bot.py:110 | missing permissions | yes |
| C123 | /privacy/ | The bot has no code path that bans anyone; the only actions it knows are off, flag, delete and timeout. | jevmod/core/policy.py:10 | ACTIONS | yes |
| C165 | /privacy/ | Nothing can be paid for today: the hosted instance runs without Stripe keys, so /mod upgrade answers that this copy is self-hosted and there is nothing to pay. | jevmod/adapters/discord_bot.py:345; jevmod/adapters/discord_bot.py:331 | STRIPE_PRICE_ID; nothing to pay | yes |
| C166 | /privacy/ | The text you type into the demo is sent to Jev, the model run by TypeSafe, in the same way as a message judged in a server. | jevmod/api/demo.py:142; jevmod/judge.py:144 | judge(); channel_topic | yes |
| C167 | /privacy/ | /mod forget deletes the subscription row in jevmod's database and never calls Stripe, so a subscription that is still live in Stripe keeps being charged. | jevmod/core/store.py:297; jevmod/core/store.py:305 | def delete_tenant; subscriptions | yes |

## Claims on /terms/

| id | page | sentence | source | token | verified |
|---|---|---|---|---|---|
| C130 | /terms/ | jevmod is free software under the MIT License. | LICENSE:1 | MIT | yes |
| C131 | /terms/ | It is provided as is, without warranty of any kind. | LICENSE:15 | AS IS | yes |
| C132 | /terms/ | jevmod is an independent project by Omar Hernandez and is not affiliated with TypeSafe, Discord, Telegram or Reddit. | DISCLAIMER.md:16 | affiliation | yes |
| C133 | /terms/ | By default every category except offtopic is set to flag: the message is reported to your log channel and nothing else happens. | jevmod/core/policy.py:25 | DEFAULT_ACTIONS | yes |
| C134 | /terms/ | The offtopic category is off by default. | jevmod/core/policy.py:30 | offtopic | yes |
| C135 | /terms/ | The bot deletes a message or times a member out only for a category or rule you have set to delete or timeout with /mod set or /mod rule. | jevmod/adapters/discord_bot.py:240 | timeout | yes |
| C136 | /terms/ | A time out lasts 10 minutes. | jevmod/core/policy.py:47 | timeout_minutes | yes |
| C137 | /terms/ | The bot never bans anyone: its only actions are off, flag, delete and timeout. | jevmod/core/policy.py:10 | ACTIONS | yes |
| C138 | /terms/ | Thresholds go from 0.50 to 0.99. | jevmod/core/policy.py:168 | 0.99 | yes |
| C139 | /terms/ | You can add up to 5 rules in your own words. | jevmod/core/policy.py:77 | custom rules | yes |
| C140 | /terms/ | Decisions are probabilities from a machine-learning model compared with thresholds you set; there will be false positives and false negatives. | DISCLAIMER.md:6 | Probabilistic | yes |
| C141 | /terms/ | You are responsible for the actions you enable, for the rules you write, for telling your members that automated moderation is in use, and for complying with the law that applies to your community. | DISCLAIMER.md:9 | responsible | yes |
| C142 | /terms/ | The Free plan covers 5,000 judged messages per server per month. | .env.example:40 | 5000 | yes |
| C143 | /terms/ | The Pro plan costs $3.99 per server per month. | PRODUCT.md:71 | 3.99 | yes |
| C144 | /terms/ | Pro covers 50,000 judged messages per server per month. | .env.example:40 | 50000 | yes |
| C145 | /terms/ | Judged means sent to the model: the counter grows only by messages the model receives, so messages skipped by the local filters or answered from the cache do not count. | jevmod/core/service.py:70 | judged_messages | yes |
| C146 | /terms/ | When a server reaches its quota, judging pauses until the next calendar month and nothing is deleted while paused. | jevmod/adapters/discord_bot.py:179 | Nothing is deleted | yes |
| C147 | /terms/ | The bot posts one notice in the log channel the first time the quota is reached in a month, and /mod status shows the count at any time. | tests/test_offline.py::test_the_quota_notice_reaches_the_adapter; jevmod/adapters/discord_bot.py:173; jevmod/adapters/discord_bot.py:224 | ; note_quota_hit; name="status" | yes |
| C148 | /terms/ | If it opens, Pro is a monthly subscription paid through Stripe Checkout, one price per server, started with /mod upgrade. | jevmod/api/billing.py:82 | subscription | yes |
| C149 | /terms/ | Once a subscription exists you can cancel it at any time from Stripe's billing portal, reached with the same /mod upgrade command. | jevmod/api/billing.py:101 | billing_portal | yes |
| C150 | /terms/ | When the subscription ends the server returns to the Free plan. | jevmod/api/billing.py:135 | free | yes |
| C151 | /terms/ | A period already paid is not refunded, except by writing to the operator through the contact below; refunds are handled by hand. | PRODUCT.md:82 | refunds are manual | yes |
| C152 | /terms/ | There is no service level agreement; jevmod is not the right tool if you need one. | DISCLAIMER.md:24 | SLA | yes |
| C153 | /terms/ | If the model cannot be reached, the bot takes no action on that batch of messages and lets them through. | jevmod/core/service.py:68 | error_open | yes |
| C155 | /terms/ | The selfharm category exists to alert moderators so a person can reach out. It is not a medical or crisis service and must not be used as one. | DISCLAIMER.md:19 | reach out | yes |
| C156 | /terms/ | It is flag-only by design in the defaults. | jevmod/core/policy.py:22 | flag-only | yes |
| C168 | /terms/ | Pro is not on sale at the moment. The hosted instance runs without Stripe keys, so /mod upgrade answers that this copy is self-hosted and there is nothing to pay. No plan can be bought and no card is charged today. | jevmod/adapters/discord_bot.py:345; jevmod/adapters/discord_bot.py:331 | STRIPE_PRICE_ID; nothing to pay | yes |
| C169 | /thanks.html | Stripe sends jevmod a webhook when the payment clears, and the server moves to Pro when that webhook arrives. /mod status shows the new limit. /mod upgrade opens Stripe's billing portal. | jevmod/api/billing.py:104; jevmod/adapters/discord_bot.py:224; jevmod/api/billing.py:101 | stripe/webhook; name="status"; billing_portal | yes |
