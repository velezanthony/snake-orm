"""Changing the `db_comment` of an existing TABLE has to generate a migration.

The COLUMN one was already diffed by `_column_changed`; the table one was forgotten, and a new
`COMMENT ON TABLE` kept the old value (`makemigrations` said "no changes"). Now the diff compares it
and emits `AlterTableComment`, with its reverse and its gating for SQLite (which has no
`COMMENT ON`).
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import AlterTableComment, diff_schema

_PG = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)


def _table(comentario: str | None) -> SnakeTableInfo:
    """The 'users' table with whatever table comment it is given."""
    return SnakeTableInfo(
        name="users",
        columns=(_ID,),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        db_comment=comentario,
    )


def test_changing_the_table_comment_is_a_migration() -> None:
    """Verifies the diff sees the change and emits `AlterTableComment` with the new comment."""
    ops = diff_schema([_table("viejo")], [_table("nuevo")])
    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, AlterTableComment)
    assert "COMMENT ON TABLE" in op.up_sql(_PG)[0]
    assert "'nuevo'" in op.up_sql(_PG)[0]


def test_the_reverse_restores_the_previous_comment() -> None:
    """Verifies the reverse (down) restores the previous comment, it does not leave the new one."""
    op = AlterTableComment(_table("nuevo"), previous="viejo")
    assert "'viejo'" in op.down_sql(_PG)[0]


def test_the_same_comment_converges() -> None:
    """Verifies an identical comment produces no operations: the autogen has to converge."""
    assert diff_schema([_table("igual")], [_table("igual")]) == []


def test_sqlite_emits_nothing_for_the_comment() -> None:
    """Verifies that on SQLite the operation exists but emits no SQL: there is no `COMMENT ON`."""
    op = AlterTableComment(_table("nuevo"), previous=None)
    assert op.up_sql(SQLiteDialect()) == []
    assert op.down_sql(SQLiteDialect()) == []
