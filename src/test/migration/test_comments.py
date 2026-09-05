"""`COMMENT ON`: `db_comment` had been DEAD metadata since forever.

It was captured in the descriptor, stored in the graph, rendered in the migrations and it even had
tests… but NOBODY emitted the DDL. You declared a comment, you migrated, and in the database there
was nothing. It is the same pattern as the index diff: three of the four points of the contract
closed and the fourth one forgotten, in silence.

A detail of SQL that shapes the design: `COMMENT ON` is a statement OF ITS OWN, not a clause of the
`CREATE TABLE`. So creating a commented table is several statements, not one.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    AlterColumn,
    CreateTable,
    diff_schema,
    emit_column_comment,
    emit_table_comment,
)

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)


def _table(
    *, table_comment: str | None = None, column_comment: str | None = None
) -> SnakeTableInfo:
    """The 'users' table with whatever comments are passed in."""
    return SnakeTableInfo(
        name="users",
        columns=(
            _ID,
            SnakeColumnInfo(name="email", python_type=str, db_comment=column_comment),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        db_comment=table_comment,
    )


def test_table_comment_ddl() -> None:
    """Verifies the `COMMENT ON TABLE`, with the text escaped as a SQL literal."""
    ddl = emit_table_comment(_table(table_comment="Cuentas de user"), _DIALECT)
    assert ddl == 'COMMENT ON TABLE "public"."users" IS \'Cuentas de user\''


def test_column_comment_ddl() -> None:
    """Verifies the `COMMENT ON COLUMN`, qualified with schema and table."""
    table = _table(column_comment="Correo de contacto")
    column = table.get_column("email")
    assert column is not None
    ddl = emit_column_comment(table, column, _DIALECT)
    assert ddl == 'COMMENT ON COLUMN "public"."users"."email" IS \'Correo de contacto\''


def test_a_comment_with_a_quote_is_escaped() -> None:
    """Verifies that a quote in the comment does not break the DDL (the dialect doubles it)."""
    ddl = emit_table_comment(_table(table_comment="Cuentas d'usuari"), _DIALECT)
    assert "'Cuentas d''usuari'" in ddl


def test_removing_a_comment_writes_null() -> None:
    """Verifies that removing the comment emits `IS NULL`, which is how SQL deletes one."""
    ddl = emit_table_comment(_table(), _DIALECT)
    assert ddl.endswith("IS NULL")


def test_create_table_emits_the_comments_as_separate_statements() -> None:
    """Verifies that `CreateTable` emits the CREATE and ALSO its COMMENT ON statements.

    `COMMENT ON` is not a clause of the CREATE TABLE: it is a separate statement, so the operation
    returns several.
    """
    operation = CreateTable(_table(table_comment="Cuentas", column_comment="Correo"))
    statements = operation.up_sql(_DIALECT)

    assert statements[0].startswith("CREATE TABLE")
    assert any(sql.startswith("COMMENT ON TABLE") for sql in statements)
    assert any(sql.startswith("COMMENT ON COLUMN") for sql in statements)


def test_a_table_without_comments_emits_only_the_create() -> None:
    """Verifies that with no comments the migration is not dirtied with useless COMMENT ON."""
    assert CreateTable(_table()).up_sql(_DIALECT) == [
        'CREATE TABLE "public"."users" ("id" BIGINT NOT NULL, "email" TEXT NOT NULL, '
        'PRIMARY KEY ("id"))'
    ]


def test_diff_detects_a_changed_column_comment() -> None:
    """Verifies that changing the comment of a column generates an AlterColumn.

    Before it did not detect it: `_column_changed` did not look at `db_comment`, so editing the
    documentation of a column produced no migration whatsoever.
    """
    operations = diff_schema(
        [_table(column_comment="viejo")], [_table(column_comment="nuevo")]
    )
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_alter_column_emits_the_comment_change() -> None:
    """Verifies that the `AlterColumn` includes its `COMMENT ON COLUMN` and that down reverts it."""
    old = SnakeColumnInfo(name="email", python_type=str, db_comment="viejo")
    new = SnakeColumnInfo(name="email", python_type=str, db_comment="nuevo")
    operation = AlterColumn(_table(), old, new)

    assert any("IS 'nuevo'" in sql for sql in operation.up_sql(_DIALECT))
    assert any("IS 'viejo'" in sql for sql in operation.down_sql(_DIALECT))
