"""unitary/toxic-bert (the model behind Detoxify) over items.jsonl, local GPU. Run with the ComfyUI venv python,
which already has torch + transformers:  C:\\AI\\ComfyUI\\venv\\Scripts\\python benchmark\\run_toxicbert.py
Scores: toxic, severe_toxic, obscene, threat, insult, identity_hate. harassment := max(toxic, insult, threat,
identity_hate); nsfw := obscene (weak proxy). Writes results/toxicbert.jsonl."""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

DATA = Path(__file__).parent / "data" / "items.jsonl"
OUT = Path(__file__).parent / "results" / "toxicbert.jsonl"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    tok = AutoTokenizer.from_pretrained("unitary/toxic-bert")
    model = AutoModelForSequenceClassification.from_pretrained("unitary/toxic-bert").cuda().eval()
    labels = [model.config.id2label[i] for i in range(model.config.num_labels)]
    items = [json.loads(line) for line in DATA.open(encoding="utf-8")]
    t0 = time.time()
    with OUT.open("w", encoding="utf-8") as f:
        for i in range(0, len(items), 32):
            chunk = items[i : i + 32]
            enc = tok(
                [it["text"] for it in chunk], truncation=True, max_length=512, padding=True, return_tensors="pt"
            ).to("cuda")
            t1 = time.perf_counter()
            with torch.no_grad():
                probs = torch.sigmoid(model(**enc).logits).cpu().tolist()
            ms = int((time.perf_counter() - t1) * 1000)
            for it, p in zip(chunk, probs, strict=True):
                s = dict(zip(labels, [round(x, 4) for x in p], strict=True))
                f.write(json.dumps({"id": it["id"], "scores": s, "ms": ms / len(chunk)}) + "\n")
            print(f"{i + len(chunk)}/{len(items)}", end="\r")
    print(f"\ndone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
