"""Tests of emit_create_index and of CreateTable including the indexes in its up_sql."""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import CreateTable, emit_create_index


def _table(indexes: tuple[SnakeIndexInfo, ...] = ()) -> SnakeTableInfo:
    """The 'users' table with the given indexes."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="users",
        columns=(id_col, SnakeColumnInfo(name="email", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
        indexes=indexes,
    )


def test_simple_index_with_default_name() -> None:
    """Verifies a simple index with a default generated name."""
    ddl = emit_create_index(
        _table(), SnakeIndexInfo(columns=("email",)), PostgresDialect()
    )
    assert ddl == 'CREATE INDEX "ix_users_email" ON "public"."users" ("email")'


def test_unique_index_is_declared_as_a_constraint() -> None:
    """Verifies that a unique declaration produces a CONSTRAINT, not a unique index.

    A constraint STATES a domain rule and it is what `ON CONFLICT` and the engine errors point at;
    the unique index is only how it gets implemented (Postgres creates one underneath anyway). So
    `snake_column(unique=True)` and `SnakeIndex(unique=True)` produce THE SAME object.
    """
    ddl = emit_create_index(
        _table(), SnakeIndexInfo(columns=("email",), unique=True), PostgresDialect()
    )
    assert ddl == (
        'ALTER TABLE "public"."users" ADD CONSTRAINT "uq_users_email" UNIQUE ("email")'
    )


def test_composite_index_and_custom_name() -> None:
    """Verifies a composite index with an explicit name."""
    index = SnakeIndexInfo(columns=("email", "id"), name="my_idx")
    ddl = emit_create_index(_table(), index, PostgresDialect())
    assert ddl == 'CREATE INDEX "my_idx" ON "public"."users" ("email", "id")'


def test_create_table_operation_emits_table_then_indexes() -> None:
    """Verifies that CreateTable.up_sql emits the CREATE TABLE and then the CREATE INDEXes."""
    table = _table(indexes=(SnakeIndexInfo(columns=("email",)),))
    statements = CreateTable(table).up_sql(PostgresDialect())
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE")
    assert statements[1].startswith("CREATE INDEX")
