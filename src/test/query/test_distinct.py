"""Tests of `.distinct()`: it emits `SELECT DISTINCT` both in the full SELECT and in projection.

`.distinct()` is immutable (it returns a new query). Standard SQL `DISTINCT` only; no `DISTINCT ON`
(Postgres slang). Pure, no database: it checks the prefix of the emitted SQL.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.query import SnakeQuery


@snake_model(prefix="dist")
class _Item:
    """Test model for DISTINCT."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    kind: SnakeColumn[str] = snake_str()


def test_distinct_in_full_select() -> None:
    """Checks that `.distinct().to_sql()` emits `SELECT DISTINCT ...` in the full SELECT."""
    sql, _ = SnakeQuery(_Item).distinct().to_sql(PostgresDialect())
    assert sql.startswith("SELECT DISTINCT ")
    assert '"kind"' in sql


def test_distinct_in_projection() -> None:
    """Checks that `.distinct().to_project_sql()` emits `SELECT DISTINCT <cols>` in the projection."""
    sql, _ = (
        SnakeQuery(_Item).distinct().to_project_sql(PostgresDialect(), [_Item.kind])
    )
    assert sql.startswith('SELECT DISTINCT "kind" FROM')


def test_distinct_is_immutable() -> None:
    """Checks that `.distinct()` returns a NEW query and does not mark the original one."""
    base = SnakeQuery(_Item)
    marked = base.distinct()
    assert marked is not base
    sql_base, _ = base.to_sql(PostgresDialect())
    assert "DISTINCT" not in sql_base


def test_without_distinct_the_select_is_plain() -> None:
    """Checks that without `.distinct()` the SELECT comes out with no keyword (backwards compat)."""
    sql, _ = SnakeQuery(_Item).to_sql(PostgresDialect())
    assert sql.startswith("SELECT ")
    assert "DISTINCT" not in sql
