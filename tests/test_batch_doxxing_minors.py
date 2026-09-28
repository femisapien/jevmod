"""Offline checks on the JEV-62 measurement, `benchmark/batch_doxxing_minors/REPORT.md`.

Two of them are about what the folder is allowed to hold rather than about arithmetic: the synthetic
doxxing set must carry only data reserved for fiction, and the results must carry no text, because the
`minors` rows are sexual content about minors from a public moderation eval and are not reproduced
anywhere in this repository.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `pytest tests` puts `tests/` on the path, not the repository root, and `benchmark` is not installed.
sys.path.insert(0, str(ROOT))
from benchmark.batch_doxxing_minors import doxxing_items, run  # noqa: E402

HERE = ROOT / "benchmark" / "batch_doxxing_minors"


def test_committed_doxxing_set_is_what_the_generator_writes():
    assert doxxing_items.load() == doxxing_items.build()


def test_doxxing_set_holds_only_fictional_contact_data():
    rows = doxxing_items.load()
    assert len(rows) == 2 * doxxing_items.PER_SIDE
    assert len({r["text"] for r in rows}) == len(rows), "identical texts are asked once per request"
    for r in rows:
        for phone in re.findall(r"\b555-\d{4}\b|\b07700 \d{6}\b", r["text"]):
            assert re.fullmatch(r"555-01\d\d|07700 900\d{3}", phone), phone
        for digits in re.findall(r"\d{3}[- ]?\d{4}", r["text"]):
            assert digits.startswith(("555", "900")) or "07700" in r["text"], r["text"]
        for domain in re.findall(r"@([\w.-]+\.\w+)", r["text"]):
            assert domain in ("example.com", "example.org"), domain


def test_results_carry_ids_and_scores_never_text():
    ids = {r["id"] for r in doxxing_items.load()}
    for line in (HERE / "results.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        assert "text" not in row
        assert set(row) == {"condition", "group", "side", "id", "scores", "batch_n", "pos", "batch_tokens", "req"}
        if row["group"] == "doxxing":
            assert row["id"] in ids


def test_results_hold_every_condition_once_per_item():
    seen: dict[str, set[str]] = {}
    for line in (HERE / "results.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        assert row["id"] not in seen.setdefault(row["condition"], set())
        seen[row["condition"]].add(row["id"])
    assert set(seen) == set(run.CONDITIONS)
    assert len({len(v) for v in seen.values()}) == 1, "every condition scored the same items"


def test_statistics():
    assert run._binom(0, 0) == 1.0
    assert abs(run._binom(0, 10) - 2 / 1024) < 1e-12
    lo, hi = run._wilson(0, 150)
    assert lo == 0.0 and 0.02 < hi < 0.03
    holm = run._holm([("a", 0.01), ("b", 0.04), ("c", 0.03)])
    assert holm == {"a": 0.03, "c": 0.06, "b": 0.06}
    # Clusters are resampled whole: two clusters with constant values give an interval inside them.
    lo, hi = run._boot([[1.0, 1.0, 1.0], [0.0]], lambda s: sum(s) / len(s), n=500)
    assert 0.0 <= lo <= hi <= 1.0
    assert run._cluster_sign([["a", "b"], ["c"]], {"a": 0.1, "b": -0.05, "c": -0.2}) == (1, 1)
