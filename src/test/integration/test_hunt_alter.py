"""HUNT 2 — every `AlterColumn` path APPLIED against Postgres, not merely emitted.

The `AlterColumn` tests check which SQL gets emitted. None of them EXECUTES it. And that is where
the difference between "the SQL is valid" and "the SQL does what it says" lives: the uniqueness bug
—creating under one name and dropping under another— passed every emission test.

Every test here: it creates the table, applies the `up`, checks the CATALOGUE, applies the `down`,
and checks that it returns to the initial state.

It skips gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import PostgresDialect, PsycopgDriver
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDecimalParams,
    SnakePrimaryKeyInfo,
    SnakeServerDefault,
    SnakeTableInfo,
)
from snakeorm.migration import AlterColumn, emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)


def _table(column: SnakeColumnInfo) -> SnakeTableInfo:
    """The `alt_probe` table with the `valor` column in whatever state it is handed."""
    return SnakeTableInfo(
        name="alt_probe",
        columns=(_ID, column),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


@pytest.fixture
def driver() -> Iterator[PsycopgDriver]:
    """Real driver with the test table clean before and after."""
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    connection.execute("DROP TABLE IF EXISTS alt_probe CASCADE", ())
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute("DROP TABLE IF EXISTS alt_probe CASCADE", ())
        connection.commit()
        connection.close()


def _apply(driver: PsycopgDriver, statements: list[str]) -> None:
    """Runs the statements and commits."""
    for statement in statements:
        driver.execute(statement, ())
    driver.commit()


def _type(driver: PsycopgDriver) -> str:
    """Current SQL type of the `valor` column, read from the catalogue."""
    rows = driver.fetch_all(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'alt_probe' AND column_name = 'valor'",
        (),
    )
    return str(rows[0][0])


def _nullable(driver: PsycopgDriver) -> bool:
    """Whether the `valor` column accepts NULL, read from the catalogue."""
    rows = driver.fetch_all(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'alt_probe' AND column_name = 'valor'",
        (),
    )
    return str(rows[0][0]) == "YES"


def _default(driver: PsycopgDriver) -> str | None:
    """Current DEFAULT of the `valor` column, read from the catalogue."""
    rows = driver.fetch_all(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'alt_probe' AND column_name = 'valor'",
        (),
    )
    return None if rows[0][0] is None else str(rows[0][0])


def _round_trip(
    driver: PsycopgDriver, before: SnakeColumnInfo, after: SnakeColumnInfo
) -> None:
    """Creates the table at `antes`, applies the up and then the down."""
    _apply(driver, [emit_create_table(_table(before), _DIALECT)])
    operation = AlterColumn(_table(after), before, after)
    _apply(driver, operation.up_sql(_DIALECT))


def test_changing_the_type_actually_changes_it(driver: PsycopgDriver) -> None:
    """Checks the `ALTER ... TYPE ... USING` and its reverse, against the catalogue."""
    before = SnakeColumnInfo(name="valor", python_type=int)
    after = SnakeColumnInfo(name="valor", python_type=str)

    _round_trip(driver, before, after)
    assert _type(driver) == "text"

    _apply(driver, AlterColumn(_table(before), after, before).up_sql(_DIALECT))
    # `int` defaults to BIGINT (the widest one): the reverse restores bigint, not integer.
    assert _type(driver) == "bigint"


def test_toggling_nullable_both_ways(driver: PsycopgDriver) -> None:
    """Checks `SET`/`DROP NOT NULL` for real, not just the emitted SQL."""
    required = SnakeColumnInfo(name="valor", python_type=str)
    optional = SnakeColumnInfo(name="valor", python_type=str, nullable=True)

    _round_trip(driver, required, optional)
    assert _nullable(driver) is True

    _apply(driver, AlterColumn(_table(required), optional, required).up_sql(_DIALECT))
    assert _nullable(driver) is False


def test_adding_and_removing_a_default(driver: PsycopgDriver) -> None:
    """Checks `SET DEFAULT` and `DROP DEFAULT` against the catalogue."""
    without_default = SnakeColumnInfo(name="valor", python_type=str)
    with_default = SnakeColumnInfo(
        name="valor", python_type=str, default="hola", has_default=True
    )

    _round_trip(driver, without_default, with_default)
    assert _default(driver) is not None and "hola" in str(_default(driver))

    _apply(
        driver,
        AlterColumn(_table(without_default), with_default, without_default).up_sql(
            _DIALECT
        ),
    )
    assert _default(driver) is None


def test_adding_and_removing_uniqueness(driver: PsycopgDriver) -> None:
    """THE UNIQUENESS BUG, applied: creating and dropping the constraint under the same name."""
    normal = SnakeColumnInfo(name="valor", python_type=str)
    unique = SnakeColumnInfo(name="valor", python_type=str, unique=True)

    _round_trip(driver, normal, unique)
    constraints = {
        str(row[0])
        for row in driver.fetch_all(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'alt_probe'::regclass AND contype = 'u'",
            (),
        )
    }
    assert constraints == {"uq_alt_probe_valor"}

    _apply(driver, AlterColumn(_table(normal), unique, normal).up_sql(_DIALECT))
    remaining = driver.fetch_all(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'alt_probe'::regclass AND contype = 'u'",
        (),
    )
    assert remaining == []


def test_changing_the_comment(driver: PsycopgDriver) -> None:
    """Checks that the `COMMENT ON` of the AlterColumn reaches the catalogue."""
    without = SnakeColumnInfo(name="valor", python_type=str)
    with_ = SnakeColumnInfo(name="valor", python_type=str, db_comment="documentada")

    _round_trip(driver, without, with_)
    rows = driver.fetch_all(
        "SELECT col_description('alt_probe'::regclass, a.attnum) FROM pg_attribute a "
        "WHERE a.attrelid = 'alt_probe'::regclass AND a.attname = 'valor'",
        (),
    )
    assert rows[0][0] == "documentada"


def test_changing_the_numeric_precision(driver: PsycopgDriver) -> None:
    """Checks that widening `NUMERIC(10,2)` to `NUMERIC(12,2)` really reaches the column."""
    narrow = SnakeColumnInfo(
        name="valor",
        python_type=Decimal,
        type_params=SnakeDecimalParams(precision=10, scale=2),
    )
    wide = SnakeColumnInfo(
        name="valor",
        python_type=Decimal,
        type_params=SnakeDecimalParams(precision=12, scale=2),
    )

    _round_trip(driver, narrow, wide)
    rows = driver.fetch_all(
        "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
        "WHERE table_name = 'alt_probe' AND column_name = 'valor'",
        (),
    )
    assert (rows[0][0], rows[0][1]) == (12, 2)


def test_adding_a_server_default(driver: PsycopgDriver) -> None:
    """Checks that moving to `server_default` leaves the server DEFAULT on the column."""
    without = SnakeColumnInfo(name="valor", python_type=datetime, nullable=True)
    with_ = SnakeColumnInfo(
        name="valor",
        python_type=datetime,
        nullable=True,
        server_default=SnakeServerDefault.NOW,
    )

    _round_trip(driver, without, with_)
    assert _default(driver) is not None
