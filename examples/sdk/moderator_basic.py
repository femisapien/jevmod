"""One message in, one decision out. The key comes from the keyring, TYPESAFE_API_KEY or .env."""

from jevmod import Moderator

mod = Moderator()
d = mod.check("FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro", channel_topic="gaming")

print(d.action, d.category, round(d.probability, 2))  # flag scam 0.97 (probabilities move about 0.03 between runs)
for category, p in sorted(d.scores.items(), key=lambda kv: -kv[1]):
    print(f"  {category:<12} {p:.2f}")
