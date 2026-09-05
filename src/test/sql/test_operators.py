"""Emission tests for the new operators: IN, IS NULL/IS NOT NULL, LIKE, NOT.

All of them go through emit_value for the column (that is the seam). Values always in params, never
interpolated. Pure, no database.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr, SnakeInList
from snakeorm.sql import emit_condition


class _PositionalDialect(PostgresDialect):
    """A fake dialect with positional placeholders ($1, $2...) so the numbering can be tested."""

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


def test_emit_in_list() -> None:
    """Checks `col IN (%s, %s, %s)`, one placeholder per value and the values landing in params."""
    sql, params = emit_condition(
        SnakeExpr[int](path=("age",)).in_([1, 2, 3]), PostgresDialect()
    )
    assert sql == '"age" IN (%s, %s, %s)'
    assert params == (1, 2, 3)


def test_emit_in_numbers_each_placeholder() -> None:
    """Checks that in a positional dialect every value of the IN gets its own index."""
    sql, _ = emit_condition(
        SnakeExpr[int](path=("age",)).in_([1, 2, 3]), _PositionalDialect()
    )
    assert sql == '"age" IN ($1, $2, $3)'


def test_emit_in_empty_raises() -> None:
    """Checks that an IN with an empty list raises ValueError (invalid SQL on Postgres)."""
    empty = SnakeInList(SnakeExpr(path=("age",)), ())
    with pytest.raises(ValueError, match="An IN needs at least one value"):
        emit_condition(empty, PostgresDialect())


def test_emit_is_null() -> None:
    """Checks `col IS NULL`, with no params."""
    sql, params = emit_condition(
        SnakeExpr[str](path=("username",)).is_null(), PostgresDialect()
    )
    assert sql == '"username" IS NULL'
    assert params == ()


def test_emit_is_not_null() -> None:
    """Checks `col IS NOT NULL`, with no params."""
    sql, params = emit_condition(
        SnakeExpr[str](path=("username",)).is_not_null(), PostgresDialect()
    )
    assert sql == '"username" IS NOT NULL'
    assert params == ()


def test_emit_like_parametrizes_pattern() -> None:
    """Checks `col LIKE %s` with the pattern in params (never interpolated)."""
    sql, params = emit_condition(
        SnakeExpr[str](path=("username",)).like("%an%"), PostgresDialect()
    )
    assert sql == '"username" LIKE %s'
    assert params == ("%an%",)


def test_emit_not_wraps_condition() -> None:
    """Checks that NOT wraps the condition: `NOT (col = %s)`."""
    inner = SnakeExpr[str](path=("username",)) == "Ana"
    sql, params = emit_condition(~inner, PostgresDialect())
    assert sql == 'NOT ("username" = %s)'
    assert params == ("Ana",)


def test_emit_like_value_never_interpolated() -> None:
    """Checks the anti-injection thesis in LIKE too."""
    payload = "%'; DROP TABLE users; --"
    sql, params = emit_condition(
        SnakeExpr[str](path=("u",)).like(payload), PostgresDialect()
    )
    assert "DROP TABLE" not in sql
    assert params == (payload,)
