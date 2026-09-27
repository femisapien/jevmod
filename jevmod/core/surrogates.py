"""Lone UTF-16 surrogates: strings Python can hold and nothing downstream can write (JEV-83).

JSON lets a client send `"\\ud83d"` on its own, usually half an emoji left behind by code that cut a
JavaScript string by length. `json.loads` turns it into a Python `str` holding one surrogate code
point, U+D800 to U+DFFF, and everything goes along with it until something encodes it as UTF-8:
SQLite, the JSON response, the request to Jev, the SHA-256 of the cache key. Each of those raises
`UnicodeEncodeError`, and where the raise lands decides what it costs. `author` and `id` are only
written after Jev has answered, so a request carrying one was paid for and then answered 502.

Two answers, one per kind of caller:

- The HTTP API rejects the field (`contains_lone_surrogate`). The caller is a program that can be
  told, and an `id` rewritten to something else would come back as a decision for a message it never
  sent. See `jevmod/api/server.py`.
- The service replaces them in text it only reads (`replace_lone_surrogates`). An adapter has nobody
  to tell, and a surrogate that reached the conversation window would break every later message in
  that channel, because the window is part of every one of their cache keys.
"""

from __future__ import annotations

import re
from typing import Any

_SURROGATE = re.compile("[\ud800-\udfff]")


def contains_lone_surrogate(s: str) -> bool:
    """True when `s` cannot be encoded as UTF-8 because of a surrogate code point.

    Any surrogate code point counts, paired or not: a Python `str` that holds a high and a low
    surrogate as two code points is exactly as unwritable as one holding either alone. `json.loads`
    already joins a well-formed `\\ud83d\\ude00` into the one code point it stands for, so what
    reaches this from a request body is only ever the broken kind."""
    return _SURROGATE.search(s) is not None


def replace_lone_surrogates(s: str) -> str:
    """`s` with every surrogate that does not form a pair replaced by U+FFFD, and every pair that
    was held as two code points joined into the one it encodes. A string without surrogates comes
    back unchanged, and it is the same object, so the common case costs one regex scan."""
    if not contains_lone_surrogate(s):
        return s
    return s.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def scrub(value: Any) -> Any:
    """`replace_lone_surrogates` applied to every string in a JSON-shaped value, keys included."""
    if isinstance(value, str):
        return replace_lone_surrogates(value)
    if isinstance(value, dict):
        return {scrub(k): scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value
