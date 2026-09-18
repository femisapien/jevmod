// Offline: JevmodClient speaks the HTTP API of jevmod/api/server.py. A recording fetch stands in for the
// server so the paths, headers and bodies can be checked without deploying anything.
import { describe, expect, it } from "vitest";
import { JevmodApiError, JevmodClient } from "../src/index.js";

interface Call {
  url: string;
  init: RequestInit;
}

function fakeFetch(status: number, payload: unknown): { calls: Call[]; fetch: typeof fetch } {
  const calls: Call[] = [];
  const f = (async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} });
    return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  return { calls, fetch: f };
}

describe("JevmodClient", () => {
  it("needs a base url and a key, from options or the environment", () => {
    const savedUrl = process.env["JEVMOD_API_URL"];
    const savedKey = process.env["JEVMOD_API_KEY"];
    delete process.env["JEVMOD_API_URL"];
    delete process.env["JEVMOD_API_KEY"];
    try {
      expect(() => new JevmodClient()).toThrow(/baseUrl/);
      expect(() => new JevmodClient({ baseUrl: "http://localhost:8080" })).toThrow(/apiKey/);
      process.env["JEVMOD_API_URL"] = "http://localhost:8080/";
      process.env["JEVMOD_API_KEY"] = "jm_test";
      expect(new JevmodClient().baseUrl).toBe("http://localhost:8080");
    } finally {
      if (savedUrl === undefined) delete process.env["JEVMOD_API_URL"];
      else process.env["JEVMOD_API_URL"] = savedUrl;
      if (savedKey === undefined) delete process.env["JEVMOD_API_KEY"];
      else process.env["JEVMOD_API_KEY"] = savedKey;
    }
  });

  it("POST /v1/moderate sends bearer auth, ids and the channel topic", async () => {
    const payload = { request_id: "abc", decisions: [], usage: { judged_this_month: 0, jev_requests_this_month: 0, input_tokens_this_month: 0 } };
    const { calls, fetch } = fakeFetch(200, payload);
    const c = new JevmodClient({ baseUrl: "https://mod.example.com/", apiKey: "jm_secret", fetch });
    const res = await c.moderate(["hello there", { id: "x", text: "hi", channel_topic: "support" }], { channelTopic: "gaming", requestId: "req-1" });
    expect(res).toEqual(payload);
    expect(calls).toHaveLength(1);
    const call = calls[0] as Call;
    expect(call.url).toBe("https://mod.example.com/v1/moderate");
    expect(call.init.method).toBe("POST");
    const headers = call.init.headers as Record<string, string>;
    expect(headers["authorization"]).toBe("Bearer jm_secret");
    expect(headers["content-type"]).toBe("application/json");
    expect(headers["x-request-id"]).toBe("req-1");
    expect(JSON.parse(String(call.init.body))).toEqual({
      messages: [
        { id: "0", text: "hello there", channel_topic: "gaming" },
        { id: "x", text: "hi", channel_topic: "support" },
      ],
    });
  });

  it("GET/PUT /v1/policy and GET /v1/decisions use the right verbs and paths", async () => {
    const { calls, fetch } = fakeFetch(200, { thresholds: {}, actions: {}, rules: {}, rule_actions: {}, rule_thresholds: {}, timeout_minutes: 10, version: 1 });
    const c = new JevmodClient({ baseUrl: "http://localhost:8080", apiKey: "jm_x", fetch });
    await c.getPolicy();
    await c.putPolicy({ actions: { scam: "delete" }, thresholds: { scam: 0.7 } });
    await c.decisions(9999);
    await c.health();
    expect(calls.map((k) => [k.init.method, k.url.replace("http://localhost:8080", "")])).toEqual([
      ["GET", "/v1/policy"],
      ["PUT", "/v1/policy"],
      ["GET", "/v1/decisions?limit=500"],
      ["GET", "/v1/health"],
    ]);
    expect(JSON.parse(String(calls[1]?.init.body))).toEqual({ actions: { scam: "delete" }, thresholds: { scam: 0.7 } });
  });

  it("raises JevmodApiError with the status and body on failure, without the key", async () => {
    const { fetch } = fakeFetch(401, { detail: "unknown api key" });
    const c = new JevmodClient({ baseUrl: "http://localhost:8080", apiKey: "jm_secret", fetch });
    const err = await c.getPolicy().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(JevmodApiError);
    const e = err as JevmodApiError;
    expect(e.status).toBe(401);
    expect(e.body).toContain("unknown api key");
    expect(e.message).not.toContain("jm_secret");
    expect(JSON.stringify(c)).not.toContain("jm_secret");
  });
});
