"""Scalar text and date functions, with the TYPE they hand back.

A single node (`SnakeFuncCall`) covers all nine: every extra node would be one more place where the
emitter, the renderer and `paths()` can forget something, and nine nodes would be nine possible
oversights.

What earns its keep is the type of the result: `snake_length` returns `int` even though its argument
is text, so projecting it types the tuple with no `Any`.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from snakeorm import SnakeUtc
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.base import SnakeDialect
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.expressions import (
    SnakeDatePart,
    SnakeExpr,
    SnakeFuncCall,
    snake_concat,
    snake_date_trunc,
    snake_extract,
    snake_length,
    snake_lower,
    snake_round,
    snake_trim,
    snake_upper,
)
from snakeorm.sql.value import emit_value

_DIALECT = PostgresDialect()
_NAME = SnakeExpr[str](path=("name",))
_CREATED = SnakeExpr[datetime](path=("created_at",))
_PRICE = SnakeExpr[float](path=("price",))


def _sql(value: object) -> tuple[str, tuple[object, ...]]:
    """Emits a value down to `(sql, params)`."""
    params: list[object] = []
    return emit_value(value, _DIALECT, params), tuple(params)


def test_the_text_functions_wrap_their_column() -> None:
    """Checks the one-piece text ones: the name is supplied by the dialect, not by the node."""
    assert _sql(snake_lower(_NAME))[0] == 'LOWER("name")'
    assert _sql(snake_upper(_NAME))[0] == 'UPPER("name")'
    assert _sql(snake_trim(_NAME))[0] == 'TRIM("name")'
    assert _sql(snake_length(_NAME))[0] == 'LENGTH("name")'


def test_concat_takes_columns_and_literals_together() -> None:
    """Checks that the literals of `CONCAT` travel PARAMETERISED, as everywhere else in the ORM."""
    sql, params = _sql(snake_concat(_NAME, " ", _NAME))
    assert sql == 'CONCAT("name", %s, "name")'
    assert params == (" ",)


def test_date_trunc_passes_the_part_as_a_value() -> None:
    """Checks `DATE_TRUNC('month', col)`: the part is a normal argument, and it goes parameterised."""
    sql, params = _sql(snake_date_trunc(SnakeDatePart.MONTH, _CREATED))
    assert sql == 'DATE_TRUNC(%s, "created_at")'
    assert params == ("month",)


def test_extract_uses_its_own_syntax() -> None:
    """THE ODD ONE of the family: `EXTRACT(year FROM col)` is NOT an argument list.

    Forcing it into the common mould would have produced `EXTRACT('year', col)`, which is invalid
    SQL. That is why the emitter handles it apart instead of pretending every function has the same
    shape.
    """
    sql, params = _sql(snake_extract(SnakeDatePart.YEAR, _CREATED))
    assert sql == 'EXTRACT(year FROM "created_at")'
    assert params == ()


def test_round_takes_its_digits() -> None:
    """The second argument of `ROUND`, parameterised — and on Postgres the value gets a CAST.

    Postgres has `ROUND(double precision)` and `ROUND(numeric, int)` and nothing in between, so the
    two-argument form reached the server as `function round(double precision, integer) does not
    exist`. It declares the target in `syntax.round_casts_first_argument_to` and the emitter writes
    a standard `CAST`; the other two engines declare nothing and their SQL is unchanged.

    The digits stay a PARAMETER while the cast is inline, and that split is the point: the type name
    comes from the dialect and can never be user input, the number always is.
    """
    sql, params = _sql(snake_round(_PRICE, 2))
    assert sql == 'ROUND(CAST("price" AS numeric), %s)'
    assert params == (2,)


def test_a_function_composes_like_any_value() -> None:
    """Checks that the result is a VALUE: it compares like any other column."""
    from snakeorm.sql.condition import emit_condition

    sql, params = emit_condition(snake_length(_NAME) > 3, _DIALECT)
    assert sql == 'LENGTH("name") > %s'
    assert params == (3,)


def test_functions_report_the_paths_of_their_arguments() -> None:
    """Checks that the paths surface: without them, a column from another table would not join."""
    deep: SnakeExpr[str] = SnakeExpr(path=("car", "brand", "name"))
    assert snake_lower(deep).paths() == (("car", "brand", "name"),)


def test_an_unknown_function_is_refused_by_the_dialect() -> None:
    """Checks that a name the dialect does not know fails LOUDLY, it does not make up SQL."""

    # An Enum cannot be extended, so the error path is tested with something that is not in the
    # translation table. It is the same guard as map_type and server_default_sql.
    with pytest.raises(
        SnakeDialectError, match="does not know how to translate the function"
    ):
        _DIALECT.function_name("not-a-function")  # type: ignore[arg-type]


def test_the_node_is_reused_for_every_function() -> None:
    """Puts the design on the record: ONE node for all nine, not nine classes."""
    assert isinstance(snake_lower(_NAME), SnakeFuncCall)
    assert isinstance(snake_extract(SnakeDatePart.YEAR, _CREATED), SnakeFuncCall)


@pytest.mark.parametrize(
    "dialect, expected",
    [
        (PostgresDialect(), 'ROUND(CAST("price" AS numeric), %s)'),
        (MySQLDialect(), "ROUND(`price`, %s)"),
        (SQLiteDialect(), 'ROUND("price", ?)'),
    ],
    ids=lambda value: type(value).__name__ if hasattr(value, "quote_ident") else "sql",
)
def test_only_the_engine_that_asks_for_the_cast_gets_it(
    dialect: SnakeDialect, expected: str
) -> None:
    """The OTHER side of the branch, which the Postgres-only test above cannot reach.

    `round_casts_first_argument_to` defaults to `None`, so two engines get exactly the SQL they got
    before. A test that only exercises the engine which DOES cast would pass just as happily if the
    emitter had started casting for everybody — and MySQL reads a bare `CAST(x AS DECIMAL)` as
    `DECIMAL(10,0)`, no decimal places at all, so casting there would silently truncate.

    Asserted without a server on purpose. The engine tests cover this too, and they SKIP when there
    is no database: the branch would be unwatched exactly when the suite still comes out green.
    """
    params: list[object] = []

    assert emit_value(snake_round(_PRICE, 2), dialect, params) == expected
    assert params == [2]


def test_the_date_functions_emit_over_the_orms_own_timestamp() -> None:
    """`EXTRACT` over a `SnakeUtc` column: the SQL, not just the type.

    The typing case pins that the call COMPILES and the engine test pins that it ANSWERS. Neither
    says what comes out, and the emitter treats a `SnakeUtc` column like any other value — which is
    the claim worth writing down, because it is the reason the bounded TypeVar was the whole fix and
    no emission had to change.
    """
    utc_column = SnakeExpr[SnakeUtc](path=("happened_at",))

    sql, params = _sql(snake_extract(SnakeDatePart.YEAR, utc_column))

    assert sql == 'EXTRACT(year FROM "happened_at")'
    assert params == ()
