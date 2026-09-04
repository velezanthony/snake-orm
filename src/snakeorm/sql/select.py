"""Emission of a parametrised SELECT: orchestrates the grammar, delegates engine bits to the dialect.

Params in a single list (WHERE before LIMIT/OFFSET) for continuous numbering. Without a `plan` →
single-table, no alias (backwards compatible). With a `plan` → deep navigation: root aliased as t0,
JOINs and qualified columns. The result is still the root (the JOINs only filter/order).
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.expressions import SnakeCondition, SnakeLock, SnakeOrder
from snakeorm.metadata import SnakeColumnInfo, SnakeTableInfo
from snakeorm.sql.condition import emit_condition_into
from snakeorm.sql.joins import JoinPlan
from snakeorm.sql.refs import qualified
from snakeorm.sql.value import (
    Correlation,
    ExistsAliases,
    Qualify,
    emit_order_key,
)


def _correlation(
    table: SnakeTableInfo, dialect: SnakeDialect, plan: JoinPlan | None
) -> Correlation:
    """Correlation context for the WHERE's subqueries (how to reference the root).

    With JOINs the root has an alias (`t0`); without them, the table name (the FROM's implicit
    correlation).
    """
    parent_ref = (
        plan.root_alias if plan is not None else dialect.quote_ident(table.name)
    )
    return Correlation(parent_ref=parent_ref, aliases=ExistsAliases())


def selected_columns(
    table: SnakeTableInfo, columns: frozenset[str] | None
) -> tuple[SnakeColumnInfo, ...]:
    """The columns to project, in the TABLE's declaration order and never the caller's.

    The order is not a detail: hydration walks the same declaration to build its plan, so a
    projection sorted by what the user typed would line the row up against the wrong attributes. Two
    orders is two chances to be wrong, and one of them is silent.

    `None` means every column, which is what every path but `only()`/`defer()` passes.
    """
    if columns is None:
        return table.columns
    return tuple(column for column in table.columns if column.name in columns)


def emit_select(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    where: SnakeCondition | None = None,
    order_by: tuple[SnakeOrder, ...] = (),
    limit: int | None = None,
    offset: int | None = None,
    plan: JoinPlan | None = None,
    distinct: bool = False,
    lock: SnakeLock | None = None,
    columns: frozenset[str] | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Emits a parametrised `SELECT [DISTINCT] ... FROM ... [JOINs] [WHERE] [ORDER BY] [LIMIT/OFFSET]`.

    `columns` is the subset `only()`/`defer()` asked for, or `None` for every column. The order is
    the TABLE's, never the caller's: the hydration plan is built by walking the same declaration, so
    two orders would be two chances to line the row up wrong.
    """
    params: list[object] = []
    qualify: Qualify | None = plan.alias_for if plan is not None else None
    root_alias = plan.root_alias if plan is not None else None

    projected = selected_columns(table, columns)
    columns_sql = ", ".join(
        _column_ref(root_alias, column.name, dialect) for column in projected
    )
    table_ref = qualified(table.schema, table.name, dialect)
    if root_alias is not None:
        table_ref = f"{table_ref} AS {root_alias}"
    keyword = "SELECT DISTINCT" if distinct else "SELECT"
    sql = f"{keyword} {columns_sql} FROM {table_ref}"

    if plan is not None and plan.has_joins:
        sql = f"{sql} {' '.join(plan.joins)}"

    if where is not None:
        correlate = _correlation(table, dialect, plan)
        sql = f"{sql} WHERE {emit_condition_into(where, dialect, params, qualify, correlate)}"

    if order_by:
        keys = ", ".join(
            emit_order_key(key, dialect, params, qualify) for key in order_by
        )
        sql = f"{sql} ORDER BY {keys}"

    clause = dialect.limit_offset(limit, offset, params)
    if clause:
        sql = f"{sql} {clause}"

    # The lock goes AT THE END of the grammar, after LIMIT/OFFSET: it locks the rows the SELECT
    # really returns, not the ones it looked at to get to them.
    if lock is not None and not dialect.supports_row_locking:
        # It is cut off at COMPILE time (before touching the DB) and the alternative is given,
        # rather than emitting a `FOR UPDATE` the engine does not understand so that it blows up.
        raise SnakeUnsupportedFeature(
            "This engine does not support row locking (`SELECT ... FOR UPDATE`): SQLite locks the "
            "whole file, not individual rows. Use an exclusive transaction on this engine, or "
            "PostgreSQL if you need to reserve specific rows."
        )
    if lock is not None:
        sql = f"{sql} {_LOCK_CLAUSES[lock]}"

    return sql, tuple(params)


# Lock clause per mode. `WAIT` is the plain `FOR UPDATE` (waiting is its default behaviour), so it
# carries no suffix.
_LOCK_CLAUSES: dict[SnakeLock, str] = {
    SnakeLock.WAIT: "FOR UPDATE",
    SnakeLock.NOWAIT: "FOR UPDATE NOWAIT",
    SnakeLock.SKIP_LOCKED: "FOR UPDATE SKIP LOCKED",
}


def emit_select_with_includes(
    dialect: SnakeDialect,
    segments: Sequence[tuple[tuple[str, ...], SnakeTableInfo]],
    plan: JoinPlan,
    where: SnakeCondition | None = None,
    order_by: tuple[SnakeOrder, ...] = (),
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Emits the SELECT loading the root + included relationships (columns qualified by alias).

    `segments` in order: root `((), table)` and then each relationship `(prefix, table)`. All their
    columns enter in that order, so the session slices each row by segment and rebuilds the object.
    """
    params: list[object] = []
    qualify: Qualify = plan.alias_for
    root = segments[0][1]

    columns = ", ".join(
        f"{plan.alias_for(prefix)}.{dialect.quote_ident(column.name)}"
        for prefix, segment_table in segments
        for column in segment_table.columns
    )
    table_ref = qualified(root.schema, root.name, dialect)
    sql = f"SELECT {columns} FROM {table_ref} AS {plan.root_alias}"
    if plan.has_joins:
        sql = f"{sql} {' '.join(plan.joins)}"
    if where is not None:
        correlate = _correlation(root, dialect, plan)
        sql = f"{sql} WHERE {emit_condition_into(where, dialect, params, qualify, correlate)}"
    if order_by:
        keys = ", ".join(
            emit_order_key(key, dialect, params, qualify) for key in order_by
        )
        sql = f"{sql} ORDER BY {keys}"
    clause = dialect.limit_offset(limit, offset, params)
    if clause:
        sql = f"{sql} {clause}"
    return sql, tuple(params)


def _column_ref(root_alias: str | None, name: str, dialect: SnakeDialect) -> str:
    """Quotes a column of the root table, with an alias if the query carries JOINs."""
    column = dialect.quote_ident(name)
    return f"{root_alias}.{column}" if root_alias is not None else column
