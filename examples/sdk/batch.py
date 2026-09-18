"""Judge many messages cheaply: 50 per request, the pre-filter skips trivial ones, the cache skips repeats."""

from jevmod import Moderator

mod = Moderator()
messages = [
    "gg everyone, that raid was clean. same time tomorrow?",
    "ok",  # too short: never sent to Jev
    "DM me for cheap accounts, paypal only, no refunds",
    "gg everyone, that raid was clean. same time tomorrow?",  # repeat: same request, judged once
    "anyone selling a spare key for the expansion?",
]

for i in range(0, len(messages), 50):
    batch = messages[i : i + 50]
    for text, d in zip(batch, mod.check_many(batch), strict=True):
        verdict = f"{d.category} {d.probability:.2f}" if d.action != "none" else "ok"
        print(f"{verdict:<18} judged={d.judged!s:<5} reason={d.reason:<10} {text[:50]!r}")

j = mod.judge
print(f"{j.judged_messages} messages judged in {j.requests} request(s), {j.input_tokens} input tokens")
