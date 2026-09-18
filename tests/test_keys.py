"""Key resolution (env, .env) and `jevmod init` writing .env. The real OS keyring is never read or written here:
`_from_keyring` and `store_in_keyring` are patched. Validation against Jev runs only when a key is set."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jevmod import keys

REAL_KEY = os.environ.get("TYPESAFE_API_KEY", "")


@pytest.fixture(autouse=True)
def no_keyring(monkeypatch):
    monkeypatch.setattr(keys, "_from_keyring", lambda: None)
    monkeypatch.setattr(keys, "store_in_keyring", lambda key: False)


def test_env_wins_over_dotenv(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-env")
    assert keys.get_api_key(tmp_path) == "from-env"


def test_dotenv_when_env_is_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    (tmp_path / ".env").write_text(
        "# comment\nexport OTHER='x'\nTYPESAFE_API_KEY=\"quoted-key\"  # trailing\n", encoding="utf-8"
    )
    assert keys.get_api_key(tmp_path) == "quoted-key"
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert keys.get_api_key(tmp_path) == "quoted-key"


def test_nothing_set_returns_none(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert keys.get_api_key(tmp_path) is None


def test_read_dotenv_parses_minimal_syntax(tmp_path: Path):
    (tmp_path / ".env").write_text("A=1\nB = two words\nC=\nbroken line\nD='q'\n", encoding="utf-8")
    assert keys.read_dotenv(tmp_path) == {"A": "1", "B": "two words", "D": "q"}


def test_write_dotenv_replaces_keeps_others_and_gitignores(tmp_path: Path):
    (tmp_path / ".env").write_text("PORT=8080\nTYPESAFE_API_KEY=old\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    path = keys.write_dotenv("new-key", tmp_path)
    assert path.read_text(encoding="utf-8") == "PORT=8080\nTYPESAFE_API_KEY=new-key\n"
    assert ".env" in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    keys.write_dotenv("new-key", tmp_path)  # idempotent: .gitignore gets .env once
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").count(".env") == 1


def test_write_dotenv_without_gitignore_creates_none(tmp_path: Path):
    keys.write_dotenv("k", tmp_path)
    assert not (tmp_path / ".gitignore").exists()
    assert keys.read_dotenv(tmp_path)["TYPESAFE_API_KEY"] == "k"


def test_init_rejects_empty_input(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    assert keys.init(tmp_path) == 2
    assert "no key" in capsys.readouterr().err


@pytest.mark.skipif(not REAL_KEY, reason="TYPESAFE_API_KEY not set")
def test_init_rejects_a_bad_key_and_writes_nothing(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "not-a-real-key")
    assert keys.init(tmp_path) == 2
    assert "rejected" in capsys.readouterr().err
    assert not (tmp_path / ".env").exists()


@pytest.mark.skipif(not REAL_KEY, reason="TYPESAFE_API_KEY not set")
def test_init_validates_and_falls_back_to_dotenv(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": REAL_KEY)
    assert keys.init(tmp_path) == 0
    out = capsys.readouterr().out
    assert REAL_KEY not in out and ".env" in out
    assert keys.read_dotenv(tmp_path)["TYPESAFE_API_KEY"] == REAL_KEY


@pytest.mark.skipif(not REAL_KEY, reason="TYPESAFE_API_KEY not set")
def test_init_env_file_flag_via_cli(tmp_path: Path, monkeypatch, capsys):
    from jevmod.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": REAL_KEY)
    assert main(["init", "--env-file"]) == 0
    assert keys.read_dotenv(tmp_path)["TYPESAFE_API_KEY"] == REAL_KEY
