"""Scenario harness fixtures: the devcontainer Postgres seeded with edge cases.

Connects through .env variables (see db.py), creates the schema and seeds it ONCE per session. If
there is no Postgres, the tests skip gracefully. The database is left populated (playground).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn
from test.scenarios.schema import create_schema, seed


@pytest.fixture(scope="session")
def seeded_session() -> Iterator[SnakeSession]:
    """Session against the devcontainer Postgres with the scenario domain already seeded."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON} (check .env / devcontainer): {error}")

    create_schema(driver)
    seed(driver)
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.close()
