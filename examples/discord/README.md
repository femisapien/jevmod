# Discord

The bot ships with the package. Run it against your own server:

```bash
pip install "jevmod[discord]"
jevmod init                      # stores the TypeSafe key (keyring, or .env)
export DISCORD_TOKEN=...         # Developer Portal -> Bot -> Reset Token, Message Content Intent on
jevmod discord
```

It creates a private `#jevmod-log` channel and flags into it; tune with `/mod` (command table in the root README).

`custom_adapter.py` is the shape of any other chat platform: build `Message`s from your events, call
`ModerationService.moderate(tenant, messages)`, act on `Decision.action`. Policy, quota, audit log and fail-open
come with the service; the adapter only translates events and actions.

```bash
python examples/discord/custom_adapter.py    # runs the adapter once on three sample messages
```
