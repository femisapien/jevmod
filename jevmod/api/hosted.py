"""The `hosted` role: one process serving the public demo (`/demo/*`), Stripe billing (`/billing/*`) and the
operator panel (`/admin`). Shares the tenant store with the Discord bot through JEVMOD_DB on the same volume."""

from __future__ import annotations

import os

from ..core import Store
from .billing import make_router
from .demo import app, spent_usd

store = Store(os.environ.get("JEVMOD_DB", "jevmod.sqlite"))
app.title = "jevmod hosted"
app.include_router(make_router(store, demo_spend=spent_usd))
