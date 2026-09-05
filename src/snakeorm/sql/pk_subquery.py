"""Rewriting a bulk write with a deep WHERE into `pk IN (subquery)`.

An UPDATE/DELETE whose filter navigates a relationship does not fit in a flat WHERE. Instead of
`... FROM` (Postgres jargon, not portable), it is rewritten into a subquery that projects the PK
using the `JoinPlan` of the deep paths. A composite PK uses a row constructor `(a, b) IN (...)`.
"""

from __future__ import annotations

from snakeorm.dialects import SnakeDialect
from snakeorm.expressions import SnakeCondition
from snakeorm.metadata import SnakeTableInfo
from snakeorm.sql.condition import emit_condition_into
from snakeorm.sql.joins import JoinPlan
from snakeorm.sql.refs import qualified
from snakeorm.sql.value import Correlation, ExistsAliases


def emit_pk_subquery(
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    plan: JoinPlan,
    where: SnakeCondition,
    params: list[object],
) -> str:
    """Emits `SELECT t0."pk"... FROM <table> AS t0 [JOINs] WHERE <deep cond>` (the PK ONLY).

    Reuses the `JoinPlan` and `emit_condition_into` with alias qualification. The WHERE params are
    accumulated (numbering continues from the UPDATE's SET, positional).
    """
    quote = dialect.quote_ident
    root_alias = plan.root_alias
    pk_columns = ", ".join(
        f"{root_alias}.{quote(column.name)}" for column in table.primary_key.columns
    )
    table_ref = f"{qualified(table.schema, table.name, dialect)} AS {root_alias}"
    sql = f"SELECT {pk_columns} FROM {table_ref}"
    if plan.has_joins:
        sql = f"{sql} {' '.join(plan.joins)}"
    correlate = Correlation(parent_ref=root_alias, aliases=ExistsAliases())
    where_sql = emit_condition_into(where, dialect, params, plan.alias_for, correlate)
    return f"{sql} WHERE {where_sql}"


def emit_pk_in(table: SnakeTableInfo, dialect: SnakeDialect, subquery: str) -> str:
    """Emits `<pk> IN (subquery)` over the base table (NO alias).

    Simple PK → `"id" IN (...)`; composite → row constructor `("a","b") IN (...)`. Unqualified: the
    outer UPDATE/DELETE operates on the base table, which carries no alias.
    """
    quote = dialect.quote_ident
    columns = [quote(column.name) for column in table.primary_key.columns]
    left = columns[0] if len(columns) == 1 else f"({', '.join(columns)})"
    return f"{left} IN ({subquery})"
