"""Tests for the SnakeTupleIn node: a parameterised row constructor `(a, b) IN ((..), (..))`.

`SnakeTupleIn` is the N-dimensional version of `SnakeInList`: it compares a TUPLE of columns against
a set of value tuples. It is produced by the select-in of a to-many with a composite FK. These tests
are PURE (no database): they check the SQL and the params with 1 and 2 columns, the alternative
OR-of-ANDs branch for a dialect with no row constructor, and the error on empty `rows`. The thesis
of the project: values are NEVER interpolated into the string.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import SnakeExpr, SnakeTupleIn, SnakeValue
from snakeorm.sql import emit_condition


class _NoRowConstructorDialect(PostgresDialect):
    """A fake dialect with NO row constructor: it forces the equivalent OR-of-ANDs branch."""

    supports_row_constructor = False
    max_bind_params = 65535

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:  # pragma: no cover - not used here
        raise NotImplementedError

    def placeholder(self, index: int) -> str:
        return "%s"

    def quote_ident(self, name: str) -> str:
        return f'"{name}"'

    def map_type(  # pragma: no cover - not used here
        self,
        python_type: object,
        autoincrement: bool = False,
        int_size: object = None,
        max_length: object = None,
        json_storage: object = None,
    ) -> str:
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


def _cols(*names: str) -> tuple[SnakeValue[object], ...]:
    """Builds the row constructor's columns (SnakeExpr) out of their names."""
    return tuple(SnakeExpr(path=(name,)) for name in names)


def test_two_columns_emit_a_row_constructor() -> None:
    """With two columns and a dialect that supports it: `(a, b) IN ((%s, %s), (%s, %s))`, params in order."""
    node = SnakeTupleIn(
        columns=_cols("region", "code"), rows=(("Nornia", 1), ("Sudmark", 2))
    )
    sql, params = emit_condition(node, PostgresDialect())
    assert sql == '("region", "code") IN ((%s, %s), (%s, %s))'
    assert params == ("Nornia", 1, "Sudmark", 2)


def test_single_column_still_wraps_each_row() -> None:
    """With ONE column it emits `(c) IN ((%s), (%s))`: each row still gets its own parentheses."""
    node = SnakeTupleIn(columns=_cols("region"), rows=(("Nornia",), ("Sudmark",)))
    sql, params = emit_condition(node, PostgresDialect())
    assert sql == '("region") IN ((%s), (%s))'
    assert params == ("Nornia", "Sudmark")


def test_value_is_never_interpolated() -> None:
    """Checks the anti-injection thesis: not one value shows up in the SQL string."""
    node = SnakeTupleIn(
        columns=_cols("region", "code"),
        rows=(("'; DROP TABLE realms; --", 1),),
    )
    sql, params = emit_condition(node, PostgresDialect())
    assert "DROP TABLE" not in sql
    assert params == ("'; DROP TABLE realms; --", 1)


def test_falls_back_to_or_of_ands_without_row_constructor() -> None:
    """With no row constructor, the same node translates to `((a=%s AND b=%s) OR (a=%s AND b=%s))`."""
    node = SnakeTupleIn(
        columns=_cols("region", "code"), rows=(("Nornia", 1), ("Sudmark", 2))
    )
    sql, params = emit_condition(node, _NoRowConstructorDialect())
    assert sql == (
        '(("region" = %s AND "code" = %s) OR ("region" = %s AND "code" = %s))'
    )
    assert params == ("Nornia", 1, "Sudmark", 2)


def test_empty_rows_raise_emit_error() -> None:
    """A `SnakeTupleIn` with no rows cannot be emitted: `SnakeEmitError` (same as SnakeInList's `IN ()`)."""
    node = SnakeTupleIn(columns=_cols("region", "code"), rows=())
    with pytest.raises(SnakeEmitError, match="A tuple IN needs at least one row"):
        emit_condition(node, PostgresDialect())


def _wide(columns: int, tuples: int) -> SnakeTupleIn:
    """A row constructor of a given shape, for asking where the emitter stops."""
    return SnakeTupleIn(
        columns=_cols(*(f"c{i}" for i in range(columns))),
        rows=tuple(tuple(range(columns)) for _ in range(tuples)),
    )


def test_a_row_constructor_past_the_engines_placeholder_ceiling_is_refused() -> None:
    """The ORM counts the placeholders and says so, rather than letting the driver do it.

    MEASURED on SQLite 3.53 rather than assumed, and measured at BOTH widths because the two
    candidate laws disagree: 16.383 tuples of 2 columns and 8.191 of 4 both stop at the same
    PLACEHOLDER count, so what governs this engine is the placeholders and not the rows. The
    declared `bind_params` is therefore the right number to count against, and `add_all` and the
    prefetch have been slicing by it for longer than this node has existed.

    What the engine answers without the guard is `too many SQL variables`, which says nothing about
    which query or what to do. This names the width, the count and the remedy.
    """
    dialect = SQLiteDialect()
    ceiling = dialect.max_bind_params

    emit_condition(
        _wide(2, ceiling // 2), dialect
    )  # exactly at the ceiling: still emits

    with pytest.raises(SnakeEmitError, match="32766|placeholder"):
        emit_condition(_wide(2, ceiling // 2 + 1), dialect)


def test_the_refusal_names_the_shape_that_caused_it() -> None:
    """The message carries the width and the number of keys: without them there is nothing to slice."""
    with pytest.raises(SnakeEmitError) as refusal:
        emit_condition(_wide(4, 9000), SQLiteDialect())

    message = str(refusal.value)
    assert "9000" in message, "the number of keys is missing"
    assert "4" in message, "the width is missing"
