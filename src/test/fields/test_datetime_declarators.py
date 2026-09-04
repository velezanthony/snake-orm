"""The TWO date declarators: the SQL column is read right there in the declaration.

`TIMESTAMP` and `TIMESTAMPTZ` are different types of the database, and the model has to say which
one it is without anybody having to remember a rule. In the other four families the declarator does
this already —`snake_int(size=SMALLINT)` is SMALLINT, `snake_decimal(precision=12, scale=2)` is
NUMERIC(12,2)— and there was no reason for dates to be the exception.

Having the Python type say it TOO is not duplication for its own sake: each covers what the other
does not.

    snake_datetimetz()      says which COLUMN is created  -> read in the model, next to the rest
    SnakeColumn[SnakeUtc]   says which VALUE is accepted   -> enforced by the checker

And a guard demands that they agree, so the redundancy cannot lie. It is the same deal as
`snake_enum(State)` over a `SnakeColumn[State]`, whose docstring sums it up: "one single path,
explicit".
"""

from __future__ import annotations

from datetime import datetime

import pytest

from snakeorm import (
    PostgresDialect,
    SnakeColumn,
    SnakeModel,
    SnakeUtc,
    snake_column,
    snake_datetime,
    snake_datetimetz,
    snake_int,
    snake_model,
)
from snakeorm.compiler import compile_model
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.migration.ddl import sql_type_of
from snakeorm.registry import registry


@snake_model(table="decl_events")
class Event(SnakeModel):
    """Both date columns, each one with its own declarator."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    ocurrio: SnakeColumn[SnakeUtc] = snake_datetimetz()
    apertura: SnakeColumn[datetime] = snake_datetime()


def _sql_type(model: type, column: str) -> str:
    """The SQL type a column emits under Postgres."""
    table = registry.table_of(model)
    assert table is not None
    info = table.get_column(column)
    assert info is not None
    return sql_type_of(info, PostgresDialect())


def test_the_tz_declarator_creates_a_timestamptz() -> None:
    """`snake_datetimetz()` emits `TIMESTAMPTZ`, and it reads right there in the declaration."""
    assert _sql_type(Event, "ocurrio") == "TIMESTAMPTZ"


def test_the_plain_declarator_creates_a_timestamp() -> None:
    """`snake_datetime()` emits `TIMESTAMP`, with no zone."""
    assert _sql_type(Event, "apertura") == "TIMESTAMP"


def test_each_declarator_carries_its_precision() -> None:
    """The fractional-second precision reaches the DDL in both of them."""

    @snake_model(table="decl_precision")
    class ConPrecision(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        al_segundo: SnakeColumn[SnakeUtc] = snake_datetimetz(precision=0)
        al_milis: SnakeColumn[datetime] = snake_datetime(precision=3)

    assert _sql_type(ConPrecision, "al_segundo") == "TIMESTAMPTZ(0)"
    assert _sql_type(ConPrecision, "al_milis") == "TIMESTAMP(3)"


def test_the_tz_declarator_demands_a_snake_utc_annotation() -> None:
    """`snake_datetimetz()` over a bare `datetime` fails AT COMPILE TIME.

    A column with a zone holds an instant, and a plain `datetime` identifies none. If the declarator
    and the annotation were allowed to disagree, one of the two would be lying — which is exactly
    what the guard prevents.
    """

    class Mal:
        id: SnakeColumn[int] = snake_int(primary_key=True)
        cuando: SnakeColumn[datetime] = snake_datetimetz()

    with pytest.raises(SnakeModelDefinitionError, match="SnakeUtc"):
        compile_model(Mal)


def test_the_plain_declarator_refuses_a_snake_utc_annotation() -> None:
    """The parity is demanded in BOTH directions.

    A `SnakeUtc` in a column with no zone would lose its `tzinfo` on the way in, which is the silent
    failure the column guide has been describing from the very start.
    """

    class Mal:
        id: SnakeColumn[int] = snake_int(primary_key=True)
        cuando: SnakeColumn[SnakeUtc] = (
            snake_datetime()
        )  # the declarator WITHOUT a zone: a contradiction

    with pytest.raises(SnakeModelDefinitionError, match="snake_datetimetz"):
        compile_model(Mal)


def test_a_bare_snake_column_on_a_date_is_rejected() -> None:
    """`snake_column()` over a date is an error, and it says which of the two to use instead.

    It is ambiguous: there is no telling whether you want an instant or a wall-clock time, and
    choosing on the user's behalf is exactly what led to EVERYTHING being TIMESTAMPTZ without
    anybody deciding it. Same deal as an `Enum` with no `snake_enum()`.
    """

    class Mal:
        id: SnakeColumn[int] = snake_int(primary_key=True)
        cuando: SnakeColumn[datetime] = (
            snake_column()
        )  # ambiguous: it does not say which column to create

    with pytest.raises(SnakeModelDefinitionError, match="snake_datetimetz"):
        compile_model(Mal)
