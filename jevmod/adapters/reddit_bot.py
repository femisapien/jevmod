"""Reddit adapter over the official API (PRAW). Streams new comments and posts of the subreddits you moderate;
`flag` reports the item to the mod queue with the probabilities, `delete` removes it. Runs as a moderator account.

    REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=... REDDIT_USERNAME=... REDDIT_PASSWORD=... REDDIT_SUBREDDITS=sub1,sub2
    TYPESAFE_API_KEY=... python -m jevmod.adapters.reddit_bot

Reddit's API rules apply (OAuth, user agent, 100 requests/min for OAuth clients). This adapter reads the stream and
acts on items only; it never posts content.
"""

from __future__ import annotations

import logging
import os
import time

import praw

from ..core import ModerationService, Store
from ..judge import Message

log = logging.getLogger("jevmod.reddit")
store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
service = ModerationService(store)
BATCH_WINDOW_S = 5.0


def tenant_of(subreddit: str) -> str:
    return f"reddit:{subreddit.lower()}"


def act(item, d) -> None:
    top = ", ".join(f"{c} {p:.2f}" for c, p in sorted(d.scores.items(), key=lambda kv: -kv[1])[:3])
    reason = f"jevmod: {d.category} p={d.probability:.2f} ({top})"[:100]
    try:
        if d.action == "flag":
            item.report(reason)
        elif d.action in ("delete", "timeout"):
            item.mod.remove(mod_note=reason)
            if d.action == "timeout" and getattr(item, "author", None):
                item.subreddit.banned.add(item.author, duration=1, ban_reason=reason[:100], note="jevmod timeout")
    except Exception as exc:
        log.warning("cannot act on %s: %s", item.id, exc)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "jevmod/0.2 moderation bot"),
    )
    subs = [s.strip() for s in os.environ["REDDIT_SUBREDDITS"].split(",") if s.strip()]
    multi = reddit.subreddit("+".join(subs))
    mods = {s: {m.name for m in reddit.subreddit(s).moderator()} for s in subs}
    log.info("streaming %s", subs)
    pending: dict[str, list] = {}
    last_flush = time.time()
    for item in multi.stream.comments(skip_existing=True, pause_after=0):
        now = time.time()
        if item is not None:
            sub = item.subreddit.display_name
            tenant = tenant_of(sub)
            if service.policy(tenant).active():
                pending.setdefault(tenant, []).append(item)
        if now - last_flush >= BATCH_WINDOW_S and pending:
            for tenant, items in pending.items():
                sub = items[0].subreddit.display_name
                msgs = [
                    Message(
                        id=i.id,
                        text=getattr(i, "body", None) or f"{getattr(i, 'title', '')}\n{getattr(i, 'selftext', '')}",
                        author=str(i.author) if i.author else "",
                        channel_topic=store.get_meta(tenant).get("topic", f"r/{sub}"),
                        author_trusted=bool(i.author and i.author.name in mods.get(sub, set())),
                    )
                    for i in items
                ]
                for i, d in zip(items, service.moderate(tenant, msgs), strict=True):
                    if d.action != "none":
                        act(i, d)
            pending = {}
            last_flush = now
        if item is None:
            time.sleep(1)


if __name__ == "__main__":
    run()
