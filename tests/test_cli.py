"""The CLI end to end: argument, stdin batch, JSON output, exit codes. Real Jev."""

import io
import json
import os

import pytest

from jevmod.cli import main

pytestmark = pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")


def test_single_message_exit_code_and_text(capsys):
    code = main(["check", "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro"])
    out = capsys.readouterr().out
    assert code == 1 and ("scam" in out or "spam" in out), out


def test_stdin_batch_json_and_rule(capsys, monkeypatch):
    lines = [
        "Anyone know if the patch fixed the inventory bug?",
        "The left is destroying this country, vote them out next month",
        "ok",
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    code = main(["check", "--json", "--rule", "No political discussion here.", "-"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 1 and len(rows) == 3
    by_text = {r["text"]: r for r in rows}
    assert by_text[lines[0]]["action"] == "none" and by_text[lines[0]]["judged"]
    assert by_text[lines[1]]["category"] == "rule:rule1", by_text[lines[1]]
    assert by_text["ok"]["judged"] is False


def test_clean_message_exits_zero(capsys):
    assert main(["check", "gg everyone, that raid was clean. same time tomorrow?"]) == 0


def test_bad_key_exits_two(monkeypatch, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "not-a-key")
    assert main(["check", "some message long enough to be judged"]) == 2
    assert "error:" in capsys.readouterr().err
