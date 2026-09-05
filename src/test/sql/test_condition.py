"""Tests for the WHERE emitter: SnakeCondition -> a parameterised (sql, params).

The thesis of the project: values are NEVER interpolated into the string. Emission returns
`(sql, params)` and the placeholders are supplied by the dialect. These tests are PURE (no database).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.base import SnakeDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.sql import emit_condition
from snakeorm.sql.condition import emit_condition_into


def _username() -> SnakeExpr[str]:
    """A test expression for the 'username' column."""
    return SnakeExpr(path=("username",))


def _age() -> SnakeExpr[int]:
    """A test expression for the 'age' column."""
    return SnakeExpr(path=("age",))


class _PositionalDialect(PostgresDialect):
    """A fake dialect with positional placeholders ($1, $2...) so the index can be tested.

    PostgresDialect masks the index behind '%s'; this dialect exposes it so we can check that the
    emitter numbers the parameters in order.
    """

    max_bind_params = 65535

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:  # pragma: no cover - not used here
        raise NotImplementedError

    def placeholder(self, index: int) -> str:
        return f"${index}"

    def quote_ident(self, name: str) -> str:
        return f'"{name}"'

    def map_type(
        self,
        python_type: object,
        autoincrement: bool = False,
        int_size: object = None,
        max_length: object = None,
        json_storage: object = None,
    ) -> str:  # pragma: no cover - not used here
        raise NotImplementedError

    def limit_offset(  # pragma: no cover - not used here
        self, limit: int | None, offset: int | None, params: list[object]
    ) -> str:
        raise NotImplementedError

    def literal(self, value: object) -> str:  # pragma: no cover - not used here
        raise NotImplementedError

    def server_default_sql(
        self, value: object
    ) -> str:  # pragma: no cover - not used here
        raise NotImplementedError

    def index_method(self, method: object) -> str:  # pragma: no cover - not used here
        raise NotImplementedError

    def function_name(self, func: object) -> str:  # pragma: no cover - not used here
        raise NotImplementedError


def test_comparison_emits_parametrized_sql() -> None:
    """Checks that a comparison produces `<col> <op> <placeholder>` and the value lands in params."""
    sql, params = emit_condition(_username() == "Ana", PostgresDialect())
    assert sql == '"username" = %s'
    assert params == ("Ana",)


def test_value_is_never_interpolated() -> None:
    """Checks the anti-injection thesis: the value does NOT show up in the SQL string."""
    sql, params = emit_condition(
        _username() == "Ana'; DROP TABLE users; --", PostgresDialect()
    )
    assert "DROP TABLE" not in sql
    assert params == ("Ana'; DROP TABLE users; --",)


def test_and_wraps_parts_in_parens() -> None:
    """Checks that `&` emits `(a AND b)` with the params in order of appearance."""
    condition = (_username() == "Ana") & (_age() > 18)
    sql, params = emit_condition(condition, PostgresDialect())
    assert sql == '("username" = %s AND "age" > %s)'
    assert params == ("Ana", 18)


def test_or_wraps_parts_in_parens() -> None:
    """Checks that `|` emits `(a OR b)`."""
    condition = (_username() == "Ana") | (_username() == "Bob")
    sql, params = emit_condition(condition, PostgresDialect())
    assert sql == '("username" = %s OR "username" = %s)'
    assert params == ("Ana", "Bob")


def test_nested_and_or_preserves_structure_and_order() -> None:
    """Checks nesting (a AND (b OR c)) with the parameters in left-to-right order."""
    condition = (_username() == "Ana") & ((_age() > 18) | (_age() < 5))
    sql, params = emit_condition(condition, PostgresDialect())
    assert sql == '("username" = %s AND ("age" > %s OR "age" < %s))'
    assert params == ("Ana", 18, 5)


def test_placeholder_index_increments_per_param() -> None:
    """Checks that the emitter numbers the placeholders (1-based) by delegating to the dialect."""
    condition = (_username() == "Ana") & (_age() > 18)
    sql, params = emit_condition(condition, _PositionalDialect())
    assert sql == '("username" = $1 AND "age" > $2)'
    assert params == ("Ana", 18)


def test_unknown_node_raises_type_error() -> None:
    """Checks that an unknown condition node raises TypeError (no garbage gets emitted)."""
    from snakeorm.expressions import SnakeCondition

    with pytest.raises(TypeError):
        emit_condition(SnakeCondition(), PostgresDialect())


def test_emit_into_continues_placeholder_numbering() -> None:
    """Checks that emit_condition_into numbers the placeholders CONTINUING from earlier params.

    That is what allows combining SET + WHERE (UPDATE) with no index collision on positional
    dialects ($1, $2...).
    """
    from snakeorm.sql.condition import emit_condition_into

    params: list[object] = ["ya_estaba"]  # simulates a SET that already consumed $1
    sql = emit_condition_into(_age() > 18, _PositionalDialect(), params)
    assert sql == '"age" > $2'
    assert params == ["ya_estaba", 18]


@pytest.mark.parametrize(
    "dialect, expected",
    [
        (PostgresDialect(), "\"username\" ILIKE %s ESCAPE '\\'"),
        (MySQLDialect(), "LOWER(`username`) LIKE LOWER(%s) ESCAPE '\\\\'"),
        (SQLiteDialect(), "LOWER(\"username\") LIKE LOWER(?) ESCAPE '\\'"),
    ],
    ids=lambda value: type(value).__name__ if hasattr(value, "quote_ident") else "sql",
)
def test_the_case_insensitive_match_takes_the_shape_the_engine_has(
    dialect: SnakeDialect, expected: str
) -> None:
    """One engine has the operator and two get the lowering, decided by `syntax.has_ilike`.

    PURE, and that is the point of putting it here. The choice was asserted only in tests that need
    a live server, and those SKIP when there is none — so the branch that picks between two SQL
    shapes was unwatched in exactly the run that still comes out green. Nothing about choosing a
    spelling needs a database.

    It also pins two things the shape alone would not. The pattern stays a PARAMETER on all three —
    the lowering wraps the placeholder, it does not inline the value: `LOWER(?)`, never
    `LOWER('%ana%')`. And the ESCAPE clause is DOUBLED on MySQL and single on the other two, because
    how to write a backslash inside a literal is the dialect's business: hardcoded as `'\\'` this
    clause was ERROR 1064 there and `startswith`, `contains` and `endswith` did not work at all.
    """
    params: list[object] = []
    sql = emit_condition_into(_username().icontains("ana"), dialect, params)

    assert sql == expected
    assert params == ["%ana%"]
