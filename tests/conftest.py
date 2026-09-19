"""Shared test setup.

The tests that talk to the real Jev API skip themselves when there is no key. They used to look only at the
environment variable, so a developer who had run `jevmod init` and stored the key in the OS keyring saw them
skip anyway, and the suite looked green while never touching the API. `has_key` resolves the key the same way
the product does: environment, then keyring, then .env.
"""

from __future__ import annotations

import os

from jevmod.keys import get_api_key

KEY = get_api_key()
NO_KEY_REASON = "no TypeSafe key: set TYPESAFE_API_KEY or run `jevmod init`"

if KEY:
    # The adapters and the API read the environment directly, so put the resolved key there for the subprocess
    # and client code under test. Nothing here prints it.
    os.environ.setdefault("TYPESAFE_API_KEY", KEY)
