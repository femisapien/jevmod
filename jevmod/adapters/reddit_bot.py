"""Reddit adapter over the official API (PRAW). Streams new comments AND new submissions of the subreddits
you moderate; `flag` reports the item to the mod queue with the probabilities, `delete` removes it. Runs as
a moderator account.

A submission has a title and, for a text post, a body (`selftext`); a comment only ever has a body. What
gets judged is the title joined with the body (`title\n\nselftext`), never the title alone: a scam or a
slur is exactly as likely to sit in the title as in the text underneath it, and judging only one half would
let the other half through for free. A link post has no `selftext` -- PRAW gives it back as `""` -- so the
join degrades to the title by itself, which is the whole of what there is to judge; there is no fallback to
the linked URL's content, because fetching an arbitrary external page to judge it is a different feature
with its own SSRF and cost questions, not something this adapter's stream loop should do implicitly.

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


def item_text(item) -> str:
    """Comments have `.body`; submissions don't -- PRAW simply has no such attribute on a `Submission`, so
    `getattr(..., None)` is the right way to tell the two apart without an `isinstance` on a PRAW internal
    class. A submission is judged on `title` joined with `selftext` (empty string for a link post, which is
    exactly all there is to judge for one): never the title alone, since either half can carry the thing a
    category exists to catch."""
    body = getattr(item, "body", None)
    if body is not None:
        return body
    return f"{getattr(item, 'title', '')}\n\n{getattr(item, 'selftext', '')}"


def act(item, d) -> None:
    top = ", ".join(f"{c} {p:.2f}" for c, p in sorted(d.scores.items(), key=lambda kv: -kv[1])[:3])
    reason = f"jevmod: {d.category} p={d.probability:.2f} ({top})"[:100]
    try:
        if d.action == "flag":
            item.report(reason)
        elif d.action in ("delete", "timeout"):
            # Timeout removes the comment and stops there. Reddit has no per-comment mute, so this used to
            # map it to a one day ban, which made the promise the rest of the product is built on - that
            # jevmod cannot ban anybody - false on this platform and false in the terms. A ban is a
            # moderator's decision about a person; this only ever acts on a message.
            item.mod.remove(mod_note=reason)
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
    log.info("streaming %s (comments and submissions)", subs)
    # Two independent streams, not one: PRAW has no single call that yields both comments and submissions,
    # and `multi.stream.comments` was the only one this adapter drove until now. `pause_after=0` makes each
    # generator return `None` the moment it has caught up rather than blocking, so both can be polled from
    # the same loop tick by calling `next()` on each in turn -- the same non-blocking shape the old
    # single-stream loop already relied on, just applied twice.
    comments = multi.stream.comments(skip_existing=True, pause_after=0)
    submissions = multi.stream.submissions(skip_existing=True, pause_after=0)
    pending: dict[str, list] = {}
    last_flush = time.time()
    while True:
        got_item = False
        for item in (next(comments, None), next(submissions, None)):
            if item is not None:
                got_item = True
                sub = item.subreddit.display_name
                tenant = tenant_of(sub)
                if service.policy(tenant).active():
                    pending.setdefault(tenant, []).append(item)
        now = time.time()
        if now - last_flush >= BATCH_WINDOW_S and pending:
            for tenant, items in pending.items():
                sub = items[0].subreddit.display_name
                msgs = [
                    Message(
                        id=i.id,
                        text=item_text(i),
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
        if not got_item:
            time.sleep(1)


if __name__ == "__main__":
    run()
