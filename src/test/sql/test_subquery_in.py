"""Tests for `in_(subquery)`: a scalar subquery as the value of an `IN`.

`SnakeInSubquery` emits `<col> IN (SELECT <column> FROM <table> [WHERE ...])`. The CRITICAL part: the
subquery params are threaded into the numbering of the outer query (positional placeholders depend on
the order). These tests are PURE (no database): they check the SQL and the ORDER of the params,
including a subquery with a WHERE of its own inside an outer query that also filters.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import (
    SnakeAnd,
    SnakeExpr,
    SnakeInSubquery,
    SnakeSubquery,
)
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.sql import emit_condition
from test.scenarios.deep_domain import Maker, Nation


class _PositionalDialect(PostgresDialect):
    """A fake dialect with positional placeholders ($1, $2...) so the numbering can be checked."""

    max_bind_params = 65535

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:  # pragma: no cover - not used here
        raise NotImplementedError

    def placeholder(self, index: int) -> str:
        return f"${index}"

    def quote_ident(self, name: str) -> str:
        return f'"{name}"'

    def map_type(  # pragma: no cover - not used here
        self,
        python_type: object,
        autoincrement: bool = False,
        int_size: object = None,
        max_length: object = None,
        json_storage: object = None,
    ) -> str:
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


def test_in_subquery_emits_select_with_its_own_where() -> None:
    """Checks `<col> IN (SELECT <col> FROM <table> WHERE ...)` with the WHERE value landing in params."""
    sub: SnakeSubquery[int] = SnakeSubquery(
        schema="public",
        name="makers",
        column="nation_id",
        where=SnakeExpr[str](path=("name",)) == "SEAT",
    )
    node = SnakeInSubquery(left=SnakeExpr[int](path=("nation_id",)), subquery=sub)
    sql, params = emit_condition(node, PostgresDialect())
    assert sql == (
        '"nation_id" IN (SELECT "nation_id" FROM "public"."makers" WHERE "name" = %s)'
    )
    assert params == ("SEAT",)


def test_in_subquery_without_where_omits_clause() -> None:
    """Checks that a subquery with no WHERE emits just `SELECT <col> FROM <table>` (with no params)."""
    sub: SnakeSubquery[int] = SnakeSubquery(
        schema="public", name="makers", column="nation_id"
    )
    node = SnakeInSubquery(left=SnakeExpr[int](path=("id",)), subquery=sub)
    sql, params = emit_condition(node, PostgresDialect())
    assert sql == '"id" IN (SELECT "nation_id" FROM "public"."makers")'
    assert params == ()


def test_in_subquery_threads_params_after_outer_filter() -> None:
    """Checks the ORDER of the params: first the outer query's, then the subquery's."""
    sub: SnakeSubquery[int] = SnakeSubquery(
        schema="public",
        name="makers",
        column="nation_id",
        where=SnakeExpr[str](path=("name",)) == "SEAT",
    )
    inq = SnakeInSubquery(left=SnakeExpr[int](path=("id",)), subquery=sub)
    outer = SnakeAnd(parts=(SnakeExpr[int](path=("age",)) > 18, inq))
    sql, params = emit_condition(outer, PostgresDialect())
    assert sql == (
        '("age" > %s AND "id" IN '
        '(SELECT "nation_id" FROM "public"."makers" WHERE "name" = %s))'
    )
    assert params == (18, "SEAT")


def test_in_subquery_positional_numbering_is_continuous() -> None:
    """Checks that with positional placeholders the subquery CONTINUES the outer numbering ($2)."""
    sub: SnakeSubquery[int] = SnakeSubquery(
        schema="public",
        name="makers",
        column="nation_id",
        where=SnakeExpr[str](path=("name",)) == "SEAT",
    )
    inq = SnakeInSubquery(left=SnakeExpr[int](path=("id",)), subquery=sub)
    outer = SnakeAnd(parts=(SnakeExpr[int](path=("age",)) > 18, inq))
    sql, params = emit_condition(outer, _PositionalDialect())
    assert sql == (
        '("age" > $1 AND "id" IN '
        '(SELECT "nation_id" FROM "public"."makers" WHERE "name" = $2))'
    )
    assert params == (18, "SEAT")


def test_in_subquery_value_is_never_interpolated() -> None:
    """Checks the anti-injection thesis: the value of the subquery's WHERE does not show up in the string."""
    payload = "x'; DROP TABLE makers; --"
    sub: SnakeSubquery[int] = SnakeSubquery(
        schema="public",
        name="makers",
        column="nation_id",
        where=SnakeExpr[str](path=("name",)) == payload,
    )
    node = SnakeInSubquery(left=SnakeExpr[int](path=("id",)), subquery=sub)
    sql, params = emit_condition(node, PostgresDialect())
    assert "DROP TABLE" not in sql
    assert params == (payload,)


def test_as_scalar_from_query_builds_the_in_subquery() -> None:
    """Checks the public path: `SnakeQuery(...).as_scalar(col)` + `col.in_(sub)` emits the IN."""
    snake_link()
    sub = SnakeQuery(Maker).filter(Maker.name == "SEAT").as_scalar(Maker.nation_id)
    node = Nation.id.in_(sub)
    sql, params = emit_condition(node, PostgresDialect())
    assert sql == (
        '"id" IN (SELECT "nation_id" FROM "public"."makers" WHERE "name" = %s)'
    )
    assert params == ("SEAT",)
