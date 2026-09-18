# jevmod plugin for Claude Code

Two skills and one MCP server.

- `jevmod-integrate`: add moderation to an existing codebase (pick the surface, wire the key, insert the call, add a real test).
- `jevmod-moderate`: screen text, inputs or datasets from the terminal (`jevmod check`) or through the MCP tools while working.
- `.mcp.json`: registers `jevmod mcp` (stdio). Needs `jevmod` on PATH (`pip install "jevmod[mcp]"`) and `TYPESAFE_API_KEY` in the environment or the OS keyring (`jevmod init`).

Install (the jevmod repository is its own marketplace, see `.claude-plugin/marketplace.json` at the root):

```
/plugin marketplace add ohernandezdev/jevmod
/plugin install jevmod@jevmod
```
