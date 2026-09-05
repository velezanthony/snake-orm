"""An EXPLICIT conversion of a value's type: `snake_cast(Stock.reserved, float) / Stock.on_hand`.

WITHOUT THIS DECLARATOR THE ORM HAS A DEAD END, and that is the whole reason it exists. The
arithmetic operators are `SnakeValue[T] | T -> SnakeArith[T]`: one single `T` for both sides and for
the result. That is CORRECT — an ORM that silently promoted `int` to `float` would be deciding for
the user — but it only holds up if the explicit route exists. It did not. `column * 1.0` does not
type-check (invariance, and that invariance is what stops nonsense getting through), and there was
no declarator either, so a real division between two integer columns could not be expressed at all.
A type system earns the right to be strict by offering the explicit door, and this is that door.

THE TYPE NAME IS THE DIALECT'S BUSINESS, and this is not ceremony — it was MEASURED, and the naive
version is silently wrong. `CAST(45 AS NUMERIC) / 50` answers `0.9` on PostgreSQL and `0` on SQLite,
because SQLite's NUMERIC affinity collapses an integral value back to an integer. One spelling for
the three engines would have given the right answer on two and a wrong one on the third, without a
word — which is the exact shape of the bug this declarator was written to close.

Measured against the three engines, `45 / 50` cast to float:

    PostgreSQL   CAST(45 AS double precision) / 50  ->  0.9
    SQLite       CAST(45 AS REAL) / 50              ->  0.9      (NUMERIC would give 0)
    MySQL        CAST(45 AS DOUBLE) / 50            ->  0.9

Those three names are ALREADY in each dialect, in the table `json_get_sql` reads. This declarator
reuses that table rather than opening a second one: two tables of the same thing drift, and the one
that drifts is the one with fewer readers.

THE WHITELIST REFUSES BY NAME. A type nobody has written a cast for is rejected at the CALL SITE, not
at emission — the same decision `json_get` already takes, and for the same reason: the alternative is
emitting SQL the engine rejects and letting the driver explain a decision this ORM made.
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
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions import SnakeExpr, snake_cast
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.sql.value import emit_value


@snake_model(table="cast_pairs")
class _Pair(SnakeModel):
    """A stock pair holding 45 of 50 reserved: the numbers the whole file was measured on."""

    id: SnakeColumn[int] = snake_auto()
    reserved: SnakeColumn[int] = snake_column()
    on_hand: SnakeColumn[int] = snake_column()


def _reserved() -> SnakeExpr[int]:
    """An integer column, as the descriptor hands it over on class access."""
    return SnakeExpr(path=("reserved",))


def test_postgres_spells_the_float_cast_its_own_way() -> None:
    """PostgreSQL casts to `double precision`, the name its own type table already holds."""
    params: list[object] = []
    sql = emit_value(snake_cast(_reserved(), float), PostgresDialect(), params, None)
    assert sql == 'CAST("reserved" AS double precision)'
    assert params == []


def test_sqlite_casts_to_real_and_not_to_numeric() -> None:
    """SQLite needs REAL: measured, `CAST(45 AS NUMERIC)/50` answers 0, not 0.9.

    This is the test that stops the tempting shortcut of one spelling for the three engines.
    """
    params: list[object] = []
    sql = emit_value(snake_cast(_reserved(), float), SQLiteDialect(), params, None)
    assert sql == 'CAST("reserved" AS REAL)'
    assert "NUMERIC" not in sql


def test_mysql_casts_to_double() -> None:
    """MySQL spells it DOUBLE, and quotes the identifier with backticks like everything else."""
    params: list[object] = []
    sql = emit_value(snake_cast(_reserved(), float), MySQLDialect(), params, None)
    assert sql == "CAST(`reserved` AS DOUBLE)"


def test_cast_to_int_truncates_and_says_so_in_each_engine() -> None:
    """The other direction, which is what makes this a cast and not a float helper."""
    for dialect, expected in (
        (PostgresDialect(), 'CAST("reserved" AS integer)'),
        (SQLiteDialect(), 'CAST("reserved" AS INTEGER)'),
        (MySQLDialect(), "CAST(`reserved` AS SIGNED)"),
    ):
        params: list[object] = []
        assert (
            emit_value(snake_cast(_reserved(), int), dialect, params, None) == expected
        )


def test_a_cast_carries_the_paths_of_what_it_wraps() -> None:
    """The JOIN planner reads `paths()`: a cast that swallowed them would drop the join.

    A cast adds no navigation of its own, so it propagates exactly what it wraps.
    """
    deep: SnakeExpr[int] = SnakeExpr(path=("car", "brand", "founded"))
    assert snake_cast(deep, float).paths() == (("car", "brand", "founded"),)


def test_a_type_nobody_can_cast_is_refused_by_name_at_the_call_site() -> None:
    """A whitelist, not a mapping with a fallback: the refusal names the type and the alternatives."""
    with pytest.raises(SnakeUnsupportedFeature) as caught:
        snake_cast(_reserved(), dict)
    message = str(caught.value)
    assert "dict" in message
    assert "float" in message


def test_str_is_refused_rather_than_quietly_doing_nothing() -> None:
    """`str` is the trap: `json_get` lists it as castable because `->>` ALREADY returns text there.

    Here there is no `->>`. Accepting `str` and emitting the source unchanged would answer an
    integer to someone who asked for text, which is worse than refusing.
    """
    with pytest.raises(SnakeUnsupportedFeature, match="no cast to 'str'"):
        snake_cast(_reserved(), str)


def test_the_cast_is_what_makes_a_real_division_expressible() -> None:
    """The end this declarator was written for: two integer columns, one decimal answer.

    BOTH SIDES ARE CAST, and that is not verbosity for its own sake — it is the invariance holding.
    `__truediv__` is `SnakeValue[T] | T -> SnakeArith[T]`, ONE `T` for both operands, so casting the
    left alone leaves `SnakeCast[float] / SnakeExpr[int]` and mypy rejects it by name:

        error: Unsupported operand types for / ("SnakeCast[float]" and "SnakeExpr[int]")

    SQL would settle for one side (the engine promotes the other), so the checker is asking for more
    than the engine does. That is the right trade and the same one the whole file rests on: what is
    being declared is that this is DECIMAL arithmetic, and declaring it on one operand only says it
    half way. The alternative — widening the operators so a float on either side promotes the result
    — buys the shorter spelling by loosening the invariance that stops nonsense getting through.
    """
    on_hand: SnakeExpr[int] = SnakeExpr(path=("on_hand",))
    node = snake_cast(_reserved(), float) / snake_cast(on_hand, float)
    params: list[object] = []
    sql = emit_value(node, PostgresDialect(), params, None)
    assert (
        sql
        == '(CAST("reserved" AS double precision) / CAST("on_hand" AS double precision))'
    )
    assert params == []


def test_the_engine_answers_what_the_cast_promises() -> None:
    """Emission is half of it: the ENGINE has to hand back the decimals.

    Run against SQLite on purpose, because it is where the tempting shortcut fails: `CAST(x AS
    NUMERIC)` collapses back to an integer here and would answer `0`, silently, while PostgreSQL
    answered `0.9` to the very same statement.

    45 of 50 is `0.9`, and `0.9 > 0` is true. Without the cast the same expression is integer
    division — `0` — and `0 > 0` is false. The two halves below are the same row and the same
    columns, so what separates them is exactly the cast and nothing else.
    """
    dialect = SQLiteDialect()
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(emit_create_table(snake_table(_Pair), dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    session.add(_Pair(reserved=45, on_hand=50))
    session.commit()

    decimal_division = session.all(
        SnakeQuery(_Pair).filter(
            snake_cast(_Pair.reserved, float) / snake_cast(_Pair.on_hand, float) > 0.0
        )
    )
    assert [row.reserved for row in decimal_division] == [45]

    # The same row, the same columns, no cast: integer division, `0`, and nothing comes back.
    integer_division = session.all(
        SnakeQuery(_Pair).filter(_Pair.reserved / _Pair.on_hand > 0)
    )
    assert integer_division == []
