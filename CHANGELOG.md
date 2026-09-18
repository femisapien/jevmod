# Changelog

## 0.2.1

- `jevmod api` binds `127.0.0.1` by default. 0.2.0 bound `0.0.0.0`, so installing the package and starting the
  API on a machine with a public interface exposed it to the internet. Set `JEVMOD_HOST=0.0.0.0` to expose it on
  purpose; the Docker image does.
- The hosted bot no longer deletes a message when the action is `timeout`. `delete` and `timeout` shared a branch,
  so a category set to time a member out also removed the message.
- The member DM now says what actually happened, a removal or a timeout, instead of always saying removed.
- Edited messages are judged again. Before, a message was judged once and an edit was never looked at.
- The bot gives itself an explicit permission overwrite on the `#jevmod-log` channel it creates. Without it,
  channel overwrites could leave the bot unable to read or post in its own log.
- Billing links refuse to be signed when `JEVMOD_ADMIN_TOKEN` is unset. The key fell back to a constant, so
  anyone could sign a link for any server and open that owner's Stripe portal.
- New category `ai_generated`, experimental and off by default. See `benchmark/ai_detect/REPORT.md` for what it
  can and cannot do.

## 0.2.0

- First public release: Python package, CLI, HTTP API, MCP server, npm package, Discord, Telegram and Reddit bots.
