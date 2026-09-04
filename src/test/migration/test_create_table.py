"""Tests of emit_create_table: SnakeTableInfo -> CREATE TABLE DDL.

The SQL type comes from the dialect (map_type). NOT NULL if the column is not nullable; UNIQUE if
it declares it; PRIMARY KEY (simple or composite) as a constraint. The DDL is NOT parameterized
(it is schema, not user data).
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import emit_create_table, emit_drop_table


def test_create_table_columns_types_and_pk() -> None:
    """Verifies quoted columns with their SQL type, NOT NULL and the PK constraint."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    name_col = SnakeColumnInfo(name="username", python_type=str)
    table = SnakeTableInfo(
        name="users",
        columns=(id_col, name_col),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    ddl = emit_create_table(table, PostgresDialect())
    assert ddl == (
        'CREATE TABLE "public"."users" '
        '("id" BIGINT NOT NULL, "username" TEXT NOT NULL, PRIMARY KEY ("id"))'
    )


def test_nullable_column_omits_not_null() -> None:
    """Verifies that a nullable column (| None) carries no NOT NULL."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    age_col = SnakeColumnInfo(name="age", python_type=int, nullable=True)
    table = SnakeTableInfo(
        name="people",
        columns=(id_col, age_col),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    ddl = emit_create_table(table, PostgresDialect())
    assert '"age" BIGINT,' in ddl
    assert '"age" BIGINT NOT NULL' not in ddl


def test_unique_column() -> None:
    """Verifies that a unique column adds its constraint WITH A NAME OF ITS OWN.

    Never a bare inline `UNIQUE`: Postgres would auto-name it `{table}_{column}_key` and the later
    `ALTER TABLE ... DROP CONSTRAINT` would look for another name and fail.
    """
    id_col = SnakeColumnInfo(name="id", python_type=int)
    code_col = SnakeColumnInfo(name="iso_code", python_type=str, unique=True)
    table = SnakeTableInfo(
        name="countries",
        columns=(id_col, code_col),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    ddl = emit_create_table(table, PostgresDialect())
    assert '"iso_code" TEXT NOT NULL' in ddl
    assert 'CONSTRAINT "uq_countries_iso_code" UNIQUE ("iso_code")' in ddl


def test_composite_primary_key() -> None:
    """Verifies that a composite PK lists all of its columns in the constraint."""
    a = SnakeColumnInfo(name="order_id", python_type=int)
    b = SnakeColumnInfo(name="product_id", python_type=int)
    table = SnakeTableInfo(
        name="order_items",
        columns=(a, b),
        primary_key=SnakePrimaryKeyInfo(columns=(a, b)),
    )
    ddl = emit_create_table(table, PostgresDialect())
    assert ddl.endswith('PRIMARY KEY ("order_id", "product_id"))')


def test_default_emitted_when_has_default() -> None:
    """Verifies that a column with a default emits DEFAULT with the formatted literal."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    active = SnakeColumnInfo(
        name="active", python_type=bool, default=True, has_default=True
    )
    label = SnakeColumnInfo(
        name="label", python_type=str, default="n/a", has_default=True
    )
    table = SnakeTableInfo(
        name="flags",
        columns=(id_col, active, label),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    ddl = emit_create_table(table, PostgresDialect())
    assert '"active" BOOLEAN NOT NULL DEFAULT TRUE' in ddl
    assert "\"label\" TEXT NOT NULL DEFAULT 'n/a'" in ddl


def test_no_default_omits_default_clause() -> None:
    """Verifies that without has_default no DEFAULT is emitted (even if default is None)."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    note = SnakeColumnInfo(name="note", python_type=str, nullable=True, default=None)
    table = SnakeTableInfo(
        name="notes",
        columns=(id_col, note),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    assert "DEFAULT" not in emit_create_table(table, PostgresDialect())


def test_autoincrement_column_emits_serial() -> None:
    """Verifies that an autoincrement column emits BIGSERIAL (the default width), with no redundant NOT NULL/DEFAULT."""
    id_col = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    table = SnakeTableInfo(
        name="tickets",
        columns=(id_col, SnakeColumnInfo(name="title", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    ddl = emit_create_table(table, PostgresDialect())
    assert '"id" BIGSERIAL,' in ddl
    assert '"id" BIGSERIAL NOT NULL' not in ddl


def test_drop_table() -> None:
    """Verifies that emit_drop_table generates the quoted DROP TABLE."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="users",
        columns=(id_col,),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    assert emit_drop_table(table, PostgresDialect()) == 'DROP TABLE "public"."users"'
