"""Tests for SnakeQuery: an IMMUTABLE builder that accumulates filters and compiles to (sql, params).

Every method returns a brand new SnakeQuery (it does not mutate). Filters get AND-ed together. The
real execution (against a database) does NOT live here: `to_sql` only compiles, delegating to
emit_select. Pure, no database.
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.query import SnakeQuery


@snake_model(prefix="q")
class _User:
    """A test model registered through @snake_model."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    age: SnakeColumn[int] = snake_int()
    username: SnakeColumn[str] = snake_str()


class _Unregistered:
    """A class with no @snake_model: it is not in the registry."""


def test_query_on_unregistered_model_raises() -> None:
    """Checks that querying a model with no @snake_model raises ValueError."""
    with pytest.raises(ValueError, match="@snake_model"):
        SnakeQuery(_Unregistered)


def test_to_sql_without_filters_is_plain_select() -> None:
    """Checks that with no filters it compiles a SELECT with no WHERE."""
    sql, params = SnakeQuery(_User).to_sql(PostgresDialect())
    assert "WHERE" not in sql
    assert sql.startswith("SELECT ")
    assert params == ()


def test_filter_compiles_where() -> None:
    """Checks that a filter produces the corresponding parameterised WHERE."""
    sql, params = SnakeQuery(_User).filter(_User.age > 18).to_sql(PostgresDialect())
    assert sql.endswith('WHERE "age" > %s')
    assert params == (18,)


def test_filter_is_immutable() -> None:
    """Checks that .filter() does NOT mutate the original query (safe branching)."""
    base = SnakeQuery(_User)
    _ = base.filter(_User.age > 18)
    sql, params = base.to_sql(PostgresDialect())
    assert "WHERE" not in sql
    assert params == ()


def test_chained_filters_are_anded() -> None:
    """Checks that .filter(a).filter(b) combines both conditions with AND."""
    query = SnakeQuery(_User).filter(_User.age > 18).filter(_User.username == "Ana")
    sql, params = query.to_sql(PostgresDialect())
    assert sql.endswith('WHERE ("age" > %s AND "username" = %s)')
    assert params == (18, "Ana")


def test_multiple_conditions_in_one_filter_are_anded() -> None:
    """Checks that .filter(a, b) amounts to an AND of the two."""
    query = SnakeQuery(_User).filter(_User.age > 18, _User.username == "Ana")
    sql, params = query.to_sql(PostgresDialect())
    assert sql.endswith('WHERE ("age" > %s AND "username" = %s)')
    assert params == (18, "Ana")


def test_order_by_bare_column_is_ascending() -> None:
    """Checks that .order_by(col) sorts ascending by default."""
    sql, _ = SnakeQuery(_User).order_by(_User.username).to_sql(PostgresDialect())
    assert sql.endswith('ORDER BY "username" ASC')


def test_order_by_desc_key() -> None:
    """Checks that .order_by(col.desc()) sorts descending."""
    sql, _ = SnakeQuery(_User).order_by(_User.age.desc()).to_sql(PostgresDialect())
    assert sql.endswith('ORDER BY "age" DESC')


def test_limit_and_offset() -> None:
    """Checks that .limit()/.offset() compile a parameterised LIMIT/OFFSET."""
    sql, params = SnakeQuery(_User).limit(10).offset(5).to_sql(PostgresDialect())
    assert sql.endswith("LIMIT %s OFFSET %s")
    assert params == (10, 5)


def test_full_query_composition() -> None:
    """Checks filter + order_by + limit together, with the params in WHERE->LIMIT order."""
    sql, params = (
        SnakeQuery(_User)
        .filter(_User.age > 18)
        .order_by(_User.username)
        .limit(10)
        .to_sql(PostgresDialect())
    )
    assert sql.endswith('WHERE "age" > %s ORDER BY "username" ASC LIMIT %s')
    assert params == (18, 10)


def test_builder_methods_are_immutable() -> None:
    """Checks that order_by/limit do not mutate the original query."""
    base = SnakeQuery(_User)
    _ = base.order_by(_User.username).limit(5)
    sql, params = base.to_sql(PostgresDialect())
    assert "ORDER BY" not in sql
    assert "LIMIT" not in sql
    assert params == ()
