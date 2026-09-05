"""Tests of AlterColumn: type/nullable changes on an existing column (diff + DDL + reverse)."""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    AlterColumn,
    Migration,
    autodetect,
    diff_schema,
    emit_alter_column,
    replay,
)


def _col(name: str, python_type: type, *, nullable: bool = False) -> SnakeColumnInfo:
    """Test column."""
    return SnakeColumnInfo(name=name, python_type=python_type, nullable=nullable)


def _table(*extra: SnakeColumnInfo) -> SnakeTableInfo:
    """The 'users' table with 'id' + the given extra columns."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="users",
        columns=(id_col, *extra),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def test_emit_type_change_uses_using_cast() -> None:
    """Verifies the ALTER COLUMN TYPE with the USING cast."""
    statements = emit_alter_column(
        _table(), _col("age", int), _col("age", str), PostgresDialect()
    )
    assert statements == [
        'ALTER TABLE "public"."users" ALTER COLUMN "age" TYPE TEXT USING "age"::TEXT'
    ]


def test_emit_set_not_null() -> None:
    """Verifies that going from nullable to non-nullable emits SET NOT NULL."""
    statements = emit_alter_column(
        _table(), _col("age", int, nullable=True), _col("age", int), PostgresDialect()
    )
    assert statements == [
        'ALTER TABLE "public"."users" ALTER COLUMN "age" SET NOT NULL'
    ]


def test_emit_drop_not_null() -> None:
    """Verifies that going to nullable emits DROP NOT NULL."""
    statements = emit_alter_column(
        _table(), _col("age", int), _col("age", int, nullable=True), PostgresDialect()
    )
    assert statements == [
        'ALTER TABLE "public"."users" ALTER COLUMN "age" DROP NOT NULL'
    ]


def test_diff_detects_type_change() -> None:
    """Verifies that a type change on an existing column produces an AlterColumn."""
    operations = diff_schema([_table(_col("age", int))], [_table(_col("age", str))])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)
    assert operations[0].new.python_type is str


def test_unchanged_column_yields_nothing() -> None:
    """Verifies that an identical column produces no operations."""
    assert diff_schema([_table(_col("age", int))], [_table(_col("age", int))]) == []


def test_alter_column_reverses() -> None:
    """Verifies that the reverse (down) undoes the type change."""
    operation = AlterColumn(_table(), _col("age", int), _col("age", str))
    assert "TYPE TEXT" in operation.up_sql(PostgresDialect())[0]
    assert "TYPE BIGINT" in operation.down_sql(PostgresDialect())[0]


def test_replay_alter_converges() -> None:
    """Verifies the code-first cycle: create with int, alter to str, and the diff proposes nothing."""
    from snakeorm.migration import CreateTable

    history = [
        Migration("001", (CreateTable(_table(_col("age", int))),)),
        Migration("002", (AlterColumn(_table(), _col("age", int), _col("age", str)),)),
    ]
    state = replay(history)
    assert autodetect(history, [_table(_col("age", str))]) == []
    stored = state.get_table("users")
    assert stored is not None
    assert stored.get_column("age").python_type is str  # type: ignore[union-attr]
