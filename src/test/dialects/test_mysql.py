r"""The MySQL/MariaDB dialect: how the SQL is WRITTEN. Pure, no DB.

MySQL is the third engine and the one that stresses the seam: it does not share several Postgres/SQLite
assumptions (no RETURNING, a different upsert, backticks, non-transactional DDL). These tests pin the
emission down; the round-trip against a real MariaDB lives in `test/integration/`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from snakeorm.dialects import MySQLDialect
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects.capabilities import Cap, Degraded
from snakeorm.expressions.scalar import SnakeFunc
from snakeorm.metadata import (
    SnakeDecimalParams,
    SnakeIntParams,
    SnakeStrParams,
    SnakeIndexMethod,
    SnakeIntSize,
)

_D = MySQLDialect()


def test_identifiers_are_quoted_with_backticks() -> None:
    """Verifies MySQL's quoting: backticks, with the inner ones doubled."""
    assert _D.quote_ident("users") == "`users`"
    assert _D.quote_ident("we`ird") == "`we``ird`"


def test_placeholder_is_percent_s() -> None:
    """Verifies that the placeholder is `%s` (the format paramstyle of PyMySQL/mysqlclient)."""
    assert _D.placeholder(1) == "%s"


def test_map_common_types() -> None:
    """Verifies the mapping of the Python types onto MySQL's."""
    assert _D.map_type(int) == "BIGINT"  # the widest one by default
    assert (
        _D.map_type(int, params=SnakeIntParams(size=SnakeIntSize.INTEGER)) == "INT"
    )  # INT, not INTEGER
    assert (
        _D.map_type(int, params=SnakeIntParams(size=SnakeIntSize.SMALLINT))
        == "SMALLINT"
    )
    assert _D.map_type(str) == "TEXT"
    assert _D.map_type(str, params=SnakeStrParams(max_length=50)) == "VARCHAR(50)"
    assert _D.map_type(bool) == "TINYINT(1)"  # MySQL has no native BOOLEAN
    assert _D.map_type(float) == "DOUBLE"
    # `Decimal` is not asserted here on purpose: it has no single answer, and the version of this
    # line that claimed one (`== "DECIMAL"`) was pinning the bug. Both of its paths — declared and
    # refused — have their own test below.
    assert (
        _D.map_type(datetime) == "DATETIME(6)"
    )  # (6) or the microseconds would be truncated
    assert _D.map_type(UUID) == "CHAR(36)"  # no native UUID
    assert _D.map_type(dict) == "JSON"


def test_autoincrement_uses_the_auto_increment_keyword() -> None:
    """Verifies that the autoincrement is `<type> AUTO_INCREMENT`, not a SERIAL type like Postgres."""
    assert _D.map_type(int, autoincrement=True) == "BIGINT AUTO_INCREMENT"
    assert (
        _D.map_type(
            int, autoincrement=True, params=SnakeIntParams(size=SnakeIntSize.INTEGER)
        )
        == "INT AUTO_INCREMENT"
    )


def test_timedelta_and_arrays_fall_back_to_text_and_say_what_is_lost() -> None:
    """Verifies that what MySQL does not have falls back to TEXT and stays DECLARED as degraded.

    Both used to be refused, and that made the same model unusable across the three engines: a
    duration or list column only existed on Postgres. Refusing was the right call while there was no
    way to tell what gets lost; with the catalog there is one.

    What is checked here is that the fallback is NOT silent. Storing in TEXT and keeping quiet would
    trade a loud error for a surprise, which is worse: the ORM shouts, it does not fix things on its own.
    """
    assert _D.map_type(timedelta) == "TEXT"
    assert _D.map_type(list[int]) == "TEXT"

    assert isinstance(_D.capabilities.support_for(Cap.INTERVAL), Degraded)
    assert isinstance(_D.capabilities.support_for(Cap.ARRAYS), Degraded)


def test_literal_escapes_the_backslash() -> None:
    """Verifies that a string literal escapes `\\` (MySQL interprets it, unlike Postgres)."""
    assert _D.literal("a\\b") == "'a\\\\b'"
    assert _D.literal("O'Hara") == "'O''Hara'"
    assert _D.literal(True) == "1"  # no native TRUE/FALSE
    assert _D.literal(False) == "0"


def test_upsert_uses_on_duplicate_key_update() -> None:
    """Verifies MySQL's upsert: `ON DUPLICATE KEY UPDATE`, not `ON CONFLICT`."""
    clause = _D.on_conflict_clause(["id"], ["name", "qty"])
    assert (
        clause
        == "ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `qty` = VALUES(`qty`)"
    )


def test_upsert_without_update_columns_is_a_no_op_assignment() -> None:
    """Verifies MySQL's "do nothing": there is no DO NOTHING, `col = col` is used instead."""
    assert _D.on_conflict_clause(["id"], []) == "ON DUPLICATE KEY UPDATE `id` = `id`"


def test_date_trunc_is_refused() -> None:
    """Verifies that asking for DATE_TRUNC fails clearly: MySQL does not have it."""
    with pytest.raises(SnakeDialectError, match="DATE_TRUNC|traducir"):
        _D.function_name(SnakeFunc.DATE_TRUNC)


def test_gin_index_method_is_refused() -> None:
    """Verifies that a Postgres index method (GIN) is refused on MySQL."""
    with pytest.raises(
        SnakeDialectError, match="does not know how to translate the index method"
    ):
        _D.index_method(SnakeIndexMethod.GIN)


def test_the_capability_flags_reflect_mysql() -> None:
    """Verifies the flags that define the SHAPE of the plan: no RETURNING, non-transactional DDL, etc."""
    assert (
        _D.supports_returning is False
    )  # the PK comes back through lastrowid, not through RETURNING
    assert _D.supports_transactional_ddl is False  # the DDL does an implicit commit
    assert _D.supports_upsert is True
    assert _D.supports_schemas is False  # "schema" == database on MySQL
    # It DOES comment, and the line here asserted `False` with "it comments inline" written beside
    # it as the justification — the contradiction that let a `db_comment` be dropped on a server
    # that stores it. Commenting inline is a spelling, and `syntax.comment_style` is where a
    # spelling belongs; the capability answers whether the engine can, and it can.
    assert _D.supports_comments is True
    # And that it DOES have caveats to tell the user at startup (zoneless datetime, TINYINT bool...).
    # This used to be `fidelity_warning is not None`, a loose paragraph; now they are catalog entries,
    # so besides existing they can be counted and silenced one by one.
    assert _D.capabilities.caveats() != ()


def test_a_decimal_with_no_declared_precision_is_refused_instead_of_rounded() -> None:
    """`Decimal` with no `snake_decimal(...)` STOPS the plan on MySQL, it does not fall to DECIMAL.

    Verified against MariaDB 11.8: a bare `DECIMAL` column is `decimal(10,0)`, so `9.99` is stored
    and read back as `10`. Money silently turned into an integer — the one outcome this ORM says it
    never produces.

    Postgres is not affected and that is the whole reason MySQL has to speak up: its `NUMERIC` with
    no parameters is arbitrary precision, so the same model is lossless there and lossy here. An
    engine difference that a `Degraded` cannot cover, because what is lost is not a query capability
    but the VALUE.

    It stops rather than picking a default: any default this dialect invented would be a number
    nobody declared, and a wrong guess about the scale of money is the same data loss with an
    author. `DECIMAL(10,0)` was already such a guess — MySQL's, not the model's.
    """
    dialect = MySQLDialect()

    with pytest.raises(SnakeDialectError) as error:
        dialect.map_type(Decimal)

    assert "snake_decimal" in str(error.value), (
        f"the refusal must name the specifier that fixes it; it said: {error.value}"
    )


def test_a_decimal_that_declares_its_precision_maps_as_before() -> None:
    """The declared path is untouched: `snake_decimal(12, 2)` is still `DECIMAL(12,2)`.

    The pair matters. Refusing the undeclared case is only correct if the declared one keeps
    working; otherwise the fix would just be a different way of breaking MySQL.
    """
    dialect = MySQLDialect()

    assert (
        dialect.map_type(Decimal, params=SnakeDecimalParams(precision=12, scale=2))
        == "DECIMAL(12,2)"
    )
