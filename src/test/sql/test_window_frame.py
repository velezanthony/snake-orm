"""The FRAME of a window: `SUM(x) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)`.

WITHOUT A FRAME A WINDOW IS HALF A FEATURE. `over(order_by=...)` gives the running total and nothing
else, because the default frame runs from the start of the partition to the current row. A moving
average, a trailing seven days, a centred window — every one of them needs the frame, and none of
them could be written. The alternative was pulling the rows into Python and averaging there, which is
the exact trade this ORM exists to refuse.

THE SYNTAX IS THE SAME ON THE THREE, measured, so there is no dialect method here: `ROWS BETWEEN 1
PRECEDING AND CURRENT ROW` runs unchanged on PostgreSQL, SQLite 3.53 and MariaDB 11. That is rare
enough in this codebase to be worth stating — most things that look standard are not.

THE OFFSET IS A LITERAL, AND THAT IS MEASURED RATHER THAN LAZY. PostgreSQL and SQLite both accept a
placeholder in the bound; MariaDB does NOT:

    ERROR 1064 (42000): ... near '? PRECEDING AND CURRENT ROW'

So the only portable spelling puts the number in the statement. It is the same shape as the JSON key
path, which is interpolated for the same reason and made safe the same way: the value is an `int`
from Python's own type system, checked non-negative when the bound is BUILT. An integer cannot carry
an injection, and the guard runs before any SQL exists.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeQuery,
    SnakeSession,
    SQLiteDriver,
    snake_auto,
    snake_column,
    snake_model,
    snake_table,
)
from snakeorm.core.exceptions import SnakeUnsupportedFeature, SnakeValueError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions import (
    SNAKE_CURRENT_ROW,
    SnakeFrame,
    snake_following,
    snake_preceding,
    snake_range,
    snake_rows,
    sum_,
)
from snakeorm.expressions.window import SnakeWindow
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.sql.value import emit_value


@snake_model(table="frame_readings")
class _Reading(SnakeModel):
    """A series of measurements: the shape every moving average is computed over."""

    id: SnakeColumn[int] = snake_auto()
    day: SnakeColumn[int] = snake_column()
    amount: SnakeColumn[int] = snake_column()


def _window(frame: SnakeFrame) -> SnakeWindow[int | None]:
    """A trailing sum over the series, with the frame under test."""
    return sum_(_Reading.amount).over(order_by=[_Reading.day.asc()], frame=frame)


def test_a_trailing_window_is_the_shape_nobody_could_write_before() -> None:
    """Seven rows back to here: the moving average, which the default frame cannot express."""
    sql = emit_value(
        _window(snake_rows(snake_preceding(6), SNAKE_CURRENT_ROW)),
        PostgresDialect(),
        [],
        None,
    )
    assert sql == (
        'SUM("amount") OVER (ORDER BY "day" ASC ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)'
    )


def test_the_three_engines_take_the_very_same_frame() -> None:
    """Measured on all three: this clause is genuinely standard, so no dialect gets a say.

    Only the quoting differs, and that is the dialect doing its usual job rather than the frame
    needing a translation.
    """
    frame = snake_rows(snake_preceding(1), SNAKE_CURRENT_ROW)
    postgres = emit_value(_window(frame), PostgresDialect(), [], None)
    sqlite = emit_value(_window(frame), SQLiteDialect(), [], None)
    mysql = emit_value(_window(frame), MySQLDialect(), [], None)
    assert postgres == sqlite
    assert mysql == postgres.replace('"', "`")
    assert "ROWS BETWEEN 1 PRECEDING AND CURRENT ROW" in mysql


def test_an_unbounded_bound_needs_no_number() -> None:
    """`UNBOUNDED PRECEDING` to `UNBOUNDED FOLLOWING`: the whole partition, said explicitly."""
    sql = emit_value(
        _window(snake_rows(snake_preceding(), snake_following())),
        PostgresDialect(),
        [],
        None,
    )
    assert "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING" in sql


def test_a_centred_frame_reaches_forward_too() -> None:
    """Three back and three forward: a smoothing window, which needs FOLLOWING to exist."""
    sql = emit_value(
        _window(snake_rows(snake_preceding(3), snake_following(3))),
        PostgresDialect(),
        [],
        None,
    )
    assert "ROWS BETWEEN 3 PRECEDING AND 3 FOLLOWING" in sql


def test_range_is_offered_as_well_as_rows_because_they_differ_on_ties() -> None:
    """`ROWS` counts rows, `RANGE` counts VALUES: with ties they answer differently.

    Offering only `ROWS` would have been the smaller API and the wrong one — a reader who orders by a
    day with several readings in it means RANGE, and silently giving them ROWS is a wrong answer with
    no error.
    """
    sql = emit_value(
        _window(snake_range(snake_preceding(), SNAKE_CURRENT_ROW)),
        PostgresDialect(),
        [],
        None,
    )
    assert "RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW" in sql


def test_the_offset_consumes_no_parameter_and_that_is_deliberate() -> None:
    """MariaDB rejects a placeholder in a bound, so the only portable spelling is a literal.

    Pinned as a test rather than a comment because it is the one place in the ORM where a number
    reaches the statement, and a future refactor "fixing" it would break one engine of three.
    """
    params: list[object] = []
    emit_value(
        _window(snake_rows(snake_preceding(6), SNAKE_CURRENT_ROW)),
        PostgresDialect(),
        params,
        None,
    )
    assert params == []


def test_a_negative_offset_is_refused_when_the_bound_is_built() -> None:
    """The guard runs before any SQL exists, which is what makes interpolating the number safe."""
    with pytest.raises(SnakeValueError, match="negative"):
        snake_preceding(-1)


def test_a_frame_without_an_order_is_refused_because_it_means_nothing() -> None:
    """`6 PRECEDING` needs an order to be preceding IN. Without one the engine picks, silently."""
    with pytest.raises(SnakeUnsupportedFeature, match="order_by"):
        sum_(_Reading.amount).over(
            frame=snake_rows(snake_preceding(6), SNAKE_CURRENT_ROW)
        )


def test_a_frame_that_ends_before_it_starts_is_refused() -> None:
    """`BETWEEN 1 FOLLOWING AND 2 PRECEDING` is empty by construction: the engine errors, so we do."""
    with pytest.raises(SnakeValueError, match="starts"):
        snake_rows(snake_following(1), snake_preceding(2))


def test_the_engine_computes_the_moving_sum_the_frame_describes() -> None:
    """Emission is half of it: the numbers have to come back right.

    Four readings of 1, 2, 3, 4 with a two-row trailing window: 1, 3, 5, 7. Every one of those is a
    different answer from the running total the default frame would give (1, 3, 6, 10), so this test
    fails if the frame is dropped rather than merely mis-spelled.
    """
    dialect = SQLiteDialect()
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(emit_create_table(snake_table(_Reading), dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    for day, amount in enumerate([1, 2, 3, 4], start=1):
        session.add(_Reading(day=day, amount=amount))
    session.commit()

    rows = session.select(
        SnakeQuery(_Reading).order_by(_Reading.day.asc()),
        _Reading.day,
        _window(snake_rows(snake_preceding(1), SNAKE_CURRENT_ROW)),
    )
    assert [total for _, total in rows] == [1, 3, 5, 7]
