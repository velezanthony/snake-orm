"""Tests for the UPDATE emitter: (table, values, where) -> (sql, params).

It puts SET (like the INSERT does) together with WHERE (reusing emit_condition). The critical part:
the WHERE placeholders CONTINUE the numbering started by the SET, with no collision. Pure, no
database.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.sql import emit_update


def _table() -> SnakeTableInfo:
    """The 'users' table, with a simple PK on 'id'."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="users",
        columns=(id_col, SnakeColumnInfo(name="username", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


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


def test_update_sets_columns_and_where() -> None:
    """Checks the SET with quoted columns and a parameterised WHERE; params SET first, then WHERE."""
    where = SnakeExpr[int](path=("id",)) == 1
    sql, params = emit_update(
        _table(), PostgresDialect(), {"username": "Bob"}, where=where
    )
    assert sql == 'UPDATE "public"."users" SET "username" = %s WHERE "id" = %s'
    assert params == ("Bob", 1)


def test_update_multiple_set_columns_preserves_order() -> None:
    """Checks that several SET columns follow the order of the mapping."""
    values = {"username": "Bob", "email": "b@x.io"}
    sql, params = emit_update(_table(), PostgresDialect(), values)
    assert sql == 'UPDATE "public"."users" SET "username" = %s, "email" = %s'
    assert params == ("Bob", "b@x.io")


def test_update_without_where_omits_clause() -> None:
    """Checks that with no condition no WHERE is emitted (a whole-table UPDATE, valid SQL)."""
    sql, _ = emit_update(_table(), PostgresDialect(), {"username": "Bob"})
    assert "WHERE" not in sql


def test_update_placeholder_numbering_is_continuous() -> None:
    """Checks that the WHERE continues the SET numbering ($1 in the SET, $2 in the WHERE)."""
    where = SnakeExpr[int](path=("id",)) == 1
    sql, params = emit_update(
        _table(), _PositionalDialect(), {"username": "Bob"}, where=where
    )
    assert sql == 'UPDATE "public"."users" SET "username" = $1 WHERE "id" = $2'
    assert params == ("Bob", 1)


def test_update_value_is_never_interpolated() -> None:
    """Checks the anti-injection thesis: the value does not show up in the string."""
    payload = "x'; DROP TABLE users; --"
    sql, params = emit_update(_table(), PostgresDialect(), {"username": payload})
    assert "DROP TABLE" not in sql
    assert params == (payload,)


def test_update_empty_values_raises() -> None:
    """Checks that an UPDATE with no columns in the SET raises ValueError."""
    with pytest.raises(ValueError, match="needs at least one column in the SET"):
        emit_update(_table(), PostgresDialect(), {})
