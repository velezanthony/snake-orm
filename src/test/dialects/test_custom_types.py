"""Tests for `register_type`: adding a Python type to a dialect's vocabulary.

The hole they close: the project's thesis is "the type system is the single source of truth", but the
type VOCABULARY was closed. `_POSTGRES_TYPES` was a module-private dict and `map_type` raised on
anything it did not know, so declaring an `INET`, `CITEXT`, `TSVECTOR` or a domain type column
required EDITING the dialect. SQLAlchemy has `TypeDecorator` and Django has `Field.db_type()`; here
there was nothing.

Registering is per dialect and explicit: the same Python type may be written differently in Postgres
and in SQLite, which is precisely why Dialect and Driver are separate axes.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects import PostgresDialect, SQLiteDialect


class Inet:
    """A user type: an IP address. Postgres has a native `INET`; SQLite does not."""


class Money:
    """Another user type, to check that several register without stepping on each other."""


@pytest.fixture
def dialect() -> PostgresDialect:
    """A FRESHLY built dialect: the registry is its own, not the module's."""
    return PostgresDialect()


def test_an_unregistered_type_is_rejected_with_a_useful_message(
    dialect: PostgresDialect,
) -> None:
    """Verifies that an unknown type still fails, but saying HOW to register it.

    Keeping the raise is correct: guessing the SQL type of any old class would be worse than
    refusing. What changes is that the message stops being a dead end.
    """
    with pytest.raises(SnakeDialectError, match="register_type"):
        dialect.map_type(Inet)


def test_a_registered_type_maps_to_its_sql_type(dialect: PostgresDialect) -> None:
    """Verifies that once registered, the type is emitted as its SQL type."""
    dialect.register_type(Inet, "INET")
    assert dialect.map_type(Inet) == "INET"


def test_registering_does_not_leak_into_another_dialect_instance() -> None:
    """Verifies that the registry belongs to THAT instance, not to the world.

    If it were global, importing a library that registers a type would sneak it into every dialect
    in the process — including those of another database that does not support it.
    """
    postgres = PostgresDialect()
    postgres.register_type(Inet, "INET")
    with pytest.raises(
        SnakeDialectError,
        match="If it is a type of your own, or a Postgres one the ORM does",
    ):
        PostgresDialect().map_type(Inet)


def test_the_same_type_can_map_differently_per_engine() -> None:
    """Verifies that each engine decides its own spelling of the same Python type.

    It is the whole Dialect axis in one test: `Inet` is `INET` in Postgres and `TEXT` in SQLite, and
    the model learns about neither of the two.
    """
    postgres, sqlite = PostgresDialect(), SQLiteDialect()
    postgres.register_type(Inet, "INET")
    sqlite.register_type(Inet, "TEXT")
    assert (postgres.map_type(Inet), sqlite.map_type(Inet)) == ("INET", "TEXT")


def test_several_types_coexist(dialect: PostgresDialect) -> None:
    """Verifies that registering a second type does not step on the first one."""
    dialect.register_type(Inet, "INET")
    dialect.register_type(Money, "NUMERIC(19,4)")
    assert (dialect.map_type(Inet), dialect.map_type(Money)) == (
        "INET",
        "NUMERIC(19,4)",
    )


def test_a_registered_type_works_inside_an_array(dialect: PostgresDialect) -> None:
    """Verifies that a registered type works as an array's element.

    It is the proof that the registry goes through the SAME path as the native types and not through
    a branch of its own: if it were a special case, `list[Inet]` would not find it.
    """
    dialect.register_type(Inet, "INET")
    assert dialect.map_type(list[Inet]) == "INET[]"


def test_registering_over_a_builtin_type_is_allowed(dialect: PostgresDialect) -> None:
    """Verifies that a native type can be overwritten (e.g. `str` to CITEXT across the whole base).

    It is a legitimate and explicit escape hatch: whoever does it knows what they are doing. Banning
    it would force forking the entire dialect to change one line.
    """
    dialect.register_type(str, "CITEXT")
    assert dialect.map_type(str) == "CITEXT"


def test_builtin_types_still_work_after_registering(dialect: PostgresDialect) -> None:
    """Verifies that opening up the vocabulary does not break the one already there."""
    dialect.register_type(Inet, "INET")
    assert dialect.map_type(bool) == "BOOLEAN"
    assert dialect.map_type(bytes) == "BYTEA"
