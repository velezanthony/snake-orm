"""`CASE WHEN`, `COALESCE` and `NULLIF`: the conditional living inside the SQL.

They are VALUES, not conditions: they get compared, projected and aggregated like any other column.
That is why they inherit from `SnakeValue` and not from `SnakeCondition`, and why `count(snake_case(...))`
works with nothing extra.

The type of the result is what earns its keep: `snake_case(..., default=0)` over `int` branches is a
`SnakeValue[int]`, so projecting it types the tuple with no `Any`.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import (
    SnakeExpr,
    snake_case,
    snake_coalesce,
    snake_nullif,
)
from snakeorm.sql.value import emit_value

_DIALECT = PostgresDialect()
_AGE = SnakeExpr[int](path=("age",))
_NAME = SnakeExpr[str](path=("name",))
_NICK = SnakeExpr[str](path=("nick",))


def _sql(value: object) -> tuple[str, tuple[object, ...]]:
    """Emits a value down to `(sql, params)`."""
    params: list[object] = []
    sql = emit_value(value, _DIALECT, params)
    return sql, tuple(params)


def test_a_single_branch_case() -> None:
    """Checks the minimal form: one branch and a default."""
    sql, params = _sql(snake_case((_AGE >= 18, "adulto"), default="menor"))
    assert sql == 'CASE WHEN "age" >= %s THEN %s ELSE %s END'
    assert params == (18, "adulto", "menor")


def test_branches_keep_their_order() -> None:
    """Checks that the order is respected: in a CASE, the FIRST branch that matches wins."""
    sql, params = _sql(
        snake_case((_AGE < 13, "niño"), (_AGE < 18, "adolescente"), default="adulto")
    )
    assert sql.count("WHEN") == 2
    assert params == (13, "niño", 18, "adolescente", "adulto")


def test_a_case_without_default_omits_the_else() -> None:
    """Checks that with no default no ELSE is written: in SQL that already means NULL."""
    sql, _ = _sql(snake_case((_AGE >= 18, "adulto")))
    assert "ELSE" not in sql
    assert sql.endswith("END")


def test_a_case_needs_at_least_one_branch() -> None:
    """Checks that an empty CASE is rejected: there is no valid SQL to emit with zero branches."""
    with pytest.raises(SnakeEmitError, match="A CASE needs at least one branch"):
        _sql(snake_case(default="nothing"))


def test_a_branch_can_return_a_column() -> None:
    """Checks that the result of a branch can be another COLUMN, not just a literal."""
    sql, params = _sql(snake_case((_NICK.is_null(), _NAME), default=_NICK))
    assert sql == 'CASE WHEN "nick" IS NULL THEN "name" ELSE "nick" END'
    assert params == ()


def test_coalesce_takes_the_first_non_null() -> None:
    """Checks `COALESCE`, which is the most used special case of the conditional."""
    sql, params = _sql(snake_coalesce(_NICK, _NAME, "anónimo"))
    assert sql == 'COALESCE("nick", "name", %s)'
    assert params == ("anónimo",)


def test_coalesce_needs_at_least_two_arguments() -> None:
    """Checks that a single-argument COALESCE is rejected: it chooses nothing, it is the identity."""
    with pytest.raises(SnakeEmitError, match="COALESCE needs at least two arguments"):
        _sql(snake_coalesce(_NICK))


def test_nullif_turns_a_sentinel_into_null() -> None:
    """Checks `NULLIF`, which turns a sentinel value into NULL (the empty string, typically)."""
    sql, params = _sql(snake_nullif(_NAME, ""))
    assert sql == 'NULLIF("name", %s)'
    assert params == ("",)


def test_a_case_is_a_value_so_it_composes() -> None:
    """Checks that a CASE can be compared like any value: that is the proof that it IS a value."""
    condition = snake_case((_AGE >= 18, 1), default=0) == 1
    params: list[object] = []
    from snakeorm.sql.condition import emit_condition_into

    sql = emit_condition_into(condition, _DIALECT, params)
    assert sql.startswith("CASE WHEN")
    assert sql.endswith("END = %s")


def test_the_condition_of_a_branch_can_be_composite() -> None:
    """Checks that the condition of a branch is a full condition, with its ANDs and ORs."""
    sql, params = _sql(
        snake_case(((_AGE >= 18) & (_NAME != ""), "válido"), default="no")
    )
    assert 'CASE WHEN ("age" >= %s AND "name" <> %s) THEN' in sql
    assert params == (18, "", "válido", "no")
