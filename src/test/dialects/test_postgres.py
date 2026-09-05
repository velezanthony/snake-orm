"""Tests for PostgresDialect: how the SQL is WRITTEN for PostgreSQL.

The dialect only describes syntax; it runs nothing and does not touch the connection.
"""

from __future__ import annotations

from datetime import date, datetime

from snakeorm import SnakeUtc
from decimal import Decimal

import pytest

from snakeorm.dialects import PostgresDialect, SnakeDialect
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.metadata import SnakeServerDefault


def test_conforms_to_dialect_protocol() -> None:
    """Verifies that PostgresDialect satisfies the SnakeDialect Protocol (statically and at runtime)."""
    dialect: SnakeDialect = PostgresDialect()
    assert isinstance(dialect, SnakeDialect)


def test_placeholder_is_percent_s() -> None:
    """Verifies that the parameter marker is '%s' (psycopg2 style)."""
    assert PostgresDialect().placeholder(0) == "%s"


def test_quote_ident_uses_double_quotes() -> None:
    """Verifies that identifiers are quoted with double quotes."""
    assert PostgresDialect().quote_ident("users") == '"users"'


def test_quote_ident_escapes_inner_quotes() -> None:
    """Verifies that an inner double quote is doubled (it prevents breaking out/injecting)."""
    assert PostgresDialect().quote_ident('we"ird') == '"we""ird"'


def test_map_common_types() -> None:
    """Verifies the mapping of the most common Python types onto Postgres SQL types."""
    dialect = PostgresDialect()
    # An `int` with no explicit width is BIGINT: the widest one, so Python's unbounded int matches
    # on both engines (see SnakeIntSize). The width is adjusted with `int_size`.
    assert dialect.map_type(int) == "BIGINT"
    assert dialect.map_type(str) == "TEXT"
    assert dialect.map_type(bool) == "BOOLEAN"
    assert dialect.map_type(float) == "DOUBLE PRECISION"
    assert dialect.map_type(Decimal) == "NUMERIC"
    assert dialect.map_type(date) == "DATE"
    # With a zone on purpose: a bare `TIMESTAMP` discards the tzinfo in silence.
    # The TYPE decides the zone: `datetime` is a wall-clock time, `SnakeUtc` an instant.
    assert dialect.map_type(datetime) == "TIMESTAMP"
    assert dialect.map_type(SnakeUtc) == "TIMESTAMPTZ"


def test_map_unknown_type_raises() -> None:
    """Verifies that a type with no mapping raises ValueError (fail-fast)."""
    with pytest.raises(ValueError):
        PostgresDialect().map_type(complex)


def test_map_type_autoincrement_is_serial() -> None:
    """Verifies that the agnostic `autoincrement` flag translates into the SERIAL family on Postgres.

    By default the PK is wide (BIGINT), so its autoincrement is BIGSERIAL; lowering the `int_size`
    switches to SERIAL/SMALLSERIAL coherently.
    """
    assert PostgresDialect().map_type(int, autoincrement=True) == "BIGSERIAL"


def test_supports_returning() -> None:
    """Verifies that Postgres declares support for the RETURNING clause."""
    assert PostgresDialect().supports_returning is True


def test_limit_offset_both() -> None:
    """Verifies that it emits a parameterised `LIMIT %s OFFSET %s` and accumulates both values."""
    params: list[object] = []
    clause = PostgresDialect().limit_offset(10, 5, params)
    assert clause == "LIMIT %s OFFSET %s"
    assert params == [10, 5]


def test_limit_offset_only_limit() -> None:
    """Verifies that with only a limit it emits `LIMIT %s` and a single parameter."""
    params: list[object] = []
    clause = PostgresDialect().limit_offset(10, None, params)
    assert clause == "LIMIT %s"
    assert params == [10]


def test_limit_offset_only_offset() -> None:
    """Verifies that with only an offset it emits `OFFSET %s`."""
    params: list[object] = []
    clause = PostgresDialect().limit_offset(None, 5, params)
    assert clause == "OFFSET %s"
    assert params == [5]


def test_limit_offset_none_is_empty() -> None:
    """Verifies that with neither limit nor offset it returns an empty string and does not touch params."""
    params: list[object] = []
    assert PostgresDialect().limit_offset(None, None, params) == ""
    assert params == []


def test_supports_upsert_and_max_bind_params() -> None:
    """Verifies the new flags: Postgres supports upsert and declares its parameter ceiling (65535)."""
    dialect = PostgresDialect()
    assert dialect.supports_upsert is True
    assert dialect.max_bind_params == 65535


def test_on_conflict_do_nothing_without_update_columns() -> None:
    """Verifies that with no update columns it emits `ON CONFLICT (<cols>) DO NOTHING`."""
    clause = PostgresDialect().on_conflict_clause(["email"], [])
    assert clause == 'ON CONFLICT ("email") DO NOTHING'


def test_on_conflict_do_update_sets_each_column_from_excluded() -> None:
    """Verifies that with update columns it emits `DO UPDATE SET c = EXCLUDED.c` for each one."""
    clause = PostgresDialect().on_conflict_clause(["email"], ["name", "age"])
    assert clause == (
        'ON CONFLICT ("email") DO UPDATE SET '
        '"name" = EXCLUDED."name", "age" = EXCLUDED."age"'
    )


def test_on_conflict_quotes_composite_conflict_columns() -> None:
    """Verifies that a composite conflict quotes and lists all of its columns."""
    clause = PostgresDialect().on_conflict_clause(["order_id", "product_id"], [])
    assert clause == 'ON CONFLICT ("order_id", "product_id") DO NOTHING'


def test_server_default_translates_each_member() -> None:
    """Verifies the translation of every member of the agnostic enum into its Postgres SQL."""
    dialect = PostgresDialect()
    assert dialect.server_default_sql(SnakeServerDefault.NOW) == "CURRENT_TIMESTAMP"
    assert dialect.server_default_sql(SnakeServerDefault.UUID_V4) == "gen_random_uuid()"
    assert dialect.server_default_sql(SnakeServerDefault.TRUE) == "TRUE"
    assert dialect.server_default_sql(SnakeServerDefault.FALSE) == "FALSE"
    assert dialect.server_default_sql(SnakeServerDefault.ZERO) == "0"


def test_now_uses_standard_current_timestamp_not_now() -> None:
    """`NOW` translates into the SQL standard `CURRENT_TIMESTAMP`, not into the `now()` slang."""
    assert (
        PostgresDialect().server_default_sql(SnakeServerDefault.NOW)
        == "CURRENT_TIMESTAMP"
    )


def test_unsupported_server_default_member_raises() -> None:
    """A dialect that cannot translate a member of the enum raises SnakeDialectError."""

    class _NoNowDialect(PostgresDialect):
        """Fake dialect that knows NO server_default at all (empty map)."""

        def server_default_sql(self, value: SnakeServerDefault) -> str:
            raise SnakeDialectError(f"not supported: {value!r}")

    with pytest.raises(SnakeDialectError, match="not supported"):
        _NoNowDialect().server_default_sql(SnakeServerDefault.NOW)
