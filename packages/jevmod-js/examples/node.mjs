// Plain Node example: check one message, check a batch, use your own policy, and talk to a deployed API.
//
//   cd packages/jevmod-js && npm run build
//   TYPESAFE_API_KEY=... node examples/node.mjs
//
// The key is read from the environment by the TypeSafe SDK; it is never printed or written anywhere.
import { JevmodClient, Moderator, Policy } from "jevmod";

const mod = new Moderator(); // TYPESAFE_API_KEY from the environment

// One message
const d = await mod.check("FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro", { channelTopic: "gaming" });
console.log(d.action, d.category, d.probability); // flag scam 0.97
console.log(d.scores); // every probability, for your audit log

// A batch: one Jev request for everything that passes the pre-filter and is not cached
const batch = await mod.checkMany(
  [
    "Anyone know if the patch fixed the inventory bug?",
    "lol", // too short, never sent
    "you're a worthless idiot and everyone here hates you, just leave",
  ],
  { channelTopic: "gaming", ids: ["m1", "m2", "m3"] },
);
for (const x of batch) console.log(x.message_id, x.action, x.category ?? "-", x.reason);
console.log(`${mod.judge.requests} request(s), ${mod.judge.inputTokens} input tokens`);

// Your thresholds, your actions, your rules (max 5)
const policy = new Policy();
policy.setCategory("scam", "delete", 0.7);
policy.setRule("no_politics", "No political discussion. Game news is fine.", "flag", 0.8);
const strict = new Moderator({ policy });
const p = await strict.check("Who are you all voting for? The other side is destroying this country.");
console.log(p.action, p.category); // flag rule:no_politics

// A policy round-trips as JSON, in the same shape the Python package and the HTTP API use
const saved = JSON.stringify(policy);
const restored = Policy.fromJSON(JSON.parse(saved));
console.log(restored.enabledCategories());

// Against a deployed jevmod HTTP API instead of calling Jev directly (needs a tenant key from POST /v1/keys)
if (process.env.JEVMOD_API_URL && process.env.JEVMOD_API_KEY) {
  const api = new JevmodClient(); // JEVMOD_API_URL and JEVMOD_API_KEY from the environment
  const res = await api.moderate(["hello there, where are the rules?", "DM me to double your ETH"], { channelTopic: "gaming" });
  console.log(res.request_id, res.decisions.map((x) => [x.message_id, x.action, x.category]));
  console.log(await api.getPolicy());
}
