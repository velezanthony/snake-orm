"""Precision and scale of a `NUMERIC`: a bare `Decimal` accepts anything at all.

Postgres, faced with a `NUMERIC` without precision, stores however many digits you throw at it. It
sounds generous until a money column piles up cents nobody asked for and the totals stop adding up
by whole units. `NUMERIC(12,2)` is what one means almost every time.

They travel as primitives in the metadata (`precision`, `scale`), so the renderer writes them for
free and the diff watches them like any other trait of the column.
"""

from __future__ import annotations

from decimal import Decimal

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDecimalParams,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import AlterColumn, diff_schema, emit_create_table

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)


def _table(price: SnakeColumnInfo) -> SnakeTableInfo:
    """The 'invoices' table with whatever amount column is passed in."""
    return SnakeTableInfo(
        name="invoices",
        columns=(_ID, price),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


def test_a_bare_decimal_stays_bare() -> None:
    """Verifies that with no precision asked for none is invented: what already worked is untouched."""
    ddl = emit_create_table(
        _table(SnakeColumnInfo(name="total", python_type=Decimal)), _DIALECT
    )
    assert '"total" NUMERIC NOT NULL' in ddl


def test_precision_and_scale_reach_the_ddl() -> None:
    """Verifies the case that matters: a money column with its two decimal places."""
    money = SnakeColumnInfo(
        name="total",
        python_type=Decimal,
        type_params=SnakeDecimalParams(precision=12, scale=2),
    )
    assert '"total" NUMERIC(12,2) NOT NULL' in emit_create_table(
        _table(money), _DIALECT
    )


def test_precision_without_scale_is_valid_sql() -> None:
    """Verifies `NUMERIC(9)`: precision without scale is legal and means zero decimal places."""
    counted = SnakeColumnInfo(
        name="total",
        python_type=Decimal,
        type_params=SnakeDecimalParams(precision=9, scale=None),
    )
    assert '"total" NUMERIC(9) NOT NULL' in emit_create_table(_table(counted), _DIALECT)


def test_changing_the_precision_is_a_column_change() -> None:
    """Verifies that the diff sees it: going from NUMERIC(10,2) to NUMERIC(12,2) is a real change.

    Without this, widening the maximum amount of an invoice would generate no migration and the
    column would fall short in production without anyone finding out.
    """
    before = _table(
        SnakeColumnInfo(
            name="total",
            python_type=Decimal,
            type_params=SnakeDecimalParams(precision=10, scale=2),
        )
    )
    after = _table(
        SnakeColumnInfo(
            name="total",
            python_type=Decimal,
            type_params=SnakeDecimalParams(precision=12, scale=2),
        )
    )

    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_the_same_precision_converges() -> None:
    """Verifies that an identical column produces no operations: the autogen has to converge."""
    money = SnakeColumnInfo(
        name="total",
        python_type=Decimal,
        type_params=SnakeDecimalParams(precision=12, scale=2),
    )
    assert diff_schema([_table(money)], [_table(money)]) == []
