"""Tests of the widened diff: it detects `unique` and `default` changes on an existing column.

Before, the diff only looked at type/nullable; a change of unique or of default went unnoticed.
Here it is verified that the diff detects them (AlterColumn) and that AlterColumn emits the right
DDL (ADD/DROP CONSTRAINT UNIQUE, SET/DROP DEFAULT), with its reverse.
"""

from __future__ import annotations

from snakeorm import SnakeUtc
from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeServerDefault,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AlterColumn,
    diff_schema,
    emit_alter_column,
    emit_create_table,
)


def _table(*extra: SnakeColumnInfo) -> SnakeTableInfo:
    """The 'users' table with 'id' + the given extra columns."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="users",
        columns=(id_col, *extra),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def test_diff_detects_unique_change() -> None:
    """Turning a column from non-unique to unique produces an AlterColumn."""
    before = _table(SnakeColumnInfo(name="email", python_type=str))
    after = _table(SnakeColumnInfo(name="email", python_type=str, unique=True))
    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_diff_detects_default_change() -> None:
    """Adding a default to an existing column produces an AlterColumn."""
    before = _table(SnakeColumnInfo(name="age", python_type=int))
    after = _table(
        SnakeColumnInfo(name="age", python_type=int, default=18, has_default=True)
    )
    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_emit_add_unique_constraint() -> None:
    """The AlterColumn to unique emits ADD CONSTRAINT ... UNIQUE with a deterministic name."""
    old = SnakeColumnInfo(name="email", python_type=str)
    new = SnakeColumnInfo(name="email", python_type=str, unique=True)
    statements = emit_alter_column(_table(), old, new, PostgresDialect())
    assert statements == [
        'ALTER TABLE "public"."users" ADD CONSTRAINT "uq_users_email" UNIQUE ("email")'
    ]


def test_emit_drop_unique_constraint() -> None:
    """Removing unique emits DROP CONSTRAINT with the SAME deterministic name."""
    old = SnakeColumnInfo(name="email", python_type=str, unique=True)
    new = SnakeColumnInfo(name="email", python_type=str)
    statements = emit_alter_column(_table(), old, new, PostgresDialect())
    assert statements == [
        'ALTER TABLE "public"."users" DROP CONSTRAINT "uq_users_email"'
    ]


def test_emit_set_default() -> None:
    """Adding a default emits SET DEFAULT with the literal of the dialect."""
    old = SnakeColumnInfo(name="age", python_type=int)
    new = SnakeColumnInfo(name="age", python_type=int, default=18, has_default=True)
    statements = emit_alter_column(_table(), old, new, PostgresDialect())
    assert statements == [
        'ALTER TABLE "public"."users" ALTER COLUMN "age" SET DEFAULT 18'
    ]


def test_emit_drop_default() -> None:
    """Removing the default emits DROP DEFAULT."""
    old = SnakeColumnInfo(name="age", python_type=int, default=18, has_default=True)
    new = SnakeColumnInfo(name="age", python_type=int)
    statements = emit_alter_column(_table(), old, new, PostgresDialect())
    assert statements == [
        'ALTER TABLE "public"."users" ALTER COLUMN "age" DROP DEFAULT'
    ]


def test_alter_column_unique_reverses() -> None:
    """The reverse (down) of a change to unique undoes it (DROP CONSTRAINT)."""
    old = SnakeColumnInfo(name="email", python_type=str)
    new = SnakeColumnInfo(name="email", python_type=str, unique=True)
    operation = AlterColumn(_table(), old, new)
    assert "ADD CONSTRAINT" in operation.up_sql(PostgresDialect())[0]
    assert "DROP CONSTRAINT" in operation.down_sql(PostgresDialect())[0]


def test_diff_detects_server_default_change() -> None:
    """Adding a server_default to an existing column produces an AlterColumn."""
    before = _table(SnakeColumnInfo(name="created_at", python_type=SnakeUtc))
    after = _table(
        SnakeColumnInfo(
            name="created_at",
            python_type=SnakeUtc,
            server_default=SnakeServerDefault.NOW,
        )
    )
    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_diff_detects_server_default_sql_change() -> None:
    """A change in the `server_default_sql` escape hatch is detected too (AlterColumn)."""
    before = _table(SnakeColumnInfo(name="x", python_type=int))
    after = _table(SnakeColumnInfo(name="x", python_type=int, server_default_sql="42"))
    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_emit_set_server_default_via_dialect() -> None:
    """The AlterColumn to server_default emits SET DEFAULT with the SQL the dialect translates."""

    old = SnakeColumnInfo(name="created_at", python_type=SnakeUtc)
    new = SnakeColumnInfo(
        name="created_at",
        python_type=SnakeUtc,
        server_default=SnakeServerDefault.NOW,
    )
    statements = emit_alter_column(_table(), old, new, PostgresDialect())
    assert statements == [
        'ALTER TABLE "public"."users" ALTER COLUMN "created_at" '
        "SET DEFAULT CURRENT_TIMESTAMP"
    ]


def test_create_table_emits_server_default() -> None:
    """The CREATE TABLE emits the DEFAULT translated by the dialect (enum) and the raw one as is."""

    created = SnakeColumnInfo(
        name="created_at",
        python_type=SnakeUtc,
        server_default=SnakeServerDefault.NOW,
    )
    raw = SnakeColumnInfo(name="tag", python_type=str, server_default_sql="'x'")
    ddl = emit_create_table(_table(created, raw), PostgresDialect())
    assert '"created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP' in ddl
    assert "\"tag\" TEXT NOT NULL DEFAULT 'x'" in ddl


def test_emit_type_and_default_change_together() -> None:
    """A simultaneous change of type and default emits BOTH statements, in order."""
    old = SnakeColumnInfo(name="v", python_type=int)
    new = SnakeColumnInfo(name="v", python_type=str, default="x", has_default=True)
    statements = emit_alter_column(_table(), old, new, PostgresDialect())
    assert statements == [
        'ALTER TABLE "public"."users" ALTER COLUMN "v" TYPE TEXT USING "v"::TEXT',
        'ALTER TABLE "public"."users" ALTER COLUMN "v" SET DEFAULT \'x\'',
    ]
