"""The HTTP API's limits, as names, in a module that does nothing when imported.

They used to be literals inside `Field(...)` calls in `server.py`, and three other places repeated them by
hand: the MCP tool, the hosted service's rate limiter and the prose of the website, which states each of
them in six languages. `server.py` cannot be imported just to read a number, because importing it opens a
SQLite file, so the numbers live here and everything that states or enforces them reads them from here.

`MAX_MESSAGES` is what one HTTP request (or one MCP call) may carry. It is not the size of a model request:
the judge splits a batch into requests by estimated tokens (`judge.REQUEST_TOKEN_BUDGET`), so fifty long
messages can go to the model as several requests. What a caller needs to know is this number.
"""

from __future__ import annotations

# Messages in one `POST /v1/moderate` body, and texts in one MCP `moderate` call. More is refused with 422.
MAX_MESSAGES = 50
# Characters in one message's `text`. Longer is refused with 422.
MAX_TEXT_CHARS = 8000
# `GET /v1/decisions`: entries returned with no `?limit=`, and the most any `?limit=` returns.
DECISIONS_DEFAULT = 50
DECISIONS_MAX = 500
