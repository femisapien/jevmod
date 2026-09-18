"""Start llama-server for a GGUF, wait for /health, expose a `complete()` helper with first-token probabilities."""

from __future__ import annotations

import math
import subprocess
import time
from typing import Any

import httpx

BIN = r"C:\AI\llama.cpp\bin\llama-server.exe"


class Server:
    def __init__(self, gguf: str, port: int, ctx: int = 4096, ngl: int = 99) -> None:
        self.port = port
        self.proc = subprocess.Popen(
            [BIN, "-m", gguf, "--port", str(port), "-c", str(ctx), "-ngl", str(ngl), "--log-disable", "-np", "4"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120)
        for _ in range(180):
            try:
                if self.http.get("/health").json().get("status") == "ok":
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("llama-server did not come up")

    def complete(self, prompt: str, n_predict: int = 16, n_probs: int = 8) -> dict[str, Any]:
        r = self.http.post(
            "/completion",
            json={"prompt": prompt, "n_predict": n_predict, "temperature": 0, "n_probs": n_probs, "cache_prompt": True},
        )
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except Exception:
            self.proc.kill()


def first_token_probs(resp: dict[str, Any]) -> dict[str, float]:
    """{token_text: prob} for the first generated token (llama.cpp completion_probabilities format)."""
    cp = resp.get("completion_probabilities") or []
    if not cp:
        return {}
    first = cp[0]
    probs = first.get("top_logprobs") or first.get("top_probs") or first.get("probs") or []
    out: dict[str, float] = {}
    for p in probs:
        tok = p.get("token") or p.get("tok_str") or ""
        out[tok] = float(p["prob"]) if "prob" in p else math.exp(float(p.get("logprob", -99)))
    return out
