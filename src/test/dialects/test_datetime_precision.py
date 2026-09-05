"""Tests for the fractional-second precision: that it reaches the DDL, and that it cannot be absurd.

The declared precision got lost on MySQL. `snake_datetime(precision=3)` emitted `DATETIME(6)`, and so
did `precision=0`: the parameter was accepted, travelled whole through the graph, and the dialect
threw it in the bin without saying anything. It is EXACTLY the bug this branch already killed once
with NUMERIC's `precision`/`scale` —a declared parameter that does not reach the DDL— and it had
survived hidden inside the other engine.

And there is a second edge, which is the one forcing both things to go together: honouring the
precision without bounding it makes the place WORSE. While MySQL ignored it, a `precision=9` was
harmless; the moment it is honoured, `DATETIME(9)` gets emitted and the engine rejects it. Fixing
half of it would have traded a silent failure for a loud one, only later.

The range is checked in TWO different places, and it is not about duplicating:

    < 0             -> refused by the parameter itself, at construction time
    > the engine's  -> refused by the DIALECT, with the engine's name in the message

A negative number of digits means nothing on any engine: it is structural, and that is why it is cut
off in the metadata, which is agnostic. The CEILING, on the other hand, is the engine's knowledge
—Postgres and MySQL stop at 6, SQL Server reaches 7 and Oracle 9— and putting it in the metadata would
put a concrete engine inside the model, which is precisely what the project's golden rule forbids.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeColumn,
    SnakeUtc,
    snake_auto,
    snake_datetime,
    snake_datetimetz,
)
from snakeorm.compiler import compile_model
from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeDialectError, SnakeError
from snakeorm.metadata import SnakeDateTimeParams
from snakeorm.migration.ddl import sql_type_of


def _sql_type(dialect: SnakeDialect, precision: int | None) -> str:
    """The SQL type emitted by a WALL-CLOCK column with that precision."""
    model = type(
        "M",
        (),
        {
            "__annotations__": {"id": SnakeColumn[int], "c": SnakeColumn[datetime]},
            "id": snake_auto(),
            "c": snake_datetime(precision=precision),
        },
    )
    column = compile_model(model).get_column("c")
    assert column is not None
    return sql_type_of(column, dialect)


@pytest.mark.parametrize(
    ("precision", "expected"),
    [(0, "DATETIME(0)"), (3, "DATETIME(3)"), (6, "DATETIME(6)")],
)
def test_mysql_honours_the_declared_precision(precision: int, expected: str) -> None:
    """Verifies that MySQL emits the declared precision instead of throwing it away.

    `precision=0` is the case that really gives the bug away: it is a falsy value, so a badly written
    `if params.precision:` treats it just like "not declared" and goes back to the default. Storing
    whole seconds is a legitimate and frequent decision, and it was indistinguishable from asking for
    nothing.
    """
    assert _sql_type(MySQLDialect(), precision) == expected


def test_mysql_without_precision_keeps_its_default() -> None:
    """Verifies that not declaring a precision still gives `DATETIME(6)`.

    MySQL's default is a bare `DATETIME`, which truncates to seconds IN SILENCE; the dialect puts (6)
    on purpose so as not to lose the microseconds of Python's `datetime`. Honouring the parameter
    cannot run that decision over, or the fix for one silent failure would bring another.
    """
    assert _sql_type(MySQLDialect(), None) == "DATETIME(6)"


def test_postgres_keeps_honouring_it() -> None:
    """Verifies that the engine that ALREADY honoured it does not change behavior."""
    assert _sql_type(PostgresDialect(), 3) == "TIMESTAMP(3)"
    assert _sql_type(PostgresDialect(), None) == "TIMESTAMP"


@pytest.mark.parametrize("precision", [-1, -6])
def test_a_negative_precision_is_refused_on_construction(precision: int) -> None:
    """Verifies that a negative precision dies while building the parameter, not in `migrate`.

    A negative number of digits means nothing on any engine, so there is no need to wait to know which
    one it is: it is cut off in the metadata. It used to come out as is —`TIMESTAMPTZ(-1)`— and only
    Postgres denounced it, with its own syntax, three steps further along.
    """
    with pytest.raises(SnakeError, match="precision of a date cannot be negative"):
        SnakeDateTimeParams(tz=False, precision=precision)


@pytest.mark.parametrize(
    ("dialect", "engine"), [(PostgresDialect(), "Postgres"), (MySQLDialect(), "MySQL")]
)
def test_a_precision_above_the_engine_maximum_is_refused(
    dialect: SnakeDialect, engine: str
) -> None:
    """Verifies that going over the ceiling is denounced by the DIALECT, naming the engine.

    The ceiling is the engine's knowledge, not the model's: 6 here, 7 on SQL Server, 9 on Oracle.
    Putting it in the metadata would put a concrete engine inside the model —precisely what the golden
    rule forbids— and would make illegal on Postgres something that is correct on Oracle.
    """
    with pytest.raises(SnakeDialectError, match=engine):
        _sql_type(dialect, 7)


def test_the_tz_declarator_is_bound_by_the_same_rules() -> None:
    """Verifies that the column WITH a zone goes through the same thing, not through a parallel path.

    The two declarators share a body precisely so they cannot diverge; if the guard lived in only one
    of them, half the contract would depend on which one you wrote.
    """
    model = type(
        "MTz",
        (),
        {
            "__annotations__": {"id": SnakeColumn[int], "c": SnakeColumn[SnakeUtc]},
            "id": snake_auto(),
            "c": snake_datetimetz(precision=7),
        },
    )
    column = compile_model(model).get_column("c")
    assert column is not None
    with pytest.raises(SnakeDialectError, match="Postgres"):
        sql_type_of(column, PostgresDialect())
