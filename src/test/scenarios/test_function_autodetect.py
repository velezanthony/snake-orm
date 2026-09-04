"""Function AUTODETECT against a real Postgres: declare → makemigrations → migrate → change body.

E2E scenario with UNIQUE names (`fa_*`): a function is declared with `snake_function`, the autodetect
picks it up (CreateFunction), the runner applies it and `information_schema.routines` is checked to
confirm it exists. Then the `body` is changed; the autodetect (replaying the first migration) emits an
AlterFunction, it gets applied and the function definition is checked to reflect the new body.

The routine registry is GLOBAL: it is isolated with monkeypatch so as not to contaminate other tests
and to declare the body versions here in a controlled way.
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_function
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.migration import (
    AlterFunction,
    CreateFunction,
    Migration,
    MigrationRunner,
    autodetect,
    current_routines,
)
from snakeorm.registry import registry
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_BODY_V1 = (
    "CREATE OR REPLACE FUNCTION fa_double(n integer) "
    "RETURNS integer AS $$ SELECT n * 2 $$ LANGUAGE sql"
)
_BODY_V2 = (
    "CREATE OR REPLACE FUNCTION fa_double(n integer) "
    "RETURNS integer AS $$ SELECT n * 3 $$ LANGUAGE sql"
)


@pytest.fixture
def clean_routines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the global routine store (empty on entry, restored on exit)."""
    monkeypatch.setattr(registry, "_routines", {})


def _routine_body(driver: PsycopgDriver, name: str) -> str | None:
    """Returns the full definition of the function (or None if absent), via pg_get_functiondef."""
    rows = driver.fetch_all(
        "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = %s",
        (name,),
    )
    return str(rows[0][0]) if rows else None


def test_function_autodetect_creates_then_alters_against_real_db(
    clean_routines: None,
) -> None:
    """makemigrations detects the function (Create), migrate creates it; changing the body emits Alter and updates it."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    driver = PsycopgDriver(connection)
    runner = MigrationRunner(driver, PostgresDialect())
    try:
        driver.execute("DROP FUNCTION IF EXISTS fa_double(integer)", ())
        driver.commit()

        # 1) Declare the desired function → the autodetect (empty history) emits a CreateFunction.
        snake_function(name="fa_double", body=_BODY_V1)
        first_ops = autodetect([], [], current_routines())
        assert len(first_ops) == 1 and isinstance(first_ops[0], CreateFunction)
        first = Migration(version="fa_it_0001", operations=tuple(first_ops))

        runner.apply([first])
        assert "n * 2" in (_routine_body(driver, "fa_double") or "")

        # 2) Change the body → the autodetect (replaying the 1st) emits an AlterFunction (old→new).
        snake_function(name="fa_double", body=_BODY_V2)
        second_ops = autodetect([first], [], current_routines())
        assert len(second_ops) == 1 and isinstance(second_ops[0], AlterFunction)
        second = Migration(version="fa_it_0002", operations=tuple(second_ops))

        runner.apply([second])
        updated = _routine_body(driver, "fa_double") or ""
        assert "n * 3" in updated and "n * 2" not in updated
    finally:
        driver.execute("DROP FUNCTION IF EXISTS fa_double(integer)", ())
        driver.execute(
            "DELETE FROM public.snake_migrations "
            "WHERE version IN ('fa_it_0001', 'fa_it_0002')",
            (),
        )
        driver.commit()
        driver.close()
