"""Your thresholds, your actions, your rules. Nothing is deleted unless you say so."""

from jevmod import Moderator, Policy

policy = Policy()
policy.set_category("scam", "delete", threshold=0.7)  # remove scams at 0.7 instead of flagging at 0.75
policy.set_category("offtopic", "flag", threshold=0.9)  # needs a channel_topic to mean anything
policy.set_rule("no_politics", "No political discussion. News about the game itself is fine.", action="flag")

mod = Moderator(policy=policy)
texts = [
    "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro",
    "The left is destroying this country, vote them out next month",
    "Patch 1.4 notes are out, the inventory bug is fixed",
]
for text, d in zip(texts, mod.check_many(texts, channel_topic="a game's patch notes and bugs"), strict=True):
    print(f"{d.action:<7} {d.category or '-':<18} {d.probability:.2f}  {text[:60]!r}")
