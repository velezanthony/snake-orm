"""Emission of aggregates (COUNT/EXISTS/projection) reusing a SELECT's FROM+JOINs+WHERE.

Same deep-navigation `plan`; they project an aggregate instead of columns.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import fields, is_dataclass
from typing import Any

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import (
    SnakeAggregate,
    SnakeStringAgg,
    SnakeCondition,
    SnakeOrder,
    SnakeValue,
    count,
)
from snakeorm.expressions.window import has_window
from snakeorm.metadata import SnakeTableInfo
from snakeorm.sql.condition import emit_condition_into
from snakeorm.sql.joins import JoinPlan
from snakeorm.sql.refs import qualified
from snakeorm.sql.value import Correlation, ExistsAliases, emit_order_key, emit_value


def emit_count(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    where: SnakeCondition | None = None,
    plan: JoinPlan | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Emits `SELECT COUNT(*) FROM ... [JOINs] [WHERE]`.

    The COUNT(*) is emitted through the `count()` node (the only place that knows how to write it);
    it consumes no params.
    """
    params: list[object] = []
    qualify = plan.alias_for if plan is not None else None
    projected = emit_value(count(), dialect, params, qualify)
    return (
        f"SELECT {projected} {_from_where(table, dialect, params, where, plan)}",
        tuple(params),
    )


def emit_exists(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    where: SnakeCondition | None = None,
    plan: JoinPlan | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Emits `SELECT EXISTS(SELECT 1 FROM ... [JOINs] [WHERE])`."""
    params: list[object] = []
    inner = _from_where(table, dialect, params, where, plan)
    return f"SELECT EXISTS(SELECT 1 {inner})", tuple(params)


def emit_project(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    columns: Sequence[SnakeValue[Any]],
    where: SnakeCondition | None = None,
    plan: JoinPlan | None = None,
    group_by: Sequence[SnakeValue[Any]] = (),
    having: SnakeCondition | None = None,
    order_by: tuple[SnakeOrder, ...] = (),
    limit: int | None = None,
    offset: int | None = None,
    functional_dependency: bool = False,
    distinct: bool = False,
) -> tuple[str, tuple[object, ...]]:
    """Emits `SELECT [DISTINCT] <cols> FROM ... [JOINs] [WHERE] [GROUP BY] [HAVING] [ORDER BY] [LIMIT]`.

    Params in clause order (= SQL evaluation order) for continuous numbering. `having` without
    `group_by` is valid (a global aggregate). `functional_dependency=True` disables the GROUP BY
    guard: it is used by `annotate()`, which projects every column while grouping only by the PK
    (they all depend on it).
    """
    if not functional_dependency:
        _guard_grouped_projection(columns, group_by)
    _guard_no_window_in_group_by(group_by)
    params: list[object] = []
    qualify = plan.alias_for if plan is not None else None
    # One single correlation for the whole statement: aggregates that are correlated subqueries
    # (e.g. a `collection.count()` projected by annotate) need to know how to reference the parent.
    # Plain columns and aggregates ignore it.
    correlate = _correlation(table, dialect, plan)
    projected = ", ".join(
        emit_value(column, dialect, params, qualify, correlate) for column in columns
    )
    keyword = "SELECT DISTINCT" if distinct else "SELECT"
    sql = f"{keyword} {projected} {_from_where(table, dialect, params, where, plan)}"
    if group_by:
        keys = ", ".join(
            emit_value(column, dialect, params, qualify, correlate)
            for column in group_by
        )
        sql = f"{sql} GROUP BY {keys}"
    if having is not None:
        sql = f"{sql} HAVING {emit_condition_into(having, dialect, params, qualify, correlate)}"
    if order_by:
        keys = ", ".join(
            emit_order_key(key, dialect, params, qualify, correlate) for key in order_by
        )
        sql = f"{sql} ORDER BY {keys}"
    clause = dialect.limit_offset(limit, offset, params)
    if clause:
        sql = f"{sql} {clause}"
    return sql, tuple(params)


def _correlation(
    table: SnakeTableInfo, dialect: SnakeDialect, plan: JoinPlan | None
) -> Correlation:
    """Correlation context for the HAVING (in case it carries correlated subqueries)."""
    parent_ref = (
        plan.root_alias if plan is not None else dialect.quote_ident(table.name)
    )
    return Correlation(parent_ref=parent_ref, aliases=ExistsAliases())


def _flattened(child: object) -> Iterator[object]:
    """One field's value as nodes, unwrapping sequences however deeply they nest.

    A `CASE` keeps its branches as a tuple OF TUPLES, so unwrapping one level finds a tuple and
    stops there — which is how the aggregate inside a branch stayed invisible.
    """
    if isinstance(child, (tuple, list)):
        for item in child:
            yield from _flattened(item)
    else:
        yield child


def _subnodes(value: object) -> Iterator[object]:
    """The direct children of an expression node, with its sequences flattened out.

    It reads the node's own fields instead of naming the node types, and that is deliberate: the set
    of things that can wrap an aggregate is open — `COALESCE`, `NULLIF`, `CASE`, arithmetic, a cast,
    and whatever comes next. A walk that lists them is a walk that has to be remembered.
    """
    if not is_dataclass(value) or isinstance(value, type):
        return
    for field in fields(value):
        yield from _flattened(getattr(value, field.name))


def _aggregated_paths(value: object) -> set[tuple[str, ...]]:
    """Every path that sits INSIDE an aggregate, however deeply it is wrapped.

    An aggregate's own paths are all of them: `SUM(x)` aggregates `x` wherever the `SUM` appears.

    `SnakeStringAgg` is named alongside `SnakeAggregate` and not folded into it: it IS an aggregate
    —it collapses a group— but it is a separate node because its separator has no fixed position
    across the engines. A walk that only knew the one class would have refused `string_agg(name)`
    beside a `GROUP BY` as an ungrouped column, which is the opposite of what it is.
    """
    if isinstance(value, (SnakeAggregate, SnakeStringAgg)):
        return set(value.paths())
    found: set[tuple[str, ...]] = set()
    for child in _subnodes(value):
        found |= _aggregated_paths(child)
    return found


def _guard_grouped_projection(
    columns: Sequence[SnakeValue[Any]], group_by: Sequence[SnakeValue[Any]]
) -> None:
    """With GROUP BY, every non-aggregated projected column must be grouped (caught before Postgres).

    The comparison goes through `paths()`. A path is fine when it is grouped OR when it sits inside
    an aggregate — which is what the error message has always said, and what the check used to
    decide by asking whether the projected node ITSELF was an aggregate. `COALESCE(SUM(x), 0)` is
    valid on every engine and was being refused, because the outer node is a `COALESCE`.

    The other direction is what the walk must not lose: `COALESCE(name, '')` aggregates nothing, and
    a bare column laundered through a wrapper has to stay an error.
    """
    if not group_by:
        return
    grouped = {path for column in group_by for path in column.paths()}
    for column in columns:
        aggregated = _aggregated_paths(column)
        for path in column.paths():
            if path not in grouped and path not in aggregated:
                name = ".".join(path)
                raise SnakeEmitError(
                    f"Column '{name}' appears in the projection but neither in the GROUP BY "
                    f"nor inside an aggregate. Add it to group_by(...) or aggregate it."
                )


def _from_where(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    params: list[object],
    where: SnakeCondition | None,
    plan: JoinPlan | None,
) -> str:
    """Builds `FROM <table> [AS t0] [JOINs] [WHERE <cond>]` (shared by count/exists)."""
    qualify = plan.alias_for if plan is not None else None
    table_ref = qualified(table.schema, table.name, dialect)
    if plan is not None:
        table_ref = f"{table_ref} AS {plan.root_alias}"
    sql = f"FROM {table_ref}"
    if plan is not None and plan.has_joins:
        sql = f"{sql} {' '.join(plan.joins)}"
    if where is not None:
        parent_ref = (
            plan.root_alias if plan is not None else dialect.quote_ident(table.name)
        )
        correlate = Correlation(parent_ref=parent_ref, aliases=ExistsAliases())
        sql = f"{sql} WHERE {emit_condition_into(where, dialect, params, qualify, correlate)}"
    return sql


def _guard_no_window_in_group_by(group_by: Sequence[SnakeValue[Any]]) -> None:
    """A window cannot group: SQL evaluates windows AFTER the GROUP BY.

    The condition guard covers WHERE/HAVING, but the GROUP BY is a list of values, not a condition.
    """
    for value in group_by:
        if has_window(value):
            raise SnakeEmitError(
                "A window function cannot go in a GROUP BY: SQL evaluates it AFTER grouping, so "
                "there is nothing to group by yet. Group by the columns and project the window, "
                "or wrap the query and group on the outside."
            )
