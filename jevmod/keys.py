"""Where the TypeSafe key comes from, in this order: OS keyring, `TYPESAFE_API_KEY` in the environment, `.env` in
the current directory. `jevmod init` stores it (keyring first, `.env` with mode 600 as the fallback). Nothing here
ever prints or logs the key.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

SERVICE = "jevmod"
ACCOUNT = "TYPESAFE_API_KEY"
ENV_VAR = "TYPESAFE_API_KEY"


def get_api_key(cwd: Path | None = None) -> str | None:
    """Keyring -> environment -> .env. None when nothing is set (TypeSafeClient then raises its own error)."""
    return _from_keyring() or os.environ.get(ENV_VAR, "").strip() or read_dotenv(cwd or Path.cwd()).get(ENV_VAR)


def _from_keyring() -> str | None:
    try:
        import keyring
    except ImportError:
        return None
    try:
        value = keyring.get_password(SERVICE, ACCOUNT)
    except Exception:  # no backend (headless Linux), locked vault, broken install: fall through
        return None
    return value.strip() if value and value.strip() else None


def store_in_keyring(key: str) -> bool:
    """True when the key is now in the OS keyring, False when keyring is missing or refused."""
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(SERVICE, ACCOUNT, key)
        return keyring.get_password(SERVICE, ACCOUNT) == key
    except Exception:
        return False


def read_dotenv(directory: Path) -> dict[str, str]:
    """Minimal `.env` parser: KEY=value lines, optional `export `, quotes stripped, `#` comments ignored."""
    path = directory / ".env"
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, _, v = line.partition("=")
        v = v.strip()
        if v[:1] in ("'", '"') and v[-1:] == v[:1] and len(v) >= 2:
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()
        if v:
            out[k.strip()] = v
    return out


def write_dotenv(key: str, directory: Path) -> Path:
    """Set TYPESAFE_API_KEY in `.env` (other lines kept), mode 600, and make sure `.gitignore` lists `.env`."""
    path = directory / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    entry = f"{ENV_VAR}={key}"
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().removeprefix("export ").startswith(f"{ENV_VAR}="):
            lines[i] = entry
            replaced = True
    if not replaced:
        lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    gitignore = directory / ".gitignore"
    if gitignore.is_file():
        entries = [ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()]
        if ".env" not in entries:
            with gitignore.open("a", encoding="utf-8") as fh:
                fh.write("\n.env\n")
    return path


def validate_key(key: str) -> None:
    """One tiny Jev call; raises TypeSafeError when the key is rejected or the API is unreachable."""
    from typesafe_sdk import Noul, RetryPolicy, TypeSafeClient

    with TypeSafeClient(api_key=key, retry=RetryPolicy(max_retries=1), timeout=15.0) as client:
        client.system_one(state={"text": "hello"}, questions={"ok": Noul(instructions="Is `text` a greeting?")})


def init(directory: Path | None = None, *, prefer_env_file: bool = False, prompt: bool = True) -> int:
    """`jevmod init`: ask for the key without echo, validate it, store it. Returns an exit code."""
    import sys
    from getpass import getpass

    from typesafe_sdk import TypeSafeError

    directory = directory or Path.cwd()
    try:
        key = getpass("TypeSafe API key (input hidden): ").strip() if prompt else os.environ.get(ENV_VAR, "").strip()
    except (EOFError, KeyboardInterrupt):
        print("cancelled", file=sys.stderr)
        return 2
    if not key:
        print("no key given", file=sys.stderr)
        return 2
    try:
        validate_key(key)
    except TypeSafeError as exc:
        print(f"key rejected: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if not prefer_env_file and store_in_keyring(key):
        print("key verified and stored in the OS keyring (service 'jevmod')")
        return 0
    path = write_dotenv(key, directory)
    why = "" if prefer_env_file else " (keyring unavailable)"
    print(f"key verified and written to {path} with mode 600{why}; .env is git-ignored when a .gitignore exists")
    return 0
