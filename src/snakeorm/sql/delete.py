"""Emission of a parametrised DELETE: `DELETE FROM <schema.table> [WHERE <cond>]`.

`where=None` deletes the whole table (valid SQL): the guard-rail lives in query/session, not here.
"""

from __future__ import annotations

from snakeorm.dialects import SnakeDialect
from snakeorm.expressions import SnakeCondition
from snakeorm.metadata import SnakeTableInfo
from snakeorm.sql.condition import emit_condition
from snakeorm.sql.joins import JoinPlan
from snakeorm.sql.pk_subquery import emit_pk_in, emit_pk_subquery
from snakeorm.sql.refs import qualified


def emit_delete(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    where: SnakeCondition | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Emits `DELETE FROM ... [WHERE ...]` with the params kept apart."""
    table_ref = qualified(table.schema, table.name, dialect)
    sql = f"DELETE FROM {table_ref}"
    if where is None:
        return sql, ()
    where_sql, params = emit_condition(where, dialect)
    return f"{sql} WHERE {where_sql}", params


def emit_delete_pk_in_subquery(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    plan: JoinPlan,
    where: SnakeCondition,
) -> tuple[str, tuple[object, ...]]:
    """Emits `DELETE FROM ... WHERE <pk> IN (SELECT <pk> FROM ... [JOINs] WHERE <deep cond>)`.

    For a WHERE that navigates a relationship: it is rewritten into a subquery over the PK (avoids
    `DELETE ... FROM`, Postgres jargon). A composite PK uses a row constructor. Parametrised.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    params: list[object] = []
    subquery = emit_pk_subquery(table, dialect, plan, where, params)
    pk_in = emit_pk_in(table, dialect, subquery)
    return f"DELETE FROM {table_ref} WHERE {pk_in}", tuple(params)
