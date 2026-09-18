# Twitter/X thread (draft)

Post as a thread; one tweet per block. Attach `docs/jevmod.gif` to tweet 1 and the benchmark table screenshot to
tweet 5. Repo: https://github.com/ohernandezdev/jevmod. Site and live demo: https://jevmod.hernandezbastos.es.

---

**1/**
I built jevmod: open-source moderation for Discord, Telegram, Reddit, or any app with user text.

One call, eight probabilities: spam, scam, harassment, nsfw, off-topic, self-harm, doxxing, minors. Plus rules you write in plain English.

$0.04 per 1,000 messages. MIT. Try it in the browser, no signup:
https://jevmod.hernandezbastos.es

---

**2/**
It runs on Jev, TypeSafe's "System One" model. No text generation: you ask yes/no questions over a message and get probabilities back.

That means you own the threshold. Flag at 0.75, delete at 0.95, or whatever your community tolerates.

---

**3/**
Three ways in:

- Not technical: invite the bot, it flags into a private log channel, tune with /mod
- Developer: pip install jevmod / npm i jevmod / POST /v1/moderate
- Agents: an MCP server and a Claude Code skill, so your coding agent wires it in

---

**4/**
"No politics. Game news is fine."

That is a rule. You type it, Jev judges against it, no regex, no training. Up to 5 per community. React ❌ on a wrong flag and the threshold moves.

---

**5/**
Benchmark on 2,531 public messages (OpenAI moderation eval, Jigsaw, YouTube spam), against Llama Guard 3 8B, ShieldGemma 2B and toxic-bert running locally:

AUROC on OpenAI's set
harassment 0.93 · sexual 0.98 · self-harm 0.99 · minors 0.98

Best in every category it was compared on (self-harm and minors only against Llama Guard, the others lack those labels). Details and caveats in BENCHMARK.md.

---

**6/**
What it does NOT do:

- No accounts, no SaaS. You bring a TypeSafe key.
- Nothing is deleted by default. Flag first, act when you trust it.
- Self-harm is flag-only by design: moderators reach out, the bot never punishes.

---

**7/**
Privacy, in one paragraph: only the message text and the channel topic go to the API. No usernames. The local log keeps 300 characters for 30 days, then deletes. /mod forget wipes a server. Leaving the server wipes it too.

---

**8/**
I red-teamed the judge with 98 adversarial messages (fullwidth unicode, zalgo, Spanish/Portuguese/French/German/Russian/Japanese, prompt injection inside messages). Found a real bug: batching messages as a list leaked probabilities between neighbours. Fixed, and the set now runs as a regression suite in CI.

---

**9/**
Repo, benchmark, Docker image, pip package (npm coming):
https://github.com/ohernandezdev/jevmod

Try it live, no signup, nothing installed:
https://jevmod.hernandezbastos.es

If you run a community and try it, I want to hear what it got wrong. That is what the ❌ button is for.
