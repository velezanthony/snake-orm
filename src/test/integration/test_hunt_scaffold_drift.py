"""HUNT 4 — the full circle: the ORM creates the schema, the ORM reads it back.

The hardest test introspection can be put through: creating the tables with the DDL of the ORM
ITSELF and then reading them back. Whatever the emitter wrote and the introspector does not see
is, by definition, a hole —and on top of that one no scaffolding test caught, because they all
started from a hand-written schema and checked only what they knew to look for—.

And with that set up, drift comes for free: code and database are the SAME thing, so
`drift(...)` has to be empty. If it says anything, either the introspector lies or the DDL lies.

Skips gracefully if there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import PostgresDialect, PsycopgDriver
from snakeorm.introspection import PostgresIntrospector, drift
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import emit_comments, emit_create_index, emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_DIALECT = PostgresDialect()

_ID = SnakeColumnInfo(name="id", python_type=int, autoincrement=True, attr_name="id")

_ORIGINAL = SnakeTableInfo(
    name="ida_vuelta",
    db_comment="Created by the ORM itself",
    columns=(
        _ID,
        SnakeColumnInfo(
            name="email",
            python_type=str,
            unique=True,
            attr_name="email",
            db_comment="Correo",
        ),
        SnakeColumnInfo(
            name="apodo", python_type=str, nullable=True, attr_name="apodo"
        ),
        SnakeColumnInfo(name="saldo", python_type=Decimal, attr_name="saldo"),
        SnakeColumnInfo(
            name="visto", python_type=datetime, nullable=True, attr_name="visto"
        ),
        SnakeColumnInfo(name="active", python_type=bool, attr_name="active"),
    ),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    indexes=(SnakeIndexInfo(columns=("apodo",), name="ix_ida_vuelta_apodo"),),
)


@pytest.fixture
def read_back() -> Iterator[SnakeTableInfo]:
    """Creates the table with the ORM DDL and returns what the introspector reads back."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS ida_vuelta CASCADE", ())
    driver.execute(emit_create_table(_ORIGINAL, _DIALECT), ())
    for index in _ORIGINAL.indexes:
        driver.execute(emit_create_index(_ORIGINAL, index, _DIALECT), ())
    for statement in emit_comments(_ORIGINAL, _DIALECT):
        driver.execute(statement, ())
    driver.commit()
    try:
        tables = {t.name: t for t in PostgresIntrospector(driver).tables()}
        yield tables["ida_vuelta"]
    finally:
        driver.execute("DROP TABLE IF EXISTS ida_vuelta CASCADE", ())
        driver.commit()
        driver.close()


def test_every_column_comes_back(read_back: SnakeTableInfo) -> None:
    """No column gets lost along the way."""
    assert [c.name for c in read_back.columns] == [c.name for c in _ORIGINAL.columns]


def test_the_python_types_come_back(read_back: SnakeTableInfo) -> None:
    """The types come back as Python types, and the SAME ones that were written."""
    original = {c.name: c.python_type for c in _ORIGINAL.columns}
    returned = {c.name: c.python_type for c in read_back.columns}
    assert returned == original


def test_nullability_comes_back(read_back: SnakeTableInfo) -> None:
    """Nullability comes back identical: it is the one that breaks inserts if read wrong."""
    original = {c.name: c.nullable for c in _ORIGINAL.columns}
    returned = {c.name: c.nullable for c in read_back.columns}
    assert returned == original


def test_uniqueness_comes_back(read_back: SnakeTableInfo) -> None:
    """Uniqueness comes back identical, now that it is emitted as a constraint with its own name."""
    original = {c.name: c.unique for c in _ORIGINAL.columns}
    returned = {c.name: c.unique for c in read_back.columns}
    assert returned == original


def test_the_primary_key_comes_back(read_back: SnakeTableInfo) -> None:
    """The PK comes back, and the SERIAL is recognised as autoincrement."""
    assert [c.name for c in read_back.primary_key.columns] == ["id"]
    identifier = read_back.get_column("id")
    assert identifier is not None and identifier.autoincrement is True


def test_indexes_and_comments_come_back(read_back: SnakeTableInfo) -> None:
    """The index and the comments come back: they are what the scaffolding has to reproduce."""
    assert [i.name for i in read_back.indexes] == ["ix_ida_vuelta_apodo"]
    assert read_back.db_comment == "Created by the ORM itself"
    email = read_back.get_column("email")
    assert email is not None and email.db_comment == "Correo"


def test_there_is_no_drift_against_what_created_it(read_back: SnakeTableInfo) -> None:
    """THE ACID TEST: the code and the DB are the SAME thing, so there can be no drift.

    If `drift` says anything here, either the introspector reads wrong or the DDL writes something
    else. There is no third explanation, and that is why this test is worth all the previous ones
    put together.
    """
    assert drift([_ORIGINAL], [read_back], PostgresDialect()) == []
