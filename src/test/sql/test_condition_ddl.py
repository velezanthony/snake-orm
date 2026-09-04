"""Emitting a condition for DDL: no placeholders, with the literals WRITTEN into the string.

DDL takes no parameters. A `CHECK (age >= 18)` or the `WHERE` of a partial index are part of the
schema DEFINITION, not of a query: there is nowhere to send a `params`. So the values get formatted
with `dialect.literal`, the same path the DDL `DEFAULT` already uses.

This does NOT reopen the door to SQL injection: no user data comes in here, what comes in are the
literals the programmer wrote in their model, and the escaping is done by the dialect. It is exactly
the same treatment `DEFAULT` and a view definition get.

The AST walk is not duplicated: the parameterised emitter is reused and its placeholders are
substituted in a single forward pass.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.expressions import SnakeExpr
from snakeorm.sql.condition import emit_condition_ddl

_DIALECT = PostgresDialect()
_AGE = SnakeExpr[int](path=("age",))
_NAME = SnakeExpr[str](path=("name",))


def test_a_comparison_inlines_its_literal() -> None:
    """Checks that the value is WRITTEN into the SQL, not passed as a placeholder."""
    assert emit_condition_ddl(_AGE >= 18, _DIALECT) == '"age" >= 18'


def test_no_placeholder_survives_anywhere() -> None:
    """Checks that not a single placeholder survives in a compound, nested condition."""
    condition = ((_AGE > 0) & (_AGE < 150)) | _NAME.is_null()
    ddl = emit_condition_ddl(condition, _DIALECT)

    assert "%s" not in ddl
    assert ddl == '(("age" > 0 AND "age" < 150) OR "name" IS NULL)'


def test_strings_are_escaped_by_the_dialect() -> None:
    """Checks that a single quote inside the literal is escaped by doubling it (the engine's rule)."""
    assert emit_condition_ddl(_NAME == "O'Hara", _DIALECT) == "\"name\" = 'O''Hara'"


def test_a_literal_containing_the_placeholder_token_does_not_break_the_pass() -> None:
    """Checks the sharp case: a literal that CONTAINS '%s' does not throw the substitution off.

    The substitution is a single forward pass and never revisits what it already wrote, so a value
    that looks like a placeholder stays data and is not reinterpreted.
    """
    ddl = emit_condition_ddl((_NAME == "100%s") & (_AGE == 7), _DIALECT)
    assert ddl == '("name" = \'100%s\' AND "age" = 7)'


def test_booleans_and_null_use_sql_spelling() -> None:
    """Checks that the special literals come out in SQL, not in Python (`TRUE`, not `True`)."""
    flag = SnakeExpr[bool](path=("active",))
    assert emit_condition_ddl(flag == True, _DIALECT) == '"active" = TRUE'  # noqa: E712
    assert emit_condition_ddl(_NAME == None, _DIALECT) == '"name" IS NULL'  # noqa: E711


def test_in_list_and_like_inline_every_value() -> None:
    """Checks that an IN writes out every one of its values and a LIKE writes its pattern."""
    assert (
        emit_condition_ddl(_NAME.in_(["a", "b"]), _DIALECT) == "\"name\" IN ('a', 'b')"
    )
    assert emit_condition_ddl(_NAME.like("An%"), _DIALECT) == "\"name\" LIKE 'An%'"


def test_arithmetic_inlines_its_operands() -> None:
    """Checks that literals inside an arithmetic expression get written out too."""
    assert emit_condition_ddl((_AGE + 1) > 3, _DIALECT) == '("age" + 1) > 3'


def test_decimal_keeps_its_precision() -> None:
    """Checks that a Decimal does not go through float: in money DDL that would be a disaster."""
    price = SnakeExpr[Decimal](path=("price",))
    assert emit_condition_ddl(price >= Decimal("9.99"), _DIALECT) == '"price" >= 9.99'


def test_a_value_the_dialect_cannot_write_fails_loudly() -> None:
    """Checks that a literal the dialect cannot format is rejected LOUDLY, instead of slipping through mis-written."""
    from datetime import datetime

    moment = SnakeExpr[datetime](path=("created_at",))
    with pytest.raises(
        SnakeDialectError, match="PostgresDialect does not know how to format"
    ):
        emit_condition_ddl(moment > datetime(2026, 1, 1), _DIALECT)
