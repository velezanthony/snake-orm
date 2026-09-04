"""Seeding the Django demo: the schema is built by the per-domain MIGRATIONS; here it gets populated.

The deterministic reset (`drop_all`) and the `migrate` (through `config_from_django()`, which reads
Django's native `DATABASES`) come first; generating the 29 tables of data comes from
`shared.data.seed`.
"""

from __future__ import annotations

from shared import config
from shared.data import demo_scale
from shared.data import seed as seed_data

from snakeorm.contrib.django import config_from_django


def reset_and_seed() -> None:
    """Reset + per-domain migrate + seeding at the `DEMO_SCALE` scale (a reproducible initial state).

    `drop_all` leaves the database clean; `config_from_django().migrate()` builds the schema by
    applying `apps/*/migrations` in dependency order; then it seeds.
    """
    config.drop_all("django")
    config_from_django().migrate()
    session = config.make_session("django")
    try:
        seed_data(session, demo_scale())
    finally:
        session.close()
