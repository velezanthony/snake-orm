"""Tests for the INSERT emitters: emit_insert, emit_insert_many and emit_upsert.

Values ALWAYS travel in params, never in the string. RETURNING is decided by the dialect
(supports_returning) and it lists ALL the columns of the table (so the values the server produced
come back: an autoincrement PK, a DEFAULT now()...). The upsert's conflict resolution is translated
by the dialect (on_conflict_clause). Pure, no database.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.sql import emit_insert, emit_insert_many, emit_upsert


def _table() -> SnakeTableInfo:
    """The 'users' table, with a simple PK on 'id'."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    name_col = SnakeColumnInfo(name="username", python_type=str)
    return SnakeTableInfo(
        name="users",
        columns=(id_col, name_col),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def _composite_table() -> SnakeTableInfo:
    """A table with a composite PK (order_id, product_id), to test a multi-column RETURNING."""
    a = SnakeColumnInfo(name="order_id", python_type=int)
    b = SnakeColumnInfo(name="product_id", python_type=int)
    return SnakeTableInfo(
        name="order_items",
        columns=(a, b),
        primary_key=SnakePrimaryKeyInfo(columns=(a, b)),
    )


class _NoReturningDialect(PostgresDialect):
    """A fake dialect that does NOT support RETURNING, to check that the clause is left out."""

    supports_returning = False
    max_bind_params = 65535

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
    ) -> str:  # pragma: no cover
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

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:
        cols = ", ".join(f'"{c}"' for c in conflict_columns)
        if not update_columns:
            return f"ON CONFLICT ({cols}) DO NOTHING"
        sets = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_columns)
        return f"ON CONFLICT ({cols}) DO UPDATE SET {sets}"


def test_insert_emits_columns_placeholders_and_params() -> None:
    """Checks the quoted columns, the placeholders and the values in params (order preserved)."""
    sql, params = emit_insert(_table(), PostgresDialect(), {"id": 1, "username": "Ana"})
    assert sql == (
        'INSERT INTO "public"."users" ("id", "username") '
        'VALUES (%s, %s) RETURNING "id", "username"'
    )
    assert params == (1, "Ana")


def test_insert_returns_all_columns_when_dialect_supports_it() -> None:
    """Checks that the RETURNING lists ALL the columns of the table, not just the PK.

    That way a column with a server-side DEFAULT (not included in the INSERT) makes it back to the instance.
    """
    sql, _ = emit_insert(_table(), PostgresDialect(), {"username": "Ana"})
    assert sql.endswith('RETURNING "id", "username"')


def test_insert_omits_returning_when_unsupported() -> None:
    """Checks that if the dialect does not support RETURNING, the clause does not show up."""
    sql, _ = emit_insert(_table(), _NoReturningDialect(), {"username": "Ana"})
    assert "RETURNING" not in sql


def test_insert_placeholder_index_increments() -> None:
    """Checks that the placeholders are numbered (1-based) by delegating to the dialect."""
    sql, _ = emit_insert(_table(), _NoReturningDialect(), {"id": 1, "username": "Ana"})
    assert "VALUES ($1, $2)" in sql


def test_insert_value_is_never_interpolated() -> None:
    """Checks the anti-injection thesis: the value does not show up in the string."""
    payload = "Ana'); DROP TABLE users; --"
    sql, params = emit_insert(_table(), PostgresDialect(), {"username": payload})
    assert "DROP TABLE" not in sql
    assert params == (payload,)


def test_insert_with_no_values_emits_default_values_not_an_error() -> None:
    """Inserting with no client values emits `DEFAULT VALUES`. It used to blow up, and that was a bug.

    This test used to check the opposite -that it raised `ValueError`- and that assertion encoded the
    bug: a table with only an autoincrement PK could not be inserted into on any engine.
    `DEFAULT VALUES` is the correct SQL and both of them understand it.
    """
    sql, params = emit_insert(_table(), PostgresDialect(), {})

    assert "DEFAULT VALUES" in sql
    assert params == ()


def test_insert_many_emits_one_statement_with_several_value_tuples() -> None:
    """Checks that N rows go in a single INSERT with several `VALUES (...), (...)` and their params."""
    rows = [{"id": 1, "username": "Ana"}, {"id": 2, "username": "Bob"}]
    sql, params = emit_insert_many(_table(), PostgresDialect(), rows)
    assert sql == (
        'INSERT INTO "public"."users" ("id", "username") '
        'VALUES (%s, %s), (%s, %s) RETURNING "id", "username"'
    )
    assert params == (1, "Ana", 2, "Bob")


def test_insert_many_numbers_placeholders_continuously() -> None:
    """Checks that positional placeholders carry on across rows (1..N), without restarting."""
    rows = [{"id": 1, "username": "Ana"}, {"id": 2, "username": "Bob"}]
    sql, _ = emit_insert_many(_table(), _NoReturningDialect(), rows)
    assert "VALUES ($1, $2), ($3, $4)" in sql


def test_insert_many_rejects_rows_with_different_columns() -> None:
    """Checks that rows with different columns break the VALUES and raise SnakeEmitError."""
    rows: list[Mapping[str, object]] = [{"id": 1, "username": "Ana"}, {"id": 2}]
    with pytest.raises(ValueError, match="must have the same columns"):
        emit_insert_many(_table(), PostgresDialect(), rows)


def test_insert_many_empty_rows_raises() -> None:
    """Checks that a bulk INSERT with no rows raises (no empty INSERT gets emitted)."""
    with pytest.raises(ValueError, match="A bulk INSERT needs at least one row"):
        emit_insert_many(_table(), PostgresDialect(), [])


def test_upsert_do_nothing_without_update_columns() -> None:
    """Checks that with no update columns it emits `ON CONFLICT (...) DO NOTHING`."""
    sql, params = emit_upsert(
        _table(),
        PostgresDialect(),
        {"id": 1, "username": "Ana"},
        conflict_columns=["id"],
    )
    assert sql == (
        'INSERT INTO "public"."users" ("id", "username") VALUES (%s, %s) '
        'ON CONFLICT ("id") DO NOTHING RETURNING "id", "username"'
    )
    assert params == (1, "Ana")


def test_upsert_do_update_sets_from_excluded() -> None:
    """Checks that with update columns it emits `DO UPDATE SET c = EXCLUDED.c`."""
    sql, _ = emit_upsert(
        _table(),
        PostgresDialect(),
        {"id": 1, "username": "Ana"},
        conflict_columns=["id"],
        update_columns=["username"],
    )
    assert 'ON CONFLICT ("id") DO UPDATE SET "username" = EXCLUDED."username"' in sql


def test_upsert_empty_conflict_columns_raises() -> None:
    """Checks that an upsert with no conflict columns raises SnakeEmitError."""
    with pytest.raises(ValueError, match="needs at least one conflict column"):
        emit_upsert(_table(), PostgresDialect(), {"id": 1}, conflict_columns=[])


def test_upsert_composite_conflict_lists_all_columns() -> None:
    """Checks that a composite conflict lists every one of its columns in the ON CONFLICT."""
    sql, _ = emit_upsert(
        _composite_table(),
        PostgresDialect(),
        {"order_id": 1, "product_id": 2},
        conflict_columns=["order_id", "product_id"],
    )
    assert 'ON CONFLICT ("order_id", "product_id") DO NOTHING' in sql


def _autoincrement_only_table() -> SnakeTableInfo:
    """A table whose ONLY column is the autoincrement PK. A legitimate schema."""
    idc = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    return SnakeTableInfo(
        name="soloid", columns=(idc,), primary_key=SnakePrimaryKeyInfo(columns=(idc,))
    )


def test_a_row_with_no_client_values_uses_default_values() -> None:
    """Inserting a row with NO client values emits `DEFAULT VALUES`, not an error.

    A table whose only column is the autoincrement PK is a legitimate schema -an entity whose identity
    is its id plus its relations, or one end of an m2m-. `emit_insert` used to blow up with "an INSERT
    needs at least one column with a value", so that model could NOT be inserted on ANY engine.
    `DEFAULT VALUES` is standard SQL that Postgres and SQLite both understand, and it lets the server
    fill in everything (the PK sequence included).
    """
    sql, params = emit_insert(_autoincrement_only_table(), PostgresDialect(), {})

    assert "DEFAULT VALUES" in sql
    assert params == ()
    assert 'RETURNING "id"' in sql, (
        "the autogenerated id has to come back through the RETURNING"
    )
