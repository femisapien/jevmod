// Real Jev calls through the public Moderator API. Skipped without TYPESAFE_API_KEY; never mocked.
import { describe, expect, it } from "vitest";
import { Moderator, Policy } from "../src/index.js";

const HAS_KEY = Boolean(process.env["TYPESAFE_API_KEY"]);

describe.skipIf(!HAS_KEY)("Moderator against the real Jev API", () => {
  it("check() returns a Decision shaped like the Python to_dict()", async () => {
    const mod = new Moderator();
    const d = await mod.check("FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro", { channelTopic: "gaming" });
    expect(Object.keys(d).sort()).toEqual(["action", "category", "judged", "message_id", "policy_version", "probability", "reason", "scores"]);
    expect(d.message_id).toBe("0");
    expect(d.judged).toBe(true);
    expect(d.reason).toBe("jev");
    expect(d.action).toBe("flag");
    expect(d.category).toBe("scam");
    expect(d.probability).toBeGreaterThanOrEqual(0.75);
    expect(Object.keys(d.scores).sort()).toEqual(["doxxing", "harassment", "minors", "nsfw", "scam", "selfharm", "spam"]);
    for (const p of Object.values(d.scores)) expect(p).toBe(Math.round(p * 1e4) / 1e4);
  });

  it("checkMany() judges the batch in one request and honours ids and trusted authors", async () => {
    const mod = new Moderator();
    const ds = await mod.checkMany(
      ["Anyone know if the patch fixed the inventory bug?", "lol", "you're a worthless idiot and everyone here hates you, just leave"],
      { ids: ["a", "b", "c"], channelTopic: "gaming" },
    );
    expect(mod.judge.requests).toBe(1);
    expect(ds.map((d) => d.message_id)).toEqual(["a", "b", "c"]);
    expect(ds[0]?.action).toBe("none");
    expect(ds[1]).toMatchObject({ action: "none", judged: false, reason: "too short" });
    expect(ds[2]).toMatchObject({ action: "flag", category: "harassment" });
    const trusted = await mod.checkMany(["you're a worthless idiot and everyone here hates you"], { authorTrusted: true });
    expect(trusted[0]).toMatchObject({ action: "none", judged: false, reason: "trusted author" });
    expect(mod.judge.requests).toBe(1);
  });

  it("a custom rule from the Policy wins as rule:<name> with its own action", async () => {
    const policy = new Policy();
    policy.setRule("no_politics", "No political discussion. Game news is fine.", "delete", 0.7);
    const mod = new Moderator({ policy, apiKey: process.env["TYPESAFE_API_KEY"] as string });
    const d = await mod.check("Who are you all voting for in the election next month? The left is destroying this country.");
    expect(d.category).toBe("rule:no_politics");
    expect(d.action).toBe("delete");
    expect(d.scores["rule:no_politics"]).toBeGreaterThanOrEqual(0.7);
  });
});
