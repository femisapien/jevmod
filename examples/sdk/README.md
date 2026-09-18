# Python SDK

`Moderator` is the stateless entry point: no database, no tenants, one Jev request per `check_many` batch.

```bash
pip install jevmod && jevmod init
python examples/sdk/moderator_basic.py   # one message: action, category, probability, all scores
python examples/sdk/custom_policy.py     # your thresholds, actions and a plain-language rule
python examples/sdk/batch.py             # 50 messages per request, pre-filter and cache in action
```

What to remember:

- `check(text)` and `check_many(texts)` return `Decision`s; `action` is `none`, `flag`, `delete` or `timeout`.
- Defaults are flag-only. `Policy.set_category` and `Policy.set_rule` change that per category or rule.
- Messages under eight letters without a link and repeats of already-judged text never reach Jev.
- `channel_topic` is what turns the `offtopic` category on.
