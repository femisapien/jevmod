"""Any chat platform on top of ModerationService: translate events in, act on decisions out."""

from jevmod import Message, ModerationService, Store

service = ModerationService(Store("jevmod.sqlite"))  # policy, quota, audit log and fail-open live in here


def on_batch(platform: str, room_id: str, events: list[dict]) -> list[str]:
    """Called by your platform client with a batch of {id, text, author, topic} events. Returns ids to remove."""
    tenant = f"{platform}:{room_id}"  # one policy and one log per room
    msgs = [Message(e["id"], e["text"], author=e["author"], channel_topic=e.get("topic", "")) for e in events]
    removed = []
    for e, d in zip(events, service.moderate(tenant, msgs), strict=True):
        if d.action in ("delete", "timeout"):
            removed.append(e["id"])  # your client deletes it and, for timeout, mutes the author
        elif d.action == "flag":
            print(f"flag {e['id']}: {d.category} {d.probability:.2f}")  # or post it to your mod channel
    return removed


if __name__ == "__main__":
    sample = [
        {"id": "1", "text": "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro", "author": "u1"},
        {"id": "2", "text": "Anyone know if the patch fixed the inventory bug?", "author": "u2"},
        {"id": "3", "text": "ok", "author": "u3"},
    ]
    print("removed:", on_batch("matrix", "!room:example.org", sample))
