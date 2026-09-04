"""Emission of a parametrised WHERE: SnakeCondition -> (sql, params).

Walks the boolean AST and produces SQL with the dialect's placeholders; the values travel in
`params` (kills injection and enables multi-engine). `qualify` qualifies columns with an alias (deep
JOINs).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import (
    SnakeEmitError,
    SnakeNodeError,
    SnakeUnsupportedFeature,
)
from snakeorm.expressions import (
    SnakeAnd,
    SnakeComparison,
    SnakeCondition,
    SnakeExists,
    SnakeExistsJoin,
    SnakeInList,
    SnakeInSubquery,
    SnakeIsNotNull,
    SnakeIsNull,
    SnakeLike,
    SnakeNot,
    SnakeOr,
    SnakeSubquery,
    SnakeTupleIn,
)
from snakeorm.expressions.window import has_window
from snakeorm.sql.refs import qualified
from snakeorm.sql.value import (
    Correlation,
    ExistsAliases,
    Qualify,
    emit_expression_or_literal,
    emit_operand,
    emit_value,
)


def emit_condition(
    condition: SnakeCondition,
    dialect: SnakeDialect,
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Translates an AST condition into a parametrised `(sql, params)`."""
    params: list[object] = []
    sql = emit_condition_into(condition, dialect, params, qualify, correlate)
    return sql, tuple(params)


def inline_params(sql: str, params: Sequence[object], dialect: SnakeDialect) -> str:
    """Replaces a compiled SQL's placeholders with their literals, for DDL (which takes no params).

    A forward pass that never revisits: a literal containing the placeholder token is not
    reinterpreted. The token is asked of the dialect by index (for numbered placeholders `$1`, `$2`).
    """
    written: list[str] = []
    rest = sql
    for index, value in enumerate(params, start=1):
        head, separator, rest = rest.partition(dialect.placeholder(index))
        if not separator:
            raise SnakeEmitError(
                f"The compiled SQL is missing a placeholder for parameter {index} of "
                f"{len(params)}: it cannot be inlined into DDL."
            )
        written.append(head)
        written.append(dialect.literal(value))
    written.append(rest)
    return "".join(written)


def emit_condition_ddl(condition: SnakeCondition, dialect: SnakeDialect) -> str:
    """Emits a condition for DDL: reuses the parametrised walk and then inlines the literals.

    It does not reopen injection: only the programmer's own literals get here, escaped by the
    dialect.
    """
    sql, params = emit_condition(condition, dialect)
    return inline_params(sql, params, dialect)


def _value_in_condition(
    value: object,
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """Emits a value inside a condition, rejecting window functions.

    SQL evaluates windows AFTER WHERE/GROUP BY/HAVING. The guard lives here (the single choke point
    every condition goes through) instead of being repeated in every node.
    """
    if has_window(value):
        raise SnakeEmitError(
            "A window function cannot be used in a WHERE, a GROUP BY or a HAVING: SQL evaluates "
            "them AFTER those clauses. Project it with select(...) and filter on the outside, "
            "or solve it with a subquery."
        )
    return emit_value(value, dialect, params, qualify, correlate)


def emit_condition_into(
    node: SnakeCondition,
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """Emits a node accumulating values into `params` (a side effect) and returns the SQL.

    The placeholders use `len(params)`, so the numbering carries on (this is what allows combining
    SET + WHERE without a collision). `qualify` qualifies columns with an alias; `correlate` carries
    the EXISTS/COUNT context.
    """
    if isinstance(node, SnakeComparison):
        left = _value_in_condition(node.left, dialect, params, qualify, correlate)
        right = emit_expression_or_literal(
            node.right, dialect, params, qualify, correlate
        )
        return f"{left} {node.op.value} {right}"
    if isinstance(node, SnakeAnd):
        joined = " AND ".join(
            emit_condition_into(part, dialect, params, qualify, correlate)
            for part in node.parts
        )
        return f"({joined})"
    if isinstance(node, SnakeOr):
        joined = " OR ".join(
            emit_condition_into(part, dialect, params, qualify, correlate)
            for part in node.parts
        )
        return f"({joined})"
    if isinstance(node, SnakeInList):
        if not node.values:
            raise SnakeEmitError("An IN needs at least one value")
        left = _value_in_condition(node.left, dialect, params, qualify, correlate)
        items = ", ".join(
            emit_expression_or_literal(value, dialect, params, qualify, correlate)
            for value in node.values
        )
        return f"{left} IN ({items})"
    if isinstance(node, SnakeTupleIn):
        return _emit_tuple_in(node, dialect, params, qualify, correlate)
    if isinstance(node, SnakeIsNull):
        return f"{_value_in_condition(node.left, dialect, params, qualify, correlate)} IS NULL"
    if isinstance(node, SnakeIsNotNull):
        return f"{_value_in_condition(node.left, dialect, params, qualify, correlate)} IS NOT NULL"
    if isinstance(node, SnakeLike):
        left = _value_in_condition(node.left, dialect, params, qualify, correlate)
        pattern = emit_expression_or_literal(
            node.pattern, dialect, params, qualify, correlate
        )
        # An ESCAPE clause only if the value's wildcards were escaped (startswith/...): without it
        # SQLite treats the `\` as a character and silently filters wrong. A raw `.like()` respects
        # the default.
        #
        # The character is the backslash on all three engines — that is decided in `_escape_like`,
        # which is engine-agnostic — but how to WRITE it inside a literal is the dialect's job, so
        # it goes through `literal()`. Hardcoded as `'\'` this clause was ERROR 1064 on MySQL, where
        # the backslash escapes the quote and the literal never closes: `startswith`, `contains` and
        # `endswith` did not work on that engine at all.
        escape = f" ESCAPE {dialect.literal(chr(92))}" if node.escaped else ""
        if node.case_insensitive and not dialect.supports_ilike:
            # Portable fallback: SQLite has no ILIKE, so it folds both sides to
            # lowercase.
            return f"LOWER({left}) LIKE LOWER({pattern}){escape}"
        operator = "ILIKE" if node.case_insensitive else "LIKE"
        return f"{left} {operator} {pattern}{escape}"
    if isinstance(node, SnakeNot):
        return f"NOT ({emit_condition_into(node.operand, dialect, params, qualify, correlate)})"
    if isinstance(node, SnakeExists):
        return _emit_exists(node, dialect, params, correlate)
    if isinstance(node, SnakeInSubquery):
        left = _value_in_condition(node.left, dialect, params, qualify, correlate)
        return f"{left} IN ({_emit_in_subquery(node.subquery, dialect, params)})"
    raise SnakeNodeError(f"Condition node cannot be emitted: {type(node).__name__}")


def _emit_in_subquery(
    sub: SnakeSubquery[Any], dialect: SnakeDialect, params: list[object]
) -> str:
    """Emits `SELECT <column> FROM <table> [WHERE ...]` of a scalar subquery.

    Its params accumulate in the shared list (continuous numbering, positional).
    Single-table (no alias); it gets its own correlation in case its WHERE nests
    an EXISTS.
    """
    quote = dialect.quote_ident
    table_ref = qualified(sub.schema, sub.name, dialect)
    sql = f"SELECT {quote(sub.column)} FROM {table_ref}"
    if sub.where is not None:
        correlate = Correlation(parent_ref=quote(sub.name), aliases=ExistsAliases())
        where_sql = emit_condition_into(sub.where, dialect, params, None, correlate)
        sql = f"{sql} WHERE {where_sql}"
    return sql


def _guard_placeholder_ceiling(node: SnakeTupleIn, dialect: SnakeDialect) -> None:
    """Refuses a row constructor that would bind more placeholders than the engine accepts.

    The number is the engine's own declared `bind_params`, which `add_all` and the prefetch already
    slice by; this is the one path where the caller supplies the rows by hand.

    MEASURED, at two widths, because two laws were candidates. On SQLite 3.53, 16.383 keys of two
    columns and 8.191 of four both stop at the SAME placeholder count: what governs it is the
    placeholders. Without this the engine answers `too many SQL variables`, which names neither the
    query nor the way out.

    WHAT IS DELIBERATELY NOT GUARDED is PostgreSQL's other ceiling. Measured on 17: it refuses at
    8.184 keys with `stack depth limit exceeded` at BOTH widths — so there the law is the number of
    keys and not the placeholders, and it is the PARSER's recursion, well under the 65.535 of the
    protocol. That number moves with `max_stack_depth`, which is a server setting, so the ORM cannot
    know it: refusing at a number taken from one server's configuration would forbid on a tuned
    server what the database there allows. The limit is written down in the reference instead of
    invented here.
    """
    placeholders = len(node.rows) * len(node.columns)
    if placeholders <= dialect.max_bind_params:
        return
    raise SnakeEmitError(
        f"This composite IN binds {placeholders} placeholders — {len(node.rows)} keys of "
        f"{len(node.columns)} columns — and {type(dialect).__name__} accepts "
        f"{dialect.max_bind_params} per statement. Slice the list of keys and combine the results; "
        f"the ORM will not split it for you, because the halves are separate queries and only the "
        f"caller knows whether that is acceptable here."
    )


def _emit_tuple_in(
    node: SnakeTupleIn,
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None,
    correlate: Correlation | None,
) -> str:
    """Emits `(c1, c2) IN ((%s, %s), ...)`, or its OR-of-ANDs equivalent without `supports_row_constructor`.

    No rows is unemittable (there is no `IN ()`). Columns with `emit_value` (no params),
    values with `emit_operand` (parametrised, continuous numbering).
    """
    if not node.rows:
        raise SnakeEmitError("A tuple IN needs at least one row")
    _guard_placeholder_ceiling(node, dialect)
    if dialect.supports_row_constructor:
        columns = ", ".join(
            emit_value(column, dialect, params, qualify, correlate)
            for column in node.columns
        )
        rows = ", ".join(
            "(" + ", ".join(emit_operand(value, dialect, params) for value in row) + ")"
            for row in node.rows
        )
        return f"({columns}) IN ({rows})"
    clauses: list[str] = []
    for row in node.rows:
        conjunction = " AND ".join(
            f"{emit_value(column, dialect, params, qualify, correlate)} "
            f"= {emit_operand(value, dialect, params)}"
            for column, value in zip(node.columns, row, strict=True)
        )
        clauses.append(f"({conjunction})")
    return "(" + " OR ".join(clauses) + ")"


def _emit_exists(
    node: SnakeExists,
    dialect: SnakeDialect,
    params: list[object],
    correlate: Correlation | None,
) -> str:
    """Emits `EXISTS (SELECT 1 FROM child AS alias [JOINs] WHERE child.fk = parent.pk [AND cond])`.

    The alias (e0, e1...) comes from its own counter shared with the nested ones (it does not
    collide with the outer t0...). The child's condition is re-anchored to the subquery's
    alias; its to-one navigation JOINs (`node.joins`) are emitted inside, with aliases from the
    same counter. A composite FK ANDs every pair. Everything parametrised.
    """
    if correlate is None:
        raise SnakeNodeError(
            "SnakeExists without a correlation context: the parent cannot be referenced"
        )
    quote = dialect.quote_ident
    alias = correlate.aliases.allocate()
    # `qualified()`, not a hand-written `f"{schema}.{name}"`: an engine without schemas
    # (SQLite) does not accept `"public".` and gave `no such table: public.x`, breaking
    # `.any()`, `.count()` and the aggregates.
    child_ref = qualified(node.child_schema, node.child_name, dialect)
    on = " AND ".join(
        f"{alias}.{quote(child_col)} = {correlate.parent_ref}.{quote(parent_col)}"
        for child_col, parent_col in node.pairs
    )
    alias_map, joins_sql = _build_exists_joins(
        node.joins, alias, correlate.aliases, dialect
    )
    from_clause = f"{child_ref} AS {alias}{joins_sql}"
    if node.condition is None:
        return f"EXISTS (SELECT 1 FROM {from_clause} WHERE {on})"
    inner = Correlation(parent_ref=alias, aliases=correlate.aliases)
    cond_sql = emit_condition_into(
        node.condition, dialect, params, _exists_qualify(alias_map), inner
    )
    return f"EXISTS (SELECT 1 FROM {from_clause} WHERE {on} AND {cond_sql})"


def _build_exists_joins(
    joins: tuple[SnakeExistsJoin, ...],
    child_alias: str,
    aliases: ExistsAliases,
    dialect: SnakeDialect,
) -> tuple[dict[tuple[str, ...], str], str]:
    """Assigns an alias to each navigated JOIN of the EXISTS and emits its clauses; returns the prefix→alias map.

    JOINs ordered from parent to child (the parent is already in `alias_map`; the base child
    takes the empty prefix). Aliases from the same shared `ExistsAliases`, so they never
    collide. to-one ON: `parent.local = alias.remote`; a composite FK ANDs the pairs.
    """
    quote = dialect.quote_ident
    alias_map: dict[tuple[str, ...], str] = {(): child_alias}
    clauses: list[str] = []
    for join in joins:
        alias = aliases.allocate()
        alias_map[join.prefix] = alias
        parent_alias = alias_map[join.prefix[:-1]]
        on = " AND ".join(
            f"{parent_alias}.{quote(local)} = {alias}.{quote(remote)}"
            for local, remote in join.pairs
        )
        table_ref = qualified(join.schema, join.name, dialect)
        clauses.append(f" JOIN {table_ref} AS {alias} ON {on}")
    return alias_map, "".join(clauses)


def _exists_qualify(alias_map: dict[tuple[str, ...], str]) -> Qualify:
    """Qualifies a child column (or navigated target) with the alias of its relation prefix.

    `Maker.name` → `()` → the child's alias; `Maker.nation.name` → `("nation",)` → the JOIN's
    alias. A missing prefix would be a JOIN that was never built (it should not happen after
    validating `.any()`).
    """

    def qualify(prefix: tuple[str, ...]) -> str:
        alias = alias_map.get(prefix)
        if alias is None:
            raise SnakeUnsupportedFeature(
                "navigation inside an EXISTS without a JOIN built for prefix "
                f"'{'.'.join(prefix)}'; it should not happen after the .any() validation."
            )
        return alias

    return qualify
