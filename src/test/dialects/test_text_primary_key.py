"""An unbounded text column in a PRIMARY KEY: the engines that refuse it say so before the DDL runs.

MySQL and MariaDB will not put a `TEXT` column in a primary key — a key needs a length and `TEXT`
has none — and they answer error 1170, *"BLOB/TEXT column used in key specification without a key
length"*, which kills the WHOLE `CREATE TABLE`. Until this guard, the ORM emitted that DDL happily:
the first sign was the driver's own error, in the engine's words, at migration time.

**The ORM does not pick a length.** Defaulting to `VARCHAR(255)` would make it work and would be
worse than the bug: the ORM would be inventing a limit the caller never chose, and the day a value
exceeded it the data would be truncated rather than refused. So it shouts, and names the argument
that is missing.

It raises rather than warns because the alternative outcome is not a degraded table, it is NO table.

Scope, measured rather than assumed: on MariaDB 11.8 a `UNIQUE` or an `INDEX` over `TEXT` is
ACCEPTED, so only the primary key is guarded. Whether MySQL 8 refuses those too was not verified
here, and guarding what this engine accepts would be the ORM forbidding what the database allows.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeColumn,
    SnakeModel,
    SQLiteDialect,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.decorators import snake_table
from snakeorm.dialects.base import SnakeDialect
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.migration import emit_create_table


@snake_model(table="tpk_unbounded")
class Unbounded(SnakeModel):
    """A string primary key with no `max_length`: the shape that used to reach MySQL."""

    key: SnakeColumn[str] = snake_str(primary_key=True)
    n: SnakeColumn[int] = snake_int()


@snake_model(table="tpk_bounded")
class Bounded(SnakeModel):
    """The same key with a length, which every engine accepts."""

    key: SnakeColumn[str] = snake_str(primary_key=True, max_length=32)
    n: SnakeColumn[int] = snake_int()


@snake_model(table="tpk_plain")
class PlainColumn(SnakeModel):
    """An unbounded string that is NOT part of the key: nothing to refuse here."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    note: SnakeColumn[str] = snake_str()


def test_mysql_refuses_an_unbounded_text_primary_key_and_names_the_column() -> None:
    """The refusal carries the column and the argument that would fix it, not just a complaint."""
    with pytest.raises(SnakeUnsupportedFeature) as refusal:
        emit_create_table(snake_table(Unbounded), MySQLDialect())

    message = str(refusal.value)
    assert "key" in message, "the message does not name the offending column"
    assert "max_length" in message, (
        "the message does not name the argument that fixes it"
    )


def test_a_length_is_all_it_takes() -> None:
    """With `max_length` the same key emits, and it emits as `VARCHAR` rather than `TEXT`."""
    sql = emit_create_table(snake_table(Bounded), MySQLDialect())

    assert "VARCHAR(32)" in sql
    assert "PRIMARY KEY" in sql


def test_an_unbounded_string_outside_the_key_is_left_alone() -> None:
    """The guard is about KEYS: a `TEXT` column MySQL is happy to store is not refused."""
    sql = emit_create_table(snake_table(PlainColumn), MySQLDialect())

    assert "TEXT" in sql


@pytest.mark.parametrize(
    "dialect", [PostgresDialect(), SQLiteDialect()], ids=lambda d: type(d).__name__
)
def test_the_engines_that_can_do_it_still_do(dialect: SnakeDialect) -> None:
    """Postgres and SQLite key an unbounded text column fine, and nothing here stops them."""
    sql = emit_create_table(snake_table(Unbounded), dialect)

    assert "PRIMARY KEY" in sql


def test_the_engines_answer_the_capability_and_mysql_is_the_one_that_cannot() -> None:
    """The refusal comes from the catalogue, so the reason lives where every other reason does.

    Read together with the test above: one asks the catalogue, the other asks the emitter, and if
    they ever disagreed the capability would be a declaration nobody honours.
    """
    assert PostgresDialect().capabilities.can(Cap.TEXT_IN_PRIMARY_KEY)
    assert SQLiteDialect().capabilities.can(Cap.TEXT_IN_PRIMARY_KEY)

    support = MySQLDialect().capabilities.support_for(Cap.TEXT_IN_PRIMARY_KEY)
    assert isinstance(support, Nope)
    assert "length" in support.reason
