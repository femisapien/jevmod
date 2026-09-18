# Reddit posts (drafts)

Targets, in order: r/Discord_Bots (main), r/selfhosted, r/Python (the package angle), r/opensource. One post per
subreddit, adapted; do not cross-post the same text the same day. Replace LINK with the repo URL once public.

---

## r/Discord_Bots

**Title:** I made an open-source moderation bot that judges messages with probabilities instead of word lists (spam, scam, harassment, nsfw, self-harm, your own rules)

I run a couple of small servers and got tired of two things: word-list bots that miss "fr​ee nitro" with a zero-width space, and LLM bots that cost real money and hallucinate reasons.

jevmod uses Jev (TypeSafe's System One model): you ask it yes/no questions about a message and it returns a probability per question. So every message gets scores like `scam 0.97, spam 0.95, harassment 0.03`, and you decide the threshold and the action per category.

What you get after inviting it:

- A private `#jevmod-log` channel where it flags things. Nothing is deleted until you enable that per category.
- `/mod set scam delete 0.9`, `/mod rule no_politics "No political discussion. Game news is fine."`, `/mod trust @Mods`.
- React ❌ on a wrong flag and the threshold for that category goes up a notch; ✅ lowers it. Two clicks a day calibrates it to your server.
- Self-harm detection that only flags (so a mod can reach out), never deletes or times out.
- A DM to the member when something is removed, saying it was automated and how to appeal.

Cost: about $0.04 per 1,000 judged messages at the API's list price. A busy server with 20k messages a month is under $1. You bring your own TypeSafe key; there is no account with me and no SaaS.

Privacy: only the text and the channel topic are sent to the API, no usernames. The local log keeps 300 characters for 30 days. `/mod forget` wipes everything; kicking the bot does too.

I benchmarked it against Llama Guard 3, ShieldGemma and toxic-bert on 2,531 public messages; on OpenAI's human-labelled moderation set it had the best AUROC in every category (harassment 0.93, sexual 0.98, self-harm 0.99). Table and caveats are in the repo.

Self-host with Docker in one command, or `pip install "jevmod[discord]"`. Telegram and Reddit adapters are in the same package. MIT.

LINK

Happy to answer anything, and if it flags something dumb on your server I want the example.

---

## r/selfhosted

**Title:** jevmod: self-hosted moderation API + bots (Discord/Telegram/Reddit) with probabilities per category, $0.04 per 1k messages

One Docker image, one env var picks the role: `api`, `discord`, `telegram` or `reddit`. SQLite on a volume. The HTTP API takes up to 50 messages per call and returns a decision plus the probability for each of 8 categories and your own plain-language rules. API keys per tenant, hashed; a `/metrics` endpoint for Prometheus; every decision in an audit log you can export or delete.

It is not a local model: judgment comes from TypeSafe's Jev API (you bring the key). What stays on your box is the policy, the keys, the log and the bots. If you want fully offline, Llama Guard 3 on a GPU is the alternative; I benchmarked both in the repo so you can pick.

`docker compose up -d` and a Postman collection to poke it. MIT.

LINK

---

## r/Python

**Title:** jevmod: a moderation SDK that returns calibrated probabilities for spam/scam/harassment/nsfw/self-harm and rules written in English

```python
from jevmod import Moderator
d = Moderator().check("FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro")
d.action, d.category, d.probability   # ('flag', 'scam', 0.97)
d.scores                              # {'spam': 0.95, 'scam': 0.97, 'harassment': 0.03, ...}
```

`check_many()` judges a batch in one request. There is a CLI (`jevmod check -` reads stdin, `--json`, exit codes for scripts), a FastAPI server, an MCP server for agents, and Discord/Telegram/Reddit adapters over the same core. Also an npm package with the same questions.

The interesting engineering bit: the questions are one yes/no `Noul` per category with explicit true/false criteria (TypeSafe's guardrails cookbook pattern), and batching several messages in one request required sending them as a dict keyed by position, because as a list the probabilities leaked between neighbours. That came out of a 98-message adversarial red team that now runs as a regression suite in CI. Tests hit the real API; no mocks.

Benchmark against Llama Guard 3 / ShieldGemma / toxic-bert included. MIT.

LINK
