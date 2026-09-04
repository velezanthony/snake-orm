"""The SQLite dialect: the SECOND engine, and the proof that the seam was honest.

What was measured before writing it (SQLite 3.50) changed the scope: SQLite has `RETURNING`, upsert,
a row constructor, partial indexes, `WITH RECURSIVE` and window functions. Which means almost all of
`query/` is reused as is and phases 1 and 2 come in for free.

What it does NOT have is what the flags declare: `ADD CONSTRAINT`, `ALTER COLUMN`, `CREATE SCHEMA`,
`FOR UPDATE` and `COMMENT ON`. The project's rule for that: **fail while COMPILING the query, not
while running it**, and the message states the alternative. SQL the engine would not understand is
never emitted just so the engine blows up on it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from snakeorm.dialects import SQLiteDialect

_DIALECT = SQLiteDialect()


def test_the_placeholder_is_a_question_mark() -> None:
    """SQLite uses a positional `?`, not psycopg2's `%s`.

    It is what makes the textual order of the params matter just as in Postgres: both are
    positional, so the rule of concatenating in textual order holds for both.
    """
    assert _DIALECT.placeholder(0) == "?"
    assert _DIALECT.placeholder(7) == "?"


def test_it_quotes_with_double_quotes() -> None:
    """SQLite accepts standard double quotes; they are escaped by doubling them, just as in Postgres."""
    assert _DIALECT.quote_ident("tabla") == '"tabla"'
    assert _DIALECT.quote_ident('ra"ro') == '"ra""ro"'


@pytest.mark.parametrize(
    ("python_type", "expected"),
    [
        (int, "INTEGER"),
        (str, "TEXT"),
        (bool, "INTEGER"),
        (float, "REAL"),
        (bytes, "BLOB"),
        # TEXT and not NUMERIC: SQLite's numeric affinity CONVERTS to REAL any text that looks
        # like a number, so an exact Decimal would go in and come out as a float. See
        # `test/integration/test_type_round_trip.py`, which checks it by running it.
        (Decimal, "TEXT"),
        (datetime, "TEXT"),
    ],
)
def test_it_maps_to_the_five_storage_classes(python_type: type, expected: str) -> None:
    """SQLite only has five storage classes: everything maps onto one of them.

    `datetime` goes to TEXT (ISO-8601) because SQLite has no date type. It is a real limitation of
    the engine and it gets documented; inventing a type that does not exist would be worse.
    """
    assert _DIALECT.map_type(python_type) == expected


def test_autoincrement_is_integer_primary_key() -> None:
    """In SQLite the autoincrement is `INTEGER PRIMARY KEY`, which aliases the internal ROWID.

    It is not `SERIAL` nor `AUTOINCREMENT`: that keyword exists but it only adds a sequence table
    and SQLite recommends not using it unless it is really needed.
    """
    assert _DIALECT.map_type(int, autoincrement=True) == "INTEGER"


def test_the_capability_flags_say_what_it_cannot_do() -> None:
    """The flags are the COMPLETE list of what separates SQLite from Postgres in this ORM.

    They are checked here, together and explicit, because a badly set flag does not fail: it makes
    the migration engine take the wrong path and you find out against the database.
    """
    assert _DIALECT.supports_returning is True, "SQLite 3.35+ has RETURNING"
    assert _DIALECT.supports_upsert is True, "ON CONFLICT since 3.24"
    assert _DIALECT.supports_row_constructor is True, "(a,b) IN ((1,2)) funciona"
    assert _DIALECT.supports_transactional_ddl is True, (
        "the DDL goes inside the transaction"
    )

    assert _DIALECT.supports_add_constraint is False, (
        "there is no ALTER TABLE ... ADD CONSTRAINT"
    )
    assert _DIALECT.supports_alter_column is False, "there is no ALTER COLUMN"
    assert _DIALECT.supports_schemas is False, "the schemas are ATTACHED databases"
    assert _DIALECT.supports_row_locking is False, "it locks the file, not the row"
    assert _DIALECT.supports_comments is False, "no guarda COMMENT ON"


def test_limit_and_offset_travel_parameterised() -> None:
    """The bounding travels parameterised too: the rule admits no exceptions by type."""
    params: list[object] = []
    clause = _DIALECT.limit_offset(10, 5, params)

    assert clause == "LIMIT ? OFFSET ?"
    assert params == [10, 5]


def test_an_offset_without_limit_uses_the_sqlite_idiom() -> None:
    """SQLite requires a LIMIT in order to accept OFFSET; the idiom is `LIMIT -1`.

    Postgres accepts a bare `OFFSET`. It is a difference of SYNTAX —what the dialect exists to
    absorb—, not of strategy.
    """
    params: list[object] = []
    clause = _DIALECT.limit_offset(None, 5, params)

    assert clause == "LIMIT -1 OFFSET ?"
    assert params == [5]
