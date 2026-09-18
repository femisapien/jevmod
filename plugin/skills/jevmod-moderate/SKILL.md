---
name: jevmod-moderate
description: Use when text, user inputs, a dataset, a file of comments or an agent's own output must be screened for spam, scams, harassment, adult content, self-harm, doxxing, sexualised minors, off-topic content or a plain-language rule while working, without adding code to a project. Runs `jevmod check` (exit codes, --json) or the jevmod MCP tools (moderate, categories). To wire moderation into a codebase, use jevmod-integrate instead.
---

# jevmod-moderate

Screen text from the terminal or through the MCP tools. Needs `jevmod` on PATH (`pip install
jevmod`; `pip install "jevmod[mcp]"` for the MCP server) and `TYPESAFE_API_KEY` in the environment, the OS keyring (`jevmod init`) or `.env`.

## CLI

```
jevmod check "one message"                                # one message, human-readable line
jevmod check - < comments.txt                             # one message per line, one Jev request per 50
cat rows.txt | jevmod check --json -                      # one JSON object per line
jevmod check --topic "product support" -- "..."           # enables the offtopic check against that topic
jevmod check --rule "No politics. Game news is fine." --rule "English only" -- "..."   # up to 5 rules
jevmod check --threshold 0.9 -- "..."                     # one threshold for every category (0.5-0.99)
```

Exit codes: `0` nothing triggered, `1` at least one message triggered an action, `2` error (bad
key, network, empty input). Errors go to stderr as one line: `error: <Type>: <message>`.

Human output, one line per message:

```
scam 0.97                    'FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro'  [scam 0.97, spam 0.95, harassment 0.03]
ok                           'Anyone know if the patch fixed the inventory bug?'  [spam 0.02, scam 0.01, harassment 0.02]
skipped (too short)          'lol'  []
```

`--json` output, one object per line:

```json
{"text": "...", "message_id": "0", "action": "flag", "category": "scam", "probability": 0.97,
 "scores": {"spam": 0.95, "scam": 0.97, "harassment": 0.03, "nsfw": 0.01, "selfharm": 0.0, "doxxing": 0.0, "minors": 0.0},
 "judged": true, "reason": "jev", "policy_version": 1}
```

`category` is a category name or `rule:ruleN` (rules given with `--rule` are named `rule1`,
`rule2`, ... in order). `reason` is `jev`, `cache`, or why the message was not judged (`too short`,
`empty`, `trusted author`).

The CLI flags every category at its default threshold (`spam` 0.85, `scam` 0.75, `harassment`
0.75, `nsfw` 0.80, `selfharm` 0.80, `doxxing` 0.80, `minors` 0.70, rules 0.80); `offtopic` (0.90)
only when `--topic` is given. Actions are always `flag` here; the CLI never deletes anything.

## Typical uses

- Screen a dataset before training or publishing: `jevmod check --json - < data.txt > verdicts.jsonl`,
  then filter rows where `action != "none"`. Strip ids and names from the lines first; only text
  should go to Jev.
- Gate user-submitted text in a script or CI job: `jevmod check "$TEXT" || echo "blocked"`
  (exit 1 means blocked, exit 2 means the check did not happen; handle both).
- Check what the agent is about to send or store: pipe the draft through `jevmod check -`.
- Try a rule before wiring it into a product: `jevmod check --rule "..." -` with ten example lines
  that should and should not trigger, and look at the probabilities, not only the verdict.

## MCP tools

When the `jevmod` MCP server is connected (this plugin registers `jevmod mcp`), the same judgment
is available as tools:

- `moderate(texts: list[str], channel_topic: str = "", rules: dict[str, str] | None = None)`:
  one decision per text (up to 50), in order, with every probability; actions are only `none` or
  `flag`. Same defaults as the CLI; `offtopic` only when `channel_topic` is non-empty; `rules` maps a
  name to a plain-language rule (up to 5). Nothing is stored between calls except the 24 h verdict cache.
- `categories()`: the category names, their true/false criteria and the default thresholds, so
  you can explain a verdict or choose which categories matter.

Prefer the CLI for files and batches larger than a few dozen lines (it chunks at 50 per request
and streams output); prefer the MCP tools for a handful of texts inside a conversation.

## Reading the numbers

- Probabilities move about plus or minus 0.03 between runs. A value within that band of a threshold
  will flip; say so instead of reporting it as a firm verdict.
- `judged: false` is not "clean". Messages under 8 letters or digits without a link are skipped.
- A high `selfharm` score means a person may need help; report it to a human, do not treat it like
  spam.
- Read `scores`, not only `category`: a message can be spam 0.95 and scam 0.97; the decision shows
  the most severe action, then the highest probability.
- Cost: about 1,050 input tokens per judged message with all categories on, $0.000045 at Jev's
  list price. Repeated identical text is served from a 24 h cache and costs nothing.

## Do not

- Do not paste the key on the command line or into a file that is committed. `jevmod init` or an
  environment variable.
- Do not send author names, emails or ids inside the text.
- Do not run `jevmod check` on the same file in a loop to "average" results; one pass plus the
  plus or minus 0.03 caveat is the honest answer.
