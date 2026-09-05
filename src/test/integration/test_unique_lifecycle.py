"""INTEGRATION: the life cycle of a UNIQUE constraint against a REAL Postgres.

This test exists because the bug was invisible in unit tests: each emitter on its own produced
perfectly valid SQL. It only showed up by running `up` and then `down` AGAINST THE DATABASE, which
is where the two names have to match.

The original failure, reproduced by hand:

    CREATE TABLE uq_probe (... "email" TEXT NOT NULL UNIQUE ...);
    -- Postgres auto-names the constraint: uq_probe_email_key
    ALTER TABLE uq_probe DROP CONSTRAINT "uq_uq_probe_email";
    -- ERROR: constraint "uq_uq_probe_email" of relation "uq_probe" does not exist

Skips gracefully if there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

from snakeorm.core.exceptions import SnakeUniqueViolation
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    emit_alter_column,
    emit_create_index,
    emit_create_table,
    emit_drop_index,
)
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_ID = SnakeColumnInfo(name="id", python_type=int)
_EMAIL_UNIQUE = SnakeColumnInfo(name="email", python_type=str, unique=True)
_EMAIL_PLAIN = SnakeColumnInfo(name="email", python_type=str)


def _table(column: SnakeColumnInfo) -> SnakeTableInfo:
    """Table `uq_lifecycle` with the email column in whatever state it is handed."""
    return SnakeTableInfo(
        name="uq_lifecycle",
        columns=(_ID, column, SnakeColumnInfo(name="city", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


@pytest.fixture
def driver() -> Iterator[PsycopgDriver]:
    """Driver against the real Postgres, with the test table wiped before and after."""
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    connection.execute("DROP TABLE IF EXISTS uq_lifecycle", ())
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute("DROP TABLE IF EXISTS uq_lifecycle", ())
        connection.commit()
        connection.close()


def _constraint_names(driver: PsycopgDriver) -> set[str]:
    """Names of the UNIQUE constraints the DB REALLY holds over the table."""
    rows = driver.fetch_all(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'uq_lifecycle'::regclass AND contype = 'u'",
        (),
    )
    return {str(row[0]) for row in rows}


def test_unique_column_can_be_created_and_then_dropped(driver: PsycopgDriver) -> None:
    """THE BUG, end to end: create the table with a unique column and then take the unique away.

    It used to fail right here with `constraint ... does not exist`, because the CREATE TABLE left
    `uq_lifecycle_email_key` behind and the ALTER went looking for `uq_uq_lifecycle_email`.
    """
    dialect = PostgresDialect()
    driver.execute(emit_create_table(_table(_EMAIL_UNIQUE), dialect), ())
    driver.commit()

    assert _constraint_names(driver) == {"uq_uq_lifecycle_email"}

    for sql in emit_alter_column(
        _table(_EMAIL_PLAIN), _EMAIL_UNIQUE, _EMAIL_PLAIN, dialect
    ):
        driver.execute(sql, ())
    driver.commit()

    assert _constraint_names(driver) == set()


def test_unique_column_actually_rejects_duplicates(driver: PsycopgDriver) -> None:
    """Verifies that the constraint with its own name STILL does its job."""

    driver.execute(emit_create_table(_table(_EMAIL_UNIQUE), PostgresDialect()), ())
    driver.commit()

    driver.execute(
        "INSERT INTO uq_lifecycle (id, email, city) VALUES (1, 'a@x.com', 'Bilbao')", ()
    )
    driver.commit()

    with pytest.raises(SnakeUniqueViolation, match="UNIQUE constraint"):
        driver.execute(
            "INSERT INTO uq_lifecycle (id, email, city) VALUES (2, 'a@x.com', 'Gasteiz')",
            (),
        )
    driver.rollback()


def test_unique_index_declaration_round_trips_as_a_constraint(
    driver: PsycopgDriver,
) -> None:
    """Verifies the cycle of a `SnakeIndex(unique=True)`: created and dropped by the SAME name."""
    dialect = PostgresDialect()
    table = _table(_EMAIL_PLAIN)
    index = SnakeIndexInfo(columns=("email", "city"), unique=True)

    driver.execute(emit_create_table(table, dialect), ())
    driver.execute(emit_create_index(table, index, dialect), ())
    driver.commit()

    assert _constraint_names(driver) == {"uq_uq_lifecycle_email_city"}

    driver.execute(emit_drop_index(table, index, dialect), ())
    driver.commit()

    assert _constraint_names(driver) == set()
