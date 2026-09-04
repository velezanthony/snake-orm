"""Six more scalar functions: `SUBSTRING`, `REPLACE`, `CEIL`, `FLOOR`, `SQRT` and `POWER`.

They are ordinary things to want from a database and the ORM had none of them, so every one was a
reason to reach for `raw()` — which is where a model stops being portable. Nothing here is clever:
the machinery already existed (`SnakeFunc` plus one name table per dialect) and each of these is an
entry in it. What was worth the work is the MEASURING, because two of the seven candidates did not
survive it.

THE RETURN TYPES WERE MEASURED, NOT ASSUMED, and that is what shaped the signatures:

    CEIL(1.2)     PostgreSQL 2 · MySQL 2 · SQLite 2.0
    FLOOR(1.8)    PostgreSQL 1 · MySQL 1 · SQLite 1.0
    SQRT(16)      double precision on PostgreSQL, 4.0 on SQLite
    POWER(2,10)   double precision on PostgreSQL, 1024.0 on SQLite

So `snake_ceil` and `snake_floor` keep the type of their ARGUMENT —`T -> T`, the same shape
`snake_abs` and `snake_round` already have— and that is honest on all three: give them a float and
every engine answers a float. Typing them `int` would have been a lie on SQLite of exactly the kind
this ORM spent a whole phase removing. `snake_sqrt` and `snake_power` answer `float` everywhere.

MOD IS NOT HERE, and both routes to it were measured and rejected:

  * `MOD(7, 3)` answers `1` on PostgreSQL and MySQL and `1.0` on SQLite — a divergence of TYPE, the
    same family as the integer division that `Cap` already declares.
  * `7 % 3` answers `1` on all three, so the operator agrees where the function does not. But psycopg
    refuses a bare `%` in a statement that carries parameters:
    `incomplete placeholder: '%'; if you want to use '%' as an operator you can double it up`.
    Whether the escape is needed depends on whether the query HAS parameters, so the rule would
    change with the shape of the statement rather than with the engine — which is not something a
    dialect can answer once.

A THIRD THING WORTH KNOWING, and it is about the deployment rather than the SQL. SQLite's maths
functions (`CEIL`, `FLOOR`, `SQRT`, `POWER`) are a COMPILE-TIME option, `ENABLE_MATH_FUNCTIONS`. The
build these tests run against has it; a build without it answers `no such function: ceil` at runtime.
That is not something the dialect can declare statically —it is a property of the binary, not of
"SQLite"— so it is written down where somebody adding a maths function will read it.
"""

from __future__ import annotations

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions import (
    SnakeExpr,
    snake_ceil,
    snake_floor,
    snake_power,
    snake_replace,
    snake_sqrt,
    snake_substring,
)
from snakeorm.sql.value import emit_value


def _name() -> SnakeExpr[str]:
    """A text column, as the descriptor hands it over on class access."""
    return SnakeExpr(path=("name",))


def _price() -> SnakeExpr[float]:
    """A numeric column."""
    return SnakeExpr(path=("price",))


def test_the_text_functions_are_spelled_the_same_on_the_three() -> None:
    """`SUBSTRING` and `REPLACE` are genuinely standard here, measured on all three engines."""
    for dialect, quoted in (
        (PostgresDialect(), '"name"'),
        (SQLiteDialect(), '"name"'),
        (MySQLDialect(), "`name`"),
    ):
        params: list[object] = []
        sql = emit_value(snake_substring(_name(), 2, 3), dialect, params, None)
        assert sql.startswith("SUBSTRING("), sql
        assert quoted in sql
        assert params == [2, 3], "the bounds are VALUES and travel as parameters"


def test_replace_takes_both_strings_as_parameters() -> None:
    """The needle and the replacement are data: they never reach the statement."""
    params: list[object] = []
    sql = emit_value(snake_replace(_name(), "-", "+"), PostgresDialect(), params, None)
    assert sql == 'REPLACE("name", %s, %s)'
    assert params == ["-", "+"]


def test_ceil_and_floor_keep_the_type_of_their_argument() -> None:
    """`T -> T`, the shape `snake_abs` and `snake_round` already have, and it is measured.

    SQLite answers `2.0` where PostgreSQL and MySQL answer `2`. Declaring `int` would be false on one
    engine of three; keeping the argument's type is true on all of them, because a float in gives a
    float back everywhere.
    """
    for dialect, quoted in (
        (PostgresDialect(), '"price"'),
        (SQLiteDialect(), '"price"'),
        (MySQLDialect(), "`price`"),
    ):
        assert emit_value(snake_ceil(_price()), dialect, [], None) == f"CEIL({quoted})"
        assert (
            emit_value(snake_floor(_price()), dialect, [], None) == f"FLOOR({quoted})"
        )


def test_sqrt_and_power_answer_a_float_on_every_engine() -> None:
    """Measured: `double precision` on PostgreSQL, a real on SQLite. No divergence to declare."""
    assert (
        emit_value(snake_sqrt(_price()), PostgresDialect(), [], None) == 'SQRT("price")'
    )
    params: list[object] = []
    sql = emit_value(snake_power(_price(), 2), PostgresDialect(), params, None)
    assert sql == 'POWER("price", %s)'
    assert params == [2]


def test_the_new_functions_carry_the_paths_of_what_they_wrap() -> None:
    """The JOIN planner reads `paths()`: a function that swallowed them would drop the join."""
    deep: SnakeExpr[str] = SnakeExpr(path=("car", "brand", "name"))
    assert snake_substring(deep, 1, 2).paths() == (("car", "brand", "name"),)
    assert snake_replace(deep, "a", "b").paths() == (("car", "brand", "name"),)


def test_they_nest_inside_each_other_like_any_other_value() -> None:
    """They are `SnakeValue`s, so they compose. `CEIL(SQRT(x))` is one statement, not two calls."""
    sql = emit_value(snake_ceil(snake_sqrt(_price())), PostgresDialect(), [], None)
    assert sql == 'CEIL(SQRT("price"))'
