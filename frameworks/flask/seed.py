"""Seed for the Flask demo: it only POPULATES data. The schema is built by the per-domain MIGRATIONS
(`SnakeOrmConfig.migrate()` in `app.py`), not by a shortcut. The deterministic reset (`drop_all`) and
the migrate run first, at boot; here we only generate the 20 data tables at the `DEMO_SCALE` scale.
"""

from __future__ import annotations

from shared import config
from shared.data import demo_scale
from shared.data import seed as seed_data

_FRAMEWORK = "flask"


def seed() -> None:
    """Seed the Flask demo at the `DEMO_SCALE` scale (the schema already exists: boot migrated it)."""
    session = config.make_session(_FRAMEWORK)
    try:
        seed_data(session, demo_scale())
    finally:
        session.close()


def reset_and_seed() -> None:
    """Deterministic reset (drop_all + per-domain migrations) + seed. For the tests: each one starts
    from a clean state, exactly like boot does. (It reuses `SNAKE.migrate()`, imported lazily so we
    do not close the cycle with `app.py`, which imports this module.)"""
    from app import SNAKE

    config.drop_all(_FRAMEWORK)
    SNAKE.migrate()
    seed()
