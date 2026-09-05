"""Adding and subtracting time on a date column: `snake_date_add(Order.created, 30, DAY)`.

THIS IS THE CANONICAL CASE FOR A DIALECT, and until now the ORM did not have it at all. Nothing
about these three spellings resembles the others:

    PostgreSQL   "created" + (30 * INTERVAL '1 day')
    MySQL        DATE_ADD(`created`, INTERVAL 30 DAY)
    SQLite       date("created", 30 || ' days')

Without a declarator the user reaches for `raw()`, writes one engine's spelling, and the model stops
being portable — which is the one thing this ORM exists to prevent. All three were MEASURED to accept
the amount as a PARAMETER, so the rule that values never touch the statement survives intact.

AND THE ENGINES DISAGREE, on calendar units only. Measured, `2026-01-31` plus one month:

    PostgreSQL   2026-02-28     clamps to the end of the month
    MySQL        2026-02-28     clamps
    SQLite       2026-03-03     OVERFLOWS

Two engines agree and the third answers something else in silence, which is the worst shape a
difference takes: whichever engine the developer runs is the one that gets tested. Days, hours,
minutes and seconds are identical on all three — the split is exactly between what a calendar has to
interpret and what is a fixed number of seconds.

So it is DECLARED rather than hidden or emulated. `Cap.CALENDAR_INTERVAL` is a type-fidelity
capability: it never stops the plan, the value goes in and comes back, and the session says once what
the semantics cost. Emulating the clamp in SQLite was the alternative and it is the wrong one — the
ORM would be computing dates itself, in Python, behind an expression that claims to be SQL.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeQuery,
    SnakeSession,
    SQLiteDriver,
    snake_auto,
    snake_column,
    snake_datetime,
    snake_model,
    snake_table,
)
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.capabilities import Cap, Degraded, Full
from snakeorm.expressions import SnakeDatePart, snake_date_add, snake_date_sub
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.sql.value import emit_value


@snake_model(table="datearith_orders")
class _Order(SnakeModel):
    """A date column and a timestamp one: SQLite picks its function from which it is."""

    id: SnakeColumn[int] = snake_auto()
    placed_on: SnakeColumn[date] = snake_column()
    created_at: SnakeColumn[datetime] = snake_datetime()


def test_postgres_multiplies_a_unit_interval_so_the_amount_can_be_a_parameter() -> None:
    """`col + (%s * INTERVAL '1 day')`, and the multiplication is what keeps the value out of the SQL.

    `INTERVAL '30 days'` would mean interpolating 30 into the statement. Measured against the engine:
    the multiplied form takes a placeholder and answers the same date.
    """
    params: list[object] = []
    sql = emit_value(
        snake_date_add(_Order.placed_on, 30, SnakeDatePart.DAY),
        PostgresDialect(),
        params,
        None,
    )
    assert sql == "(\"placed_on\" + (%s * INTERVAL '1 day'))"
    assert params == [30]


def test_mysql_uses_date_add_with_the_unit_as_a_keyword() -> None:
    """MySQL spells the unit as a bare keyword inside the call, and takes the amount as a param."""
    params: list[object] = []
    sql = emit_value(
        snake_date_add(_Order.placed_on, 30, SnakeDatePart.DAY),
        MySQLDialect(),
        params,
        None,
    )
    assert sql == "DATE_ADD(`placed_on`, INTERVAL %s DAY)"
    assert params == [30]


def test_sqlite_builds_the_modifier_string_without_interpolating_the_amount() -> None:
    """SQLite takes a TEXT modifier, so the amount is concatenated in SQL — never in Python."""
    params: list[object] = []
    sql = emit_value(
        snake_date_add(_Order.placed_on, 30, SnakeDatePart.DAY),
        SQLiteDialect(),
        params,
        None,
    )
    assert sql == "date(\"placed_on\", ? || ' days')"
    assert params == [30]


def test_sqlite_keeps_the_time_when_the_column_carries_one() -> None:
    """`date()` would TRUNCATE a timestamp, so the compiled type of the column picks the function.

    This is what the type stamped on the expression buys beyond integer division: SQLite has no date
    type to inspect, so without the compiled type the emitter would have to guess, and guessing wrong
    here silently drops the clock.
    """
    on_a_timestamp = emit_value(
        snake_date_add(_Order.created_at, 2, SnakeDatePart.HOUR),
        SQLiteDialect(),
        [],
        None,
    )
    assert on_a_timestamp == "datetime(\"created_at\", ? || ' hours')"


def test_subtracting_is_adding_a_negative_amount() -> None:
    """One node, not two: the sign lives in the VALUE, which is what all three engines accept."""
    params: list[object] = []
    sql = emit_value(
        snake_date_sub(_Order.placed_on, 7, SnakeDatePart.DAY),
        PostgresDialect(),
        params,
        None,
    )
    assert sql == "(\"placed_on\" + (%s * INTERVAL '1 day'))"
    assert params == [-7]


def test_a_quarter_is_refused_by_name_because_no_engine_spells_it() -> None:
    """`SnakeDatePart` is shared with DATE_TRUNC, where a quarter is real. As an interval it is not.

    Refusing by name beats a second near-identical enum: two tables of one thing drift, and the one
    that drifts is the one with fewer readers.
    """
    with pytest.raises(SnakeUnsupportedFeature, match="QUARTER"):
        snake_date_add(_Order.placed_on, 1, SnakeDatePart.QUARTER)


def test_the_calendar_divergence_is_declared_and_not_hidden() -> None:
    """SQLite overflows where the other two clamp, so it says so in the catalogue.

    Days are NOT covered by this: a day is a fixed span and the three agree on it. What a calendar has
    to interpret — months and years — is the whole of the difference.
    """
    postgres = PostgresDialect().capabilities.support_for(Cap.CALENDAR_INTERVAL)
    mysql = MySQLDialect().capabilities.support_for(Cap.CALENDAR_INTERVAL)
    assert isinstance(postgres, Full)
    assert isinstance(mysql, Full)
    degraded = SQLiteDialect().capabilities.support_for(Cap.CALENDAR_INTERVAL)
    assert isinstance(degraded, Degraded)
    assert "2026-03-03" in degraded.reason or "overflow" in degraded.reason.lower()


def test_the_engine_answers_the_date_the_expression_promises() -> None:
    """Emission is half of it: the ENGINE has to return the right rows.

    Two orders thirty days apart, and a filter that only one can satisfy. Run end to end so the
    modifier string, the parameter and the comparison are all proven together.
    """
    dialect = SQLiteDialect()
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(emit_create_table(snake_table(_Order), dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    session.add(
        _Order(placed_on=date(2026, 1, 1), created_at=datetime(2026, 1, 1, 10, 0))
    )
    session.add(
        _Order(placed_on=date(2026, 6, 1), created_at=datetime(2026, 6, 1, 10, 0))
    )
    session.commit()

    # Which orders fall due before March? Only the January one: 1 Jan + 30 days is 31 Jan.
    due = session.all(
        SnakeQuery(_Order).filter(
            snake_date_add(_Order.placed_on, 30, SnakeDatePart.DAY) < date(2026, 3, 1)
        )
    )
    assert [row.placed_on for row in due] == [date(2026, 1, 1)]
