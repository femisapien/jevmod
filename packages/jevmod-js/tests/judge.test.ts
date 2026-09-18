// Real Jev calls on realistic messages: the same samples and expectations as tests/test_judge.py in the
// Python package. Skipped without TYPESAFE_API_KEY; never mocked.
import { describe, expect, it } from "vitest";
import { CATEGORY_NAMES, Judge, type Message } from "../src/index.js";

const HAS_KEY = Boolean(process.env["TYPESAFE_API_KEY"]);

// (id, text, expected category with p>=0.7, or null for clean)
const SAMPLES: Array<[string, string, string | null]> = [
  ["1", "🔥 FREE NITRO for the first 100 people!! claim at discord-gifts.ru/nitro 🔥", "scam"],
  ["2", "Anyone know if the new patch fixed the inventory bug? Mine still duplicates items.", null],
  ["3", "DM me if you want to double your ETH in 24h, guaranteed, I work with Binance support", "scam"],
  ["4", "Check out my server!! Best giveaways!! discord.gg/xxxx join join join", "spam"],
  ["5", "you're a worthless idiot and everyone here hates you, just leave", "harassment"],
  ["6", "gg everyone, that raid was clean. same time tomorrow?", null],
  ["7", "lol", null], // prefilter: too short
  ["8", "Hi all, I'm new here, where do I find the rules?", null],
  ["9", "I don't want to be here anymore. nobody would notice if I was gone. sorry everyone", "selfharm"],
  ["10", "this boss fight makes me want to die lol, 40 tries", null],
  ["11", "lol his real name is Marcos Pereira, lives at Calle Colón 14 in Valencia, phone 612 33 44 55", "doxxing"],
  ["12", "hey you said you're 13? you seem mature, add me on snap, don't tell your parents, I'll send you gifts", "minors"],
  ["13", "my daughter is 12 and loves this game, any tips on parental controls?", null],
];

describe.skipIf(!HAS_KEY)("Judge against the real Jev API", () => {
  it("scores the realistic samples in one request", async () => {
    const j = new Judge();
    const msgs: Message[] = SAMPLES.map(([id, text]) => ({ id, text, channelTopic: "gaming community general chat" }));
    const verdicts = await j.judge(msgs, CATEGORY_NAMES);
    expect(j.requests).toBe(1); // one Jev request for the whole batch
    const byId = new Map(verdicts.map((v) => [v.messageId, v]));
    for (const [id, text, expected] of SAMPLES) {
      const v = byId.get(id);
      expect(v).toBeDefined();
      if (!v) continue;
      if (id === "7") {
        expect(v.judged).toBe(false);
        expect(v.reason).toBe("too short");
        continue;
      }
      expect(v.judged, `${id}: ${v.reason}`).toBe(true);
      if (expected === null) {
        for (const [c, p] of Object.entries(v.scores)) expect(p, `${text} -> ${c}=${p}`).toBeLessThan(0.5);
      } else {
        expect(v.scores[expected], `${text} -> ${JSON.stringify(v.scores)}`).toBeGreaterThanOrEqual(0.7);
      }
    }
    console.log(`${j.judgedMessages} messages, ${j.inputTokens} tokens, $${((j.inputTokens * 0.042) / 1e6).toFixed(6)}`);
  });

  it("reuses cached verdicts and applies a custom rule", async () => {
    const j = new Judge();
    const rules = { no_politics: "No political discussion in this server." };
    const m: Message[] = [
      { id: "p1", text: "Who are you all voting for in the election next month? The left is destroying this country." },
      { id: "p2", text: "Which GPU should I get for 1440p, the 5070 or wait for the 5080?" },
    ];
    const v1 = await j.judge(m, ["spam"], rules);
    expect(v1[0]?.custom["no_politics"], JSON.stringify(v1.map((x) => x.custom))).toBeGreaterThanOrEqual(0.7);
    expect(v1[1]?.custom["no_politics"], JSON.stringify(v1.map((x) => x.custom))).toBeLessThan(0.4);
    const v2 = await j.judge(m, ["spam"], rules);
    expect(j.requests).toBe(1);
    expect(v2.every((x) => x.reason === "cache")).toBe(true);
    expect(v2[0]?.scores).toEqual(v1[0]?.scores);
    expect(v2[0]?.custom).toEqual(v1[0]?.custom);
  });

  it("does not call Jev when no categories or rules are enabled", async () => {
    const j = new Judge();
    const v = await j.judge([{ id: "x", text: "a perfectly normal sentence here" }], []);
    expect(j.requests).toBe(0);
    expect(v[0]?.judged).toBe(false);
    expect(v[0]?.reason).toBe("no categories enabled");
  });
});
