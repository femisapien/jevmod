# Agent harness

Moderate what goes into an agent's tools and what comes out of the model, with the same `Moderator`.

```bash
pip install jevmod && jevmod init
python examples/agent_harness/guard.py                  # @guarded decorator on a plain function
python examples/agent_harness/claude_agent_sdk_hook.py  # Claude Agent SDK PreToolUse / PostToolUse hooks
python examples/agent_harness/langchain_callback.py     # LangChain callback handler (pip install langchain-core)
```

- `guard.py`: `@guarded` checks every string argument before the call and the return value after it; a hit raises
  `ModerationError` with the category and probability. Works on sync and async functions.
- `claude_agent_sdk_hook.py`: a `PreToolUse` hook that denies tool calls whose inputs trigger moderation and a
  `PostToolUse` hook that annotates flagged tool output. The hook functions are plain dict-in, dict-out and run
  without the SDK installed; `main()` wires them into `ClaudeAgentOptions` (`pip install claude-agent-sdk`).
- `langchain_callback.py`: `JevmodCallback` raises on flagged tool inputs (`on_tool_start`) and flagged model
  output (`on_llm_end`). Attach it with `callbacks=[JevmodCallback()]`.

Everything is flag-only by default; pass a `Policy` with `delete`/`timeout` actions to be stricter, or a rule.
