"""`WITH RECURSIVE`: walking an entire hierarchy with ONE query.

It brings a NEW capability: "every descendant at any depth" cannot be written with subqueries
(either you go down level by level with an N+1, or you use recursion). Emitted shape:

    WITH RECURSIVE snake_rec AS (
        (<anchor>) UNION [ALL]
        SELECT t.<cols> FROM <table> AS t JOIN snake_rec ON t.<child> = snake_rec.<accumulated>
    )
    SELECT <cols> FROM snake_rec [ORDER BY ...] [LIMIT ...]

`UNION ALL` by default: deduplicating every step would cost hashing everything accumulated so far,
and a well-formed tree has no duplicates to drop. Over data with CYCLES that walk never ends —each
lap yields rows the engine counts as new— so the operator is the CALLER's to pick: `distinct=True`
emits a plain `UNION`, the lap that repeats contributes nothing, and the recursion stops on its own.

A `limit()` is not a substitute. Measured against a real Postgres over a three-row cycle: `UNION
ALL` with an `order_by()` and a `LIMIT 3` never returns, because the sort has to consume every row
before it can emit one. The limit bounds what comes BACK, not how far the engine goes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import SnakeExpr, SnakeOrder
from snakeorm.metadata import SnakeTableInfo
from snakeorm.sql.refs import qualified
from snakeorm.sql.value import emit_order_key, guard_untabled_order_keys

if TYPE_CHECKING:
    from snakeorm.query.query import SnakeQuery

T = TypeVar("T")

CTE_NAME = "snake_rec"
"""Name of the CTE. Fixed on purpose: it does not nest (a recursion admits no other inside it)."""

SOURCE_ALIAS = "snake_src"
"""Alias of the table inside the recursive step, mandatory: the CTE has the same column names, so
without an alias they are ambiguous and Postgres rejects the query (the test against the engine caught it)."""


@dataclass(frozen=True, slots=True)
class SnakeRecursive(Generic[T]):
    """An ANCHOR query that expands itself by following a hop onto itself.

    `child_column` points upwards (`parent_id`) and `parent_column` identifies the accumulated row
    (`id`): the direction is fixed by which one goes first (swapping them walks the ancestors, a
    perfectly legitimate query).

    `distinct` picks the set operator that joins each step to what has already been accumulated:
    `False` (the default) emits `UNION ALL`, `True` emits `UNION`. It is the difference between a
    walk that ends over cyclic data and one that does not.
    """

    anchor: SnakeQuery[T]
    table: SnakeTableInfo
    child_column: str
    parent_column: str
    distinct: bool = False
    order_by_keys: tuple[SnakeOrder, ...] = ()
    limit_value: int | None = None
    offset_value: int | None = None

    @property
    def model(self) -> type[T]:
        """The model of the rows: the same as the anchor's. The session uses it to instantiate them."""
        return self.anchor.model

    @property
    def projected_columns(self) -> frozenset[str] | None:
        """Never narrowed: the CTE's columns are the TABLE's, and a narrowed anchor is refused."""
        return None

    @property
    def has_includes(self) -> bool:
        """Never: an anchor with includes is rejected at build time, not here."""
        return False

    @property
    def has_lock(self) -> bool:
        """Never: a recursive CTE does not lock rows. It is rejected at build time."""
        return False

    @property
    def has_bounds(self) -> bool:
        """Tells whether it carries `limit`/`offset` of its own. The compound looks at this."""
        return self.limit_value is not None or self.offset_value is not None

    @property
    def has_order(self) -> bool:
        """Tells whether it carries `order_by` of its own. The compound looks at this."""
        return bool(self.order_by_keys)

    @property
    def has_cte(self) -> bool:
        """Always: this is the `WITH RECURSIVE`. The compound asks so it can refuse where a CTE
        cannot be a branch, which is two of the three engines."""
        return True

    def order_by(self, *keys: SnakeExpr[Any] | SnakeOrder) -> SnakeRecursive[T]:
        """Orders the RESULT (not the anchor nor the step). A bare column orders ascending.

        The same guard the compound uses, and for the same reason: the `SELECT ... FROM cte` this
        ordering hangs off has only the CTE's columns, so a key that navigates a relationship would
        lose the hop and be written as another column's bare name.
        """
        normalized = tuple(
            key if isinstance(key, SnakeOrder) else key.asc() for key in keys
        )
        guard_untabled_order_keys(
            normalized,
            self.projected_columns,
            "A WITH RECURSIVE",
            "Order the rows in Python after the traversal, or join the far table in a separate "
            "query.",
        )
        return replace(self, order_by_keys=self.order_by_keys + normalized)

    def limit(self, limit: int) -> SnakeRecursive[T]:
        """Bounds the RESULT, and only the result: it does NOT bound the traversal.

        It read as the safety net against a cycle until somebody measured it. Put an `order_by()`
        in front of it —which is the normal way to ask for a hierarchy— and the engine has to
        produce every row before it can sort them, so the bound never gets its turn and the query
        hangs all the same. What ends a cyclic walk is `recursive(..., distinct=True)`.
        """
        return replace(self, limit_value=limit)

    def offset(self, offset: int) -> SnakeRecursive[T]:
        """Skips rows of the result (it replaces the previous one)."""
        return replace(self, offset_value=offset)

    def to_sql(self, dialect: SnakeDialect) -> tuple[str, tuple[object, ...]]:
        """Compiles to `(sql, params)`, with the ANCHOR's params first.

        That order is mandatory: the anchor comes earlier in the string and Postgres' `%s` is positional.
        """
        quote = dialect.quote_ident
        columns = ", ".join(quote(column.name) for column in self.table.columns)
        cte = quote(CTE_NAME)
        source = quote(SOURCE_ALIAS)
        # The step's columns go QUALIFIED by the alias: the CTE has the same names.
        step_columns = ", ".join(
            f"{source}.{quote(column.name)}" for column in self.table.columns
        )

        params: list[object] = []
        anchor_sql, anchor_params = self.anchor.to_sql(dialect)
        params.extend(anchor_params)

        # The anchor is parenthesised only if the engine admits it (SQLite rejects `((SELECT ...)
        # UNION ALL ...)`). Same flag as the UNION emitter. Without parentheses, an anchor with
        # limit()/offset() of its own is inexpressible (the bounding would read off the whole UNION),
        # so it is rejected in plain words.
        if not dialect.supports_parenthesised_compound and self.anchor.has_bounds:
            raise SnakeEmitError(
                "This engine does not accept parentheses around the anchor of a WITH RECURSIVE, so "
                "an anchor with its own limit()/offset() is inexpressible: the bound would read "
                "off the whole traversal. Drop them from the anchor and bound the RESULT with "
                ".limit() on the recursion."
            )
        anchor = (
            f"({anchor_sql})" if dialect.supports_parenthesised_compound else anchor_sql
        )

        table = qualified(self.table.schema, self.table.name, dialect)
        step = (
            f"SELECT {step_columns} FROM {table} AS {source} "
            f"JOIN {cte} ON {source}.{quote(self.child_column)} "
            f"= {cte}.{quote(self.parent_column)}"
        )
        # The operator the CALLER chose. `UNION` is `UNION DISTINCT`, so the step drops what has
        # already been accumulated and a cyclic walk runs out of new rows instead of running for ever.
        operator = "UNION" if self.distinct else "UNION ALL"
        sql = (
            f"WITH RECURSIVE {cte} AS ({anchor} {operator} {step}) "
            f"SELECT {columns} FROM {cte}"
        )

        if self.order_by_keys:
            keys = ", ".join(
                emit_order_key(key, dialect, params, None) for key in self.order_by_keys
            )
            sql = f"{sql} ORDER BY {keys}"

        clause = dialect.limit_offset(self.limit_value, self.offset_value, params)
        if clause:
            sql = f"{sql} {clause}"
        return sql, tuple(params)


def build_recursive(
    anchor: SnakeQuery[T],
    table: SnakeTableInfo,
    child: SnakeExpr[Any],
    parent: SnakeExpr[Any],
    distinct: bool = False,
) -> SnakeRecursive[T]:
    """Builds the recursion, rejecting whatever does not survive a CTE.

    The hop's two columns must belong to the table that recurses (it joins ONTO ITSELF): a column
    from another model would be emitted all the same and would produce an absurd JOIN, or worse,
    wrong results with no error.

    `distinct` travels straight through to the emission: it is a choice, not something to validate.
    """
    if anchor.has_includes:
        raise SnakeEmitError(
            "A query with include(...) cannot be the anchor of a recursion: the columns of the "
            "CTE are those of the table, so the loaded relationships would be lost. Recurse "
            "without include and load the relationships afterwards."
        )
    if anchor.has_lock:
        raise SnakeEmitError(
            "A query with for_update() cannot be the anchor of a recursion: Postgres does not "
            "accept locks inside a recursive CTE. Lock the rows in a separate query."
        )
    if anchor.projected_columns is not None:
        raise SnakeEmitError(
            "A query narrowed with only()/defer() cannot be the anchor of a recursion: the CTE's "
            "columns are the TABLE's, so the step selects every one of them and the anchor would "
            "select a few, and the UNION inside the CTE would not line up. Recurse whole rows and "
            "project afterwards."
        )

    names = {column.name for column in table.columns}
    for expr in (child, parent):
        if expr.path[-1] not in names:
            raise SnakeEmitError(
                f"Column '{expr.path[-1]}' does not belong to '{table.name}', and a recursion joins "
                f"that table WITH ITSELF. Both columns of the hop have to be its own."
            )
    return SnakeRecursive(
        anchor=anchor,
        table=table,
        child_column=child.path[-1],
        parent_column=parent.path[-1],
        distinct=distinct,
    )
