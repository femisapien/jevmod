// The judgment core, ported from jevmod/judge.py: a batch of messages in, one Jev request, a probability per
// category per message out. Cost controls live here: local pre-filters decide what is worth judging, a cache
// reuses verdicts for repeated text, and only the categories a policy enabled are asked.
//
// Messages go to Jev as a dict keyed by position (`messages.m3.text`), not a list: with a list, probabilities
// leaked between neighbouring positions in multilingual batches. See the Python module for the full findings.
import { createHash } from "node:crypto";
import { TypeSafeClient, noul, type NoulQuestion, type NoulResponse } from "@typesafe-ai/sdk";
import { CATEGORIES, isCategory, type CategoryName } from "./categories.js";
import { normalize, prefilter, type Message } from "./normalize.js";

export type { Message } from "./normalize.js";

export type Scores = Record<string, number>;

export class Verdict {
  constructor(
    public readonly messageId: string,
    /** category -> probability */
    public readonly scores: Scores,
    /** false when a pre-filter skipped Jev */
    public readonly judged: boolean,
    /** why it was skipped, or "cache" / "jev" */
    public readonly reason: string = "",
    /** server-defined rules -> probability */
    public readonly custom: Scores = {},
  ) {}

  top(): [string, number] | null {
    const all: Scores = { ...this.scores, ...this.custom };
    let best: [string, number] | null = null;
    for (const [k, p] of Object.entries(all)) {
      if (best === null || p > best[1]) best = [k, p];
    }
    return best;
  }
}

export interface JudgeOptions {
  /** A configured TypeSafe client. When omitted one is built from `apiKey` or `TYPESAFE_API_KEY`. */
  client?: TypeSafeClient;
  /** TypeSafe API key. Never logged. Falls back to the `TYPESAFE_API_KEY` environment variable. */
  apiKey?: string;
  /** How long a verdict for identical text stays reusable, in seconds. Default one day. */
  cacheTtlS?: number;
  /** Per-attempt request timeout in seconds. Default 20. */
  timeoutS?: number;
}

interface CacheEntry {
  at: number;
  scores: Scores;
  custom: Scores;
}

export class Judge {
  readonly client: TypeSafeClient;
  readonly cache = new Map<string, CacheEntry>();
  readonly cacheTtl: number;
  requests = 0;
  inputTokens = 0;
  judgedMessages = 0;

  constructor(options: JudgeOptions = {}) {
    this.client = options.client ?? makeClient(options);
    this.cacheTtl = options.cacheTtlS ?? 86_400;
  }

  /** One Jev request for every message that passes the pre-filter and is not cached. */
  async judge(
    messages: readonly Message[],
    categories: readonly string[],
    customRules: Readonly<Record<string, string>> = {},
  ): Promise<Verdict[]> {
    const cats = categories.filter(isCategory);
    const out = new Map<string, Verdict>();
    const toJudge: Array<[Message, string]> = [];
    const now = Date.now() / 1000;
    for (const m of messages) {
      const why = prefilter(m);
      if (why) {
        out.set(m.id, new Verdict(m.id, {}, false, why));
        continue;
      }
      const text = normalize(m.text);
      const key = cacheKey(text, m.channelTopic ?? "", cats, customRules);
      const hit = this.cache.get(key);
      if (hit && now - hit.at < this.cacheTtl) {
        out.set(m.id, new Verdict(m.id, { ...hit.scores }, true, "cache", { ...hit.custom }));
        continue;
      }
      toJudge.push([m, text]);
    }

    const ruleNames = Object.keys(customRules);
    if (toJudge.length > 0 && (cats.length > 0 || ruleNames.length > 0)) {
      // only the text and the channel topic reach Jev: no author names, no ids beyond the position
      const stateMessages: Record<string, { text: string; channel_topic: string }> = {};
      toJudge.forEach(([m, text], i) => {
        stateMessages[`m${i}`] = { text, channel_topic: m.channelTopic || "general chat" };
      });
      const state = { messages: stateMessages, custom_rules: { ...customRules } };
      const questions: Record<string, NoulQuestion> = {};
      for (let i = 0; i < toJudge.length; i++) {
        const path = `messages.m${i}`;
        for (const c of cats) {
          const cat = CATEGORIES[c];
          questions[`${c}_${i}`] = noul(cat.instructions.replaceAll("{m}", path), cat.criteria);
        }
        for (const name of ruleNames) {
          const rule = customRules[name] as string;
          questions[`custom__${name}_${i}`] = noul(
            `Does \`${path}.text\` break this community rule: \`custom_rules.${name}\` (${pyRepr(rule)})?`,
            {
              true: "the message does what the rule forbids, as a moderator who wrote it would read it",
              false:
                "the message is ordinary conversation, or the rule does not clearly cover it; " +
                "when the rule lists exceptions, those are allowed",
            },
          );
        }
      }
      const resp = await this.client.systemOne({ state, questions });
      this.requests += 1;
      this.inputTokens += resp.usage?.input_tokens ?? 0;
      this.judgedMessages += toJudge.length;
      toJudge.forEach(([m, text], i) => {
        const scores: Scores = {};
        for (const c of cats) scores[c] = probability(resp.answers[`${c}_${i}`]);
        const custom: Scores = {};
        for (const name of ruleNames) custom[name] = probability(resp.answers[`custom__${name}_${i}`]);
        this.cache.set(cacheKey(text, m.channelTopic ?? "", cats, customRules), { at: now, scores, custom });
        out.set(m.id, new Verdict(m.id, scores, true, "jev", custom));
      });
    } else if (toJudge.length > 0) {
      for (const [m] of toJudge) out.set(m.id, new Verdict(m.id, {}, false, "no categories enabled"));
    }
    return messages.map((m) => out.get(m.id) as Verdict);
  }
}

function makeClient(options: JudgeOptions): TypeSafeClient {
  const timeoutS = options.timeoutS ?? 20;
  return new TypeSafeClient({
    ...(options.apiKey !== undefined ? { apiKey: options.apiKey } : {}),
    timeout: timeoutS * 1000,
    retry: {
      maxRetries: 3,
      backoffInitialMs: 500,
      backoffMaxMs: 8000,
      httpStatuses: new Set([429, 500, 502, 503, 504, 529]),
    },
  });
}

function probability(answer: unknown): number {
  const a = answer as Partial<NoulResponse> | undefined;
  if (!a || a.type !== "noul" || typeof a.noul !== "number") {
    throw new TypeError(`expected a Noul answer, got ${describe(answer)}`);
  }
  return a.noul;
}

function describe(x: unknown): string {
  if (x === null) return "null";
  if (typeof x !== "object") return typeof x;
  const t = (x as { type?: unknown }).type;
  return typeof t === "string" ? `${t} answer` : "object";
}

/** Same key as the Python `_key`: sha256 of `text.lower()|topic|cats,joined|sorted(rules.items())`. */
export function cacheKey(
  text: string,
  topic: string,
  cats: readonly CategoryName[],
  rules: Readonly<Record<string, string>>,
): string {
  const norm = text.toLowerCase();
  const sorted = Object.entries(rules).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const rulesRepr = `[${sorted.map(([k, v]) => `(${pyRepr(k)}, ${pyRepr(v)})`).join(", ")}]`;
  const h = createHash("sha256").update(`${norm}|${topic}|${cats.join(",")}|${rulesRepr}`, "utf8").digest("hex");
  return h.slice(0, 32);
}

/** Python `repr()` of a str: same quoting and escapes, so questions and cache keys match the Python package. */
export function pyRepr(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const cp = ch.codePointAt(0) as number;
    if (ch === "\\") out += "\\\\";
    else if (ch === quote) out += `\\${quote}`;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (cp < 0x20 || cp === 0x7f) out += `\\x${cp.toString(16).padStart(2, "0")}`;
    else out += ch;
  }
  return out + quote;
}
