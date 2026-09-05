"""MySQL's introspector, against a real server: the ORM writes the schema and reads it back.

The third axis had a hole in it. `architecture.md` published a green tick for all three engines on
Dialect, Driver AND Introspector, and this one did not exist — so `scaffold` and `check` did not
work on MySQL at all. A table claiming a capability nobody wrote is worse than the missing
capability, because the missing one eventually gets noticed.

The shape of the check is `test_hunt_scaffold_drift`'s, which is the best one in this repository: the
ORM emits the DDL, the ORM reads it back, and `drift(...)` has to be EXACTLY empty. A whitelist, not
a list of things to look for — anything the two sides disagree about falls, including whatever
nobody thought to enumerate. If it says something, either the introspector lies or the DDL does.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest

from test.conftest import NO_MYSQL_REASON

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_auto,
    snake_column,
    snake_decimal,
    snake_link,
    snake_model,
    snake_str,
    snake_table,
    snake_to_one,
)
from snakeorm.dialects import MySQLDialect
from snakeorm.drivers import PyMySQLDriver, SnakeDriver
from snakeorm.introspection import MySQLIntrospector, drift
from snakeorm.migration import emit_add_foreign_key, emit_create_table


@snake_model(table="mi_makers")
class Maker(SnakeModel):
    """The referenced side: it exists so the FK has somewhere to point."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(max_length=60, unique=True)


@snake_model(table="mi_widgets")
class Widget(SnakeModel):
    """One column of every family the round trip has to survive, plus the FK."""

    id: SnakeColumn[int] = snake_auto()
    label: SnakeColumn[str] = snake_str(max_length=80, unique=True)
    active: SnakeColumn[bool] = snake_column()
    price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
    made_on: SnakeColumn[date] = snake_column()
    maker_id: SnakeColumn[int] = snake_column()
    maker: SnakeToOne[Maker] = snake_to_one(maker_id)


snake_link()

_TABLES = ("mi_widgets", "mi_makers")  # children first: the FK dictates the order


@pytest.fixture(scope="module")
def driver() -> Iterator[SnakeDriver]:
    """A MySQL connection with the two tables created by the ORM itself."""
    host = os.environ.get("MYSQL_HOST")
    if not host:
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    import pymysql

    try:
        connection = PyMySQLDriver.connect(
            host=host,
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DB", "snakeorm_db"),
        )
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    dialect = MySQLDialect()
    for statement in dialect.drop_all_sql(_TABLES):
        connection.execute(statement, ())
    for model in (Maker, Widget):
        connection.execute(emit_create_table(snake_table(model), dialect), ())
    # The FK goes in AFTERWARDS, which is the order the ORM itself uses: `CREATE TABLE` never
    # carries one, so every table exists before anything points at it. Building the fixture any
    # other way would be testing a schema this ORM does not produce.
    widgets = snake_table(Widget)
    connection.execute(
        emit_add_foreign_key(
            widgets, widgets.relationships[0], snake_table(Maker), dialect
        ),
        (),
    )
    connection.commit()
    yield connection
    for statement in dialect.drop_all_sql(_TABLES):
        connection.execute(statement, ())
    connection.commit()
    connection.close()


def test_what_the_orm_wrote_it_reads_back_with_no_drift(driver: SnakeDriver) -> None:
    """The ORM emitted this schema from these models; drift has nothing to report.

    THE test. Everything else in this file explains a piece of it; this one says the pieces add up.
    """
    declared = [snake_table(Maker), snake_table(Widget)]
    read_back = [
        table for table in MySQLIntrospector(driver).tables() if table.name in _TABLES
    ]

    assert drift(declared, read_back, MySQLDialect()) == []


def test_a_tinyint_1_comes_back_as_the_bool_it_was(driver: SnakeDriver) -> None:
    """`bool` survives the trip, and it is the one type that could not survive it by accident.

    MySQL has no boolean: the ORM writes `TINYINT(1)`, and `information_schema` calls that
    `tinyint` like every other one-byte integer. Reading it back by `DATA_TYPE` alone would answer
    `int`, and every boolean column in every mirrored model would be permanent drift.
    """
    table = next(
        t for t in MySQLIntrospector(driver).tables() if t.name == "mi_widgets"
    )
    active = next(column for column in table.columns if column.name == "active")

    assert active.python_type is bool


def test_the_autoincrement_is_read_from_EXTRA_not_from_the_default(
    driver: SnakeDriver,
) -> None:
    """MySQL says `auto_increment` in `EXTRA`; the column's type stays `int`.

    Postgres says it in the DEFAULT (`nextval(...)`), so the two engines answer this question in
    different places — which is exactly why the introspector is per engine rather than one file
    with branches.
    """
    table = next(
        t for t in MySQLIntrospector(driver).tables() if t.name == "mi_widgets"
    )
    identifier = next(column for column in table.columns if column.name == "id")

    assert identifier.autoincrement is True
    assert identifier.python_type is int


def test_the_foreign_key_comes_back_pointing_at_the_table_it_references(
    driver: SnakeDriver,
) -> None:
    """One FK, one relationship, aimed at the target table's NAME."""
    table = next(
        t for t in MySQLIntrospector(driver).tables() if t.name == "mi_widgets"
    )

    assert len(table.relationships) == 1
    relationship = table.relationships[0]
    assert relationship.target_table == "mi_makers"
    assert relationship.foreign_key.pairs == (("maker_id", "id"),)


def test_it_does_not_invent_a_database_called_public(driver: SnakeDriver) -> None:
    """The default `schema` means "the connected database", not a database literally named `public`.

    `public` is Postgres's word and it travels in the Protocol because Postgres needs it. Passing it
    through as a MySQL database name would query one that does not exist and answer an empty schema
    — the shape of an answer, with none of the meaning.
    """
    names = {table.name for table in MySQLIntrospector(driver).tables()}

    assert "mi_widgets" in names
