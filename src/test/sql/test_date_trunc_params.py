"""`DATE_TRUNC(part, value)`: the order of the parameters has to follow the TEXTUAL order.

In a positional dialect (Postgres' `%s`, SQLite's `?`) the database matches parameters by POSITION.
The emitter rendered the arguments first (appending their params) and then inserted the `part` at
textual position 0 but with its param at the END: `DATE_TRUNC(%s, COALESCE("ts", %s))` with params
`[default, 'year']`. The 1st `%s` (the part) bound to the default and the 2nd to `'year'`: broken
query.

The fix: the `part` is rendered FIRST, so its param is appended before the arguments' own.
"""

from __future__ import annotations

from datetime import datetime

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import (
    SnakeDatePart,
    SnakeExpr,
    snake_coalesce,
    snake_date_trunc,
)
from snakeorm.sql.value import emit_value


def test_date_trunc_keeps_part_and_arg_params_in_textual_order() -> None:
    """Checks that the part's param comes BEFORE the argument's, as they appear in the string."""
    ts: SnakeExpr[datetime] = SnakeExpr(path=("ts",))
    expr = snake_date_trunc(
        SnakeDatePart.YEAR, snake_coalesce(ts, datetime(2000, 1, 1))
    )
    params: list[object] = []
    sql = emit_value(expr, PostgresDialect(), params)

    assert sql == 'DATE_TRUNC(%s, COALESCE("ts", %s))'
    assert params == [
        "year",
        datetime(2000, 1, 1),
    ]  # part first, default afterwards (not the other way round)
