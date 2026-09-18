"""Llama Guard 3 8B (Q8_0, llama.cpp, local GPU) over items.jsonl. Meta's prompt format, categories S1-S14.
Writes results/llamaguard.jsonl with p(unsafe) from the first-token probability and the categories it names.

Mapping to jevmod: S4→minors, S7→doxxing, S1/S5/S10→harassment, S11→selfharm, S3/S12→nsfw. Llama Guard has no
spam category: on the YouTube set it can only be scored as "unsafe or not".
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from llama_server import Server, first_token_probs

GGUF = r"C:\AI\models\Llama-Guard-3-8B.Q4_K_M.gguf"
DATA = Path(__file__).parent / "data" / "items.jsonl"
OUT = Path(__file__).parent / "results" / "llamaguard.jsonl"

CATS = """S1: Violent Crimes.
S2: Non-Violent Crimes.
S3: Sex Crimes.
S4: Child Exploitation.
S5: Defamation.
S6: Specialized Advice.
S7: Privacy.
S8: Intellectual Property.
S9: Indiscriminate Weapons.
S10: Hate.
S11: Self-Harm.
S12: Sexual Content.
S13: Elections.
S14: Code Interpreter Abuse."""

PROMPT = (
    "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
    "Task: Check if there is unsafe content in 'User' messages in conversations according our safety policy with the "
    "below categories.\n\n<BEGIN UNSAFE CONTENT CATEGORIES>\n{cats}\n<END UNSAFE CONTENT CATEGORIES>\n\n"
    "<BEGIN CONVERSATION>\n\nUser: {text}\n\n<END CONVERSATION>\n\n"
    "Provide your safety assessment for ONLY THE LAST User message in the above conversation:\n"
    " - First line must read 'safe' or 'unsafe'.\n"
    " - If unsafe, a second line must include a comma-separated list of violated categories.<|eot_id|>"
    "<|start_header_id|>assistant<|end_header_id|>\n\n"
)
MAP = {
    "S4": "minors",
    "S7": "doxxing",
    "S1": "harassment",
    "S5": "harassment",
    "S10": "harassment",
    "S11": "selfharm",
    "S3": "nsfw",
    "S12": "nsfw",
}


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    done = {json.loads(line)["id"] for line in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    items = [json.loads(line) for line in DATA.open(encoding="utf-8")]
    todo = [it for it in items if it["id"] not in done]
    print(f"{len(todo)} to judge")
    srv = Server(GGUF, 8791)
    t0 = time.time()
    try:
        with OUT.open("a", encoding="utf-8") as f:
            for i, it in enumerate(todo):
                t1 = time.perf_counter()
                resp = srv.complete(PROMPT.format(cats=CATS, text=it["text"][:3000]), n_predict=24)
                ms = int((time.perf_counter() - t1) * 1000)
                text = resp.get("content", "").strip()
                probs = first_token_probs(resp)
                p_unsafe = sum(v for k, v in probs.items() if k.strip().lower().startswith("unsafe"))
                p_safe = sum(v for k, v in probs.items() if k.strip().lower() == "safe")
                if p_unsafe == 0 and p_safe == 0:
                    p_unsafe = 1.0 if text.lower().startswith("unsafe") else 0.0
                cats = [c.strip() for c in text.split("\n")[1].split(",")] if "\n" in text else []
                f.write(
                    json.dumps(
                        {
                            "id": it["id"],
                            "unsafe": text.lower().startswith("unsafe"),
                            "p_unsafe": round(p_unsafe, 4),
                            "cats": cats,
                            "labels": sorted({MAP[c] for c in cats if c in MAP}),
                            "ms": ms,
                            "tokens": resp.get("tokens_evaluated", 0),
                        }
                    )
                    + "\n"
                )
                f.flush()
                print(f"{i + 1}/{len(todo)} {ms} ms", end="\r")
    finally:
        srv.close()
    print(f"\ndone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
