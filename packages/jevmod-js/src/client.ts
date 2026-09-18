// Client for a deployed jevmod HTTP API (jevmod/api/server.py): the moderation runs on your server with your
// TypeSafe key; callers only need the per-tenant key minted with `POST /v1/keys`.
import type { PolicyJSON } from "./policy.js";

export interface JevmodClientOptions {
  /** Where the API runs, e.g. `https://mod.example.com`. Falls back to `JEVMOD_API_URL`. */
  baseUrl?: string;
  /** Tenant key (`jm_...`). Never logged. Falls back to `JEVMOD_API_KEY`. */
  apiKey?: string;
  /** Custom fetch, for tests or proxies. Default: global fetch. */
  fetch?: typeof fetch;
  /** Per-request timeout in milliseconds. Default 30000. */
  timeoutMs?: number;
}

export interface ModerateMessage {
  /** Your id for the message; echoed back. */
  id?: string;
  text: string;
  author?: string;
  /** What the channel/thread is about; used by `offtopic`. */
  channel_topic?: string;
  /** True skips judgment (moderators, verified staff). */
  author_trusted?: boolean;
}

/** A decision as the API returns it (no `policy_version`). */
export interface ApiDecision {
  message_id: string;
  action: string;
  category: string | null;
  probability: number;
  scores: Record<string, number>;
  judged: boolean;
  reason: string;
}

export interface ModerateResponse {
  request_id: string;
  decisions: ApiDecision[];
  usage: { judged_this_month: number; jev_requests_this_month: number; input_tokens_this_month: number };
}

export interface PolicyUpdate {
  thresholds?: Record<string, number>;
  actions?: Record<string, string>;
  rules?: Record<string, string>;
  rule_actions?: Record<string, string>;
  timeout_minutes?: number;
}

export interface HealthResponse {
  ok: boolean;
  uptime_s: number;
  categories: string[];
}

export class JevmodApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly method: string,
    public readonly path: string,
    public readonly body: string,
  ) {
    super(`jevmod API ${method} ${path} failed with ${status}${body ? `: ${body.slice(0, 300)}` : ""}`);
    this.name = "JevmodApiError";
  }
}

export class JevmodClient {
  readonly baseUrl: string;
  readonly #apiKey: string;
  readonly #fetch: typeof fetch;
  readonly #timeoutMs: number;

  constructor(options: JevmodClientOptions = {}) {
    const baseUrl = options.baseUrl ?? readEnv("JEVMOD_API_URL");
    if (!baseUrl) throw new Error("JevmodClient needs a baseUrl (or the JEVMOD_API_URL environment variable)");
    const apiKey = options.apiKey ?? readEnv("JEVMOD_API_KEY");
    if (!apiKey) throw new Error("JevmodClient needs an apiKey (or the JEVMOD_API_KEY environment variable)");
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.#apiKey = apiKey;
    this.#fetch = options.fetch ?? globalThis.fetch;
    this.#timeoutMs = options.timeoutMs ?? 30_000;
  }

  /** `POST /v1/moderate`: up to 50 messages per call; strings become `{ id, text }`. */
  async moderate(
    messages: ReadonlyArray<string | ModerateMessage>,
    options: { requestId?: string; channelTopic?: string } = {},
  ): Promise<ModerateResponse> {
    const body = {
      messages: messages.map((m, i) => {
        const msg: ModerateMessage = typeof m === "string" ? { id: String(i), text: m } : { ...m };
        if (options.channelTopic !== undefined && msg.channel_topic === undefined) msg.channel_topic = options.channelTopic;
        return msg;
      }),
    };
    const headers: Record<string, string> = {};
    if (options.requestId) headers["x-request-id"] = options.requestId;
    return this.#request<ModerateResponse>("POST", "/v1/moderate", body, headers);
  }

  /** `GET /v1/policy` */
  getPolicy(): Promise<PolicyJSON> {
    return this.#request<PolicyJSON>("GET", "/v1/policy");
  }

  /** `PUT /v1/policy`: partial update, returns the stored policy. */
  putPolicy(update: PolicyUpdate): Promise<PolicyJSON> {
    return this.#request<PolicyJSON>("PUT", "/v1/policy", update);
  }

  /** `GET /v1/decisions?limit=`: the tenant's recent decisions, newest first. */
  decisions(limit = 50): Promise<Array<Record<string, unknown>>> {
    const n = Math.max(1, Math.min(Math.trunc(limit), 500));
    return this.#request<Array<Record<string, unknown>>>("GET", `/v1/decisions?limit=${n}`);
  }

  /** `GET /v1/health` */
  health(): Promise<HealthResponse> {
    return this.#request<HealthResponse>("GET", "/v1/health");
  }

  /** `DELETE /v1/tenant`: forget this tenant's policy, usage and decision log. */
  forget(): Promise<{ deleted: boolean }> {
    return this.#request<{ deleted: boolean }>("DELETE", "/v1/tenant");
  }

  async #request<T>(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
    const headers: Record<string, string> = {
      accept: "application/json",
      authorization: `Bearer ${this.#apiKey}`,
      ...extraHeaders,
    };
    const init: RequestInit = { method, headers, signal: AbortSignal.timeout(this.#timeoutMs) };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await this.#fetch(`${this.baseUrl}${path}`, init);
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new JevmodApiError(res.status, method, path, text);
    }
    return (await res.json()) as T;
  }
}

function readEnv(name: string): string | undefined {
  const v = typeof process !== "undefined" ? process.env[name] : undefined;
  return v && v.trim() ? v.trim() : undefined;
}
