"""Emission of a parametrised UPDATE: `UPDATE ... SET ... [WHERE ...]`.

The SET consumes the first params; the WHERE continues the numbering over the same list
(`emit_condition_into`). `where=None` affects the whole table: the guard-rail lives in query/session.
"""

from __future__ import annotations

from collections.abc import Mapping

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import SnakeCondition, SnakeValue
from snakeorm.metadata import SnakeTableInfo
from snakeorm.sql.condition import emit_condition_into
from snakeorm.sql.joins import JoinPlan
from snakeorm.sql.pk_subquery import emit_pk_in, emit_pk_subquery
from snakeorm.sql.refs import qualified
from snakeorm.sql.value import emit_operand, emit_value


def _emit_set(
    values: Mapping[str, object], dialect: SnakeDialect, params: list[object]
) -> str:
    """Emits the SET's `col = <value>` assignments, accumulating literals into `params`.

    A `SnakeValue` (e.g. `views + 1`) is emitted as an unqualified expression; a literal, as a
    placeholder. This is what enables `SET views = views + 1`.
    """
    assignments = []
    for column, value in values.items():
        if isinstance(value, SnakeValue):
            rendered = emit_value(value, dialect, params, None)
        else:
            rendered = emit_operand(value, dialect, params)
        assignments.append(f"{dialect.quote_ident(column)} = {rendered}")
    return ", ".join(assignments)


def emit_update(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    values: Mapping[str, object],
    where: SnakeCondition | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Emits `UPDATE ... SET ... [WHERE ...]` with params apart (SET first, then WHERE)."""
    if not values:
        raise SnakeEmitError("An UPDATE needs at least one column in the SET")

    params: list[object] = []
    set_sql = _emit_set(values, dialect, params)
    table_ref = qualified(table.schema, table.name, dialect)
    sql = f"UPDATE {table_ref} SET {set_sql}"

    if where is not None:
        where_sql = emit_condition_into(where, dialect, params)
        sql = f"{sql} WHERE {where_sql}"

    return sql, tuple(params)


def emit_update_pk_in_subquery(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    values: Mapping[str, object],
    plan: JoinPlan,
    where: SnakeCondition,
) -> tuple[str, tuple[object, ...]]:
    """Emits `UPDATE ... SET ... WHERE <pk> IN (SELECT <pk> FROM ... [JOINs] WHERE <deep cond>)`.

    For a WHERE that navigates a relationship (avoids `UPDATE ... FROM`). The SET consumes the first
    params and the subquery continues from there; the SET still targets the base table.
    """
    if not values:
        raise SnakeEmitError("An UPDATE needs at least one column in the SET")

    params: list[object] = []
    set_sql = _emit_set(values, dialect, params)
    table_ref = qualified(table.schema, table.name, dialect)
    subquery = emit_pk_subquery(table, dialect, plan, where, params)
    pk_in = emit_pk_in(table, dialect, subquery)
    return f"UPDATE {table_ref} SET {set_sql} WHERE {pk_in}", tuple(params)
