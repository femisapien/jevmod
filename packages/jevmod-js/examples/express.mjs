// Express middleware: moderate a text field on incoming requests.
//
//   cd packages/jevmod-js && npm run build
//   TYPESAFE_API_KEY=... node examples/express.mjs
//   curl -X POST localhost:3000/comments -H 'content-type: application/json' -d '{"text":"DM me to double your ETH"}'
//
// Fails open: if Jev cannot be reached the request goes through and the error is attached to req.moderation,
// so an outage never blocks your users. Log it and decide what to do with it.
import express from "express";
import { Moderator, Policy } from "jevmod";

/**
 * @param {object} [options]
 * @param {string} [options.field="text"]        request body field to moderate
 * @param {string} [options.channelTopic]        what the endpoint is about (enables `offtopic` if the policy turns it on)
 * @param {(req: import("express").Request) => boolean} [options.trusted]  return true to skip judgment (staff, verified users)
 * @param {Moderator} [options.moderator]        a shared Moderator (recommended: one per process, its cache is in memory)
 * @param {Array<"delete"|"timeout"|"flag">} [options.reject=["delete","timeout"]]  actions that end the request with 422
 */
export function jevmod(options = {}) {
  const field = options.field ?? "text";
  const reject = new Set(options.reject ?? ["delete", "timeout"]);
  const mod = options.moderator ?? new Moderator();
  return async function moderate(req, res, next) {
    const text = req.body?.[field];
    if (typeof text !== "string") return next();
    try {
      const decision = await mod.check(text, {
        channelTopic: options.channelTopic,
        authorTrusted: options.trusted ? options.trusted(req) : false,
      });
      req.moderation = decision;
      if (reject.has(decision.action)) {
        return res.status(422).json({ error: "message rejected by moderation", decision });
      }
      return next();
    } catch (err) {
      req.moderation = { action: "none", judged: false, reason: "error_open", error: err?.name ?? "Error" };
      return next();
    }
  };
}

// Demo app
const policy = new Policy();
policy.setCategory("scam", "delete", 0.75);
policy.setRule("no_politics", "No political discussion. Game news is fine.");
const moderator = new Moderator({ policy });

const app = express();
app.use(express.json({ limit: "16kb" }));
app.post(
  "/comments",
  jevmod({ field: "text", channelTopic: "support forum", moderator, trusted: (req) => req.headers["x-staff"] === "1" }),
  (req, res) => {
    // store the comment; keep req.moderation with it for your audit log
    res.json({ ok: true, moderation: req.moderation });
  },
);

if (process.argv[1] && process.argv[1].endsWith("express.mjs")) {
  app.listen(3000, () => console.log("listening on http://localhost:3000  POST /comments {\"text\": ...}"));
}
