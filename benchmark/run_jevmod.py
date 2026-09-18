"""jevmod over items.jsonl: every category, batches of 25, one Jev request per batch. Writes results/jevmod.jsonl
with the raw probabilities and the token count, so cost is measured, not estimated. Resumable."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jevmod.judge import CATEGORIES, Judge, Message  # noqa: E402

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "results" / "jevmod.jsonl"
CATS = [c for c in CATEGORIES if c != "offtopic"]
BATCH = 25


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    done = {json.loads(l)["id"] for l in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    items = [json.loads(l) for l in (DATA / "items.jsonl").open(encoding="utf-8")]
    todo = [it for it in items if it["id"] not in done]
    print(f"{len(todo)} to judge ({len(done)} done)")
    j = Judge()
    t0 = time.time()
    with OUT.open("a", encoding="utf-8") as f:
        for i in range(0, len(todo), BATCH):
            chunk = todo[i : i + BATCH]
            msgs = [Message(it["id"], it["text"][:4000]) for it in chunk]
            tok0, t1 = j.input_tokens, time.perf_counter()
            verdicts = j.judge(msgs, CATS)
            ms = int((time.perf_counter() - t1) * 1000)
            toks = j.input_tokens - tok0
            for it, v in zip(chunk, verdicts, strict=True):
                f.write(
                    json.dumps(
                        {
                            "id": it["id"],
                            "judged": v.judged,
                            "reason": v.reason,
                            "scores": v.scores,
                            "batch_tokens": toks,
                            "batch_ms": ms,
                            "batch_n": len(chunk),
                        }
                    )
                    + "\n"
                )
            f.flush()
            print(f"{i + len(chunk)}/{len(todo)}  {toks} tok  {ms} ms", end="\r")
    print(
        f"\n{j.judged_messages} judged, {j.input_tokens} tokens, ${j.input_tokens * 0.042 / 1e6:.4f}, {time.time() - t0:.0f}s"
    )


if __name__ == "__main__":
    main()
