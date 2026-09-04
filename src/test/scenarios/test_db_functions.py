"""PHASE E against a real Postgres: session.call() over a FUNCTION and CreateFunction via the runner.

A procedure/function is OPAQUE SQL: the ORM does NOT verify what it returns. The contract is DECLARED
(a @snake_row) and the session HYDRATES each row into that shape, coercing the types. Here a real
FUNCTION (`RETURNS TABLE`) is created with its OWN unique names, it is called with `session.call(...)`
and the rows are checked to map onto the dataclass with the right VALUES and the coerced types
(NUMERIC→float). On top of that a `CreateFunction` is applied/reverted with the runner, checking in
`information_schema.routines` that the function exists and then disappears.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import SnakeRow, snake_row
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.metadata import SnakeRoutineInfo
from snakeorm.migration import CreateFunction, Migration, MigrationRunner
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

# A real payroll function: RETURNS TABLE, with an argument (factor) that multiplies the net. That is
# how we check that the argument travels parametrized and affects the result.
_FUNCTION_BODY = (
    "CREATE OR REPLACE FUNCTION snake_it_payroll(factor integer) "
    "RETURNS TABLE(employee_id integer, gross numeric, net numeric) AS $$ "
    "SELECT * FROM (VALUES "
    "(1, 2000::numeric, (1600 * factor)::numeric), "
    "(2, 3000::numeric, (2400 * factor)::numeric)) "
    "AS t(employee_id, gross, net) $$ LANGUAGE sql"
)


@snake_row
class _Payroll(SnakeRow):
    """Declared shape: `net` is float even though the function returns NUMERIC (Decimal→float coercion)."""

    employee_id: int
    gross: Decimal
    net: float


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates the payroll function and returns a session against the real Postgres."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    driver = PsycopgDriver(connection)
    driver.execute(_FUNCTION_BODY, ())
    driver.commit()
    return SnakeSession(driver, PostgresDialect())


def test_call_maps_function_rows_to_the_declared_shape(session: SnakeSession) -> None:
    """`session.call` calls the RETURNS TABLE function and maps its rows to the @snake_row with its values."""
    rows = session.call("snake_it_payroll", [1], into=_Payroll)
    assert [(r.employee_id, r.gross, r.net) for r in rows] == [
        (1, Decimal("2000"), 1600.0),
        (2, Decimal("3000"), 2400.0),
    ]


def test_call_passes_the_argument_parametrized(session: SnakeSession) -> None:
    """The argument travels parametrized and affects the result: with factor=2 the net doubles."""
    rows = session.call("snake_it_payroll", [2], into=_Payroll)
    assert [r.net for r in rows] == [3200.0, 4800.0]


def test_call_coerces_numeric_to_float(session: SnakeSession) -> None:
    """The field declared float receives the NUMERIC coerced to float (source of truth: the type)."""
    row = session.call("snake_it_payroll", [1], into=_Payroll)[0]
    assert isinstance(row.net, float)
    assert isinstance(row.gross, Decimal)  # gross was declared Decimal: untouched


def _routine_exists(driver: PsycopgDriver, name: str) -> bool:
    """Queries information_schema.routines to find out whether the function exists in the public schema."""
    rows = driver.fetch_all(
        "SELECT COUNT(*) FROM information_schema.routines "
        "WHERE routine_schema = 'public' AND routine_name = %s",
        (name,),
    )
    return bool(rows[0][0])


def test_create_function_applies_and_reverts_via_runner() -> None:
    """The runner applies a CreateFunction (the function shows up) and its rollback deletes it (it vanishes)."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    driver = PsycopgDriver(connection)
    body = (
        "CREATE OR REPLACE FUNCTION snake_it_greet(who text) "
        "RETURNS TABLE(saludo text) AS $$ SELECT 'hola ' || who $$ LANGUAGE sql"
    )
    routine = SnakeRoutineInfo(name="snake_it_greet", body=body)
    migration = Migration(version="itfn_0001", operations=(CreateFunction(routine),))
    runner = MigrationRunner(driver, PostgresDialect())
    try:
        driver.execute("DROP FUNCTION IF EXISTS snake_it_greet(text)", ())
        driver.commit()

        runner.apply([migration])
        assert _routine_exists(driver, "snake_it_greet") is True

        runner.rollback(migration)
        assert _routine_exists(driver, "snake_it_greet") is False
    finally:
        driver.execute("DROP FUNCTION IF EXISTS snake_it_greet(text)", ())
        driver.commit()
        driver.close()
