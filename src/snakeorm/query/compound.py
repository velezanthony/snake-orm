"""Query composition (`UNION`/`EXCEPT`/`INTERSECT`): it composes two whole SELECTs, not a clause.

`SnakeCompound` is the composable object: each node produces `(sql, params)` and composing is
concatenating in TEXTUAL ORDER (Postgres' positional `%s` matches by position: any other order would
give wrong rows). It fulfils the same contract as `SnakeQuery`, so the session runs it just the same.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import SnakeExpr, SnakeOrder
from snakeorm.sql.value import emit_order_key, guard_untabled_order_keys

if TYPE_CHECKING:
    from snakeorm.query.query import SnakeQuery
    from snakeorm.query.recursive import SnakeRecursive

T = TypeVar("T")

SnakeCompoundBranch: TypeAlias = "SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T]"
"""What can be a BRANCH of a set operation (the recursive one included).

It was verified against Postgres that `(SELECT ...) UNION (WITH RECURSIVE ...)` is valid. All three
fulfil the same contract (`model`, `has_includes`, `has_lock`, `to_sql`), which is what `_compose` needs."""


class SnakeSetOp(Enum):
    """Set operation (standard SQL, agnostic).

    `UNION` deduplicates (which forces sorting/hashing everything) and `UNION ALL` does not:
    different enum values, to force a CHOICE instead of inheriting a default.
    """

    UNION = "UNION"
    UNION_ALL = "UNION ALL"
    EXCEPT = "EXCEPT"
    INTERSECT = "INTERSECT"


@dataclass(frozen=True, slots=True)
class SnakeCompound(Generic[T]):
    """Two queries joined by a set operation, with ordering and bounding belonging to the SET.

    `order_by`/`limit`/`offset` belong to the set, and are emitted after the last branch. Closed over
    itself: a compound recomposes with no special cases.
    """

    operator: SnakeSetOp
    left: SnakeCompoundBranch[T]
    right: SnakeCompoundBranch[T]
    order_by_keys: tuple[SnakeOrder, ...] = ()
    limit_value: int | None = None
    offset_value: int | None = None

    @property
    def model(self) -> type[T]:
        """The model of the rows. Taken from the left one (both are of the same model, guaranteed by
        the type and by `_compose`): SQL only demands that the columns line up, so without that
        guarantee it would instantiate the rows wrong.
        """
        return self.left.model

    @property
    def projected_columns(self) -> frozenset[str] | None:
        """The columns the branches PROJECT, or `None` when they bring whole rows.

        The session maps by asking for this instead of counting the row's width, and a compound
        that could not answer was read as whole rows: the values of a narrowed branch landed on the
        wrong attributes. Both branches project the same set (`_compose` refuses anything else), so
        the left one answers for the pair.
        """
        return self.left.projected_columns

    @property
    def has_includes(self) -> bool:
        """Never: a compound loads no relationships. It is rejected at build time, not here."""
        return False

    @property
    def has_lock(self) -> bool:
        """Never: a compound locks no rows. It is rejected at build time, not here."""
        return False

    @property
    def has_bounds(self) -> bool:
        """Tells whether the SET carries `limit`/`offset` of its own, so a compound nested in
        another one answers the same question a query does."""
        return self.limit_value is not None or self.offset_value is not None

    @property
    def has_order(self) -> bool:
        """Tells whether the SET carries `order_by` of its own."""
        return bool(self.order_by_keys)

    @property
    def has_cte(self) -> bool:
        """Whether a `WITH RECURSIVE` is hiding anywhere inside. It travels UP: a recursion nested
        two compounds deep still ends up written inside a branch of the outer one."""
        return self.left.has_cte or self.right.has_cte

    def order_by(self, *keys: SnakeExpr[Any] | SnakeOrder) -> SnakeCompound[T]:
        """Orders the SET. A bare column orders ascending, just like in `SnakeQuery`.

        The key has to name a column the set HAS: refused here, where the caller still knows what
        they typed, rather than in the emitter where it turned into another column's name.
        """
        normalized = tuple(
            key if isinstance(key, SnakeOrder) else key.asc() for key in keys
        )
        guard_untabled_order_keys(
            normalized,
            self.projected_columns,
            "A UNION/EXCEPT/INTERSECT",
            "Order the branches' own query by it and compose the ids, or bring the column into "
            "the projection of both branches and order by that.",
        )
        return replace(self, order_by_keys=self.order_by_keys + normalized)

    def limit(self, limit: int) -> SnakeCompound[T]:
        """Bounds the SET (it replaces the previous one). Returns a new compound."""
        return replace(self, limit_value=limit)

    def offset(self, offset: int) -> SnakeCompound[T]:
        """Skips rows of the SET (it replaces the previous one). Returns a new compound."""
        return replace(self, offset_value=offset)

    def union(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`UNION`: the rows of both, WITHOUT duplicates."""
        return _compose(SnakeSetOp.UNION, self, other)

    def union_all(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`UNION ALL`: the rows of both, KEEPING duplicates. It does not deduplicate, and is cheaper."""
        return _compose(SnakeSetOp.UNION_ALL, self, other)

    def except_(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`EXCEPT`: the left-hand ones that are NOT in the right-hand one. With a trailing underscore: it is a reserved word."""
        return _compose(SnakeSetOp.EXCEPT, self, other)

    def intersect(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`INTERSECT`: only the ones that are in BOTH."""
        return _compose(SnakeSetOp.INTERSECT, self, other)

    def to_sql(self, dialect: SnakeDialect) -> tuple[str, tuple[object, ...]]:
        """Compiles to `(sql, params)` concatenating the branches in textual order.

        Each branch inside parentheses: without them a branch's `LIMIT` would read as the set's. The
        `ORDER BY` goes UNqualified: the result is no table, its columns are the projection's.
        """
        params: list[object] = []
        left_sql = self._branch_sql(self.left, dialect, params, regroups=False)
        right_sql = self._branch_sql(self.right, dialect, params, regroups=True)
        sql = f"{left_sql} {self.operator.value} {right_sql}"

        if self.order_by_keys:
            keys = ", ".join(
                emit_order_key(key, dialect, params, None) for key in self.order_by_keys
            )
            sql = f"{sql} ORDER BY {keys}"

        clause = dialect.limit_offset(self.limit_value, self.offset_value, params)
        if clause:
            sql = f"{sql} {clause}"
        return sql, tuple(params)

    @staticmethod
    def _branch_sql(
        branch: SnakeCompoundBranch[T],
        dialect: SnakeDialect,
        params: list[object],
        *,
        regroups: bool,
    ) -> str:
        """Compiles one branch and accumulates its params into the shared list, in textual order.

        The parentheses (only if the engine admits them) keep the branch's own tail —and its own
        grouping— inside the branch. Where they are not available, what cannot be written is
        REFUSED instead of emitted as something else. `regroups` says whether this position needs
        the grouping preserved: see `_refuse_what_cannot_be_written`.
        """
        _refuse_what_cannot_be_written(branch, dialect, regroups=regroups)
        sql, branch_params = branch.to_sql(dialect)
        params.extend(branch_params)
        if dialect.supports_parenthesised_compound:
            return f"({sql})"
        return sql


def _refuse_what_cannot_be_written(
    branch: SnakeCompoundBranch[T],
    dialect: SnakeDialect,
    *,
    regroups: bool,
) -> None:
    """Stops a branch this engine cannot express, before it turns into SQL that means something else.

    THREE refusals, and the middle one is the expensive one:

    - A CTE in a branch. Only Postgres takes it; SQLite answers `near "WITH": syntax error` and
      MySQL 1064, which is the driver complaining about SQL the user never wrote.
    - A branch that is ITSELF a set, in the position where the grouping matters. Without
      parentheses the engine reads the operators left to right, so `A UNION (B EXCEPT C)` becomes
      `(A UNION B) EXCEPT C`: valid SQL, different rows, no error anywhere. Measured over the 4x4
      operator matrix against the three engines, 12 of the 16 pairs disagreed. Nesting to the LEFT
      is not refused, because left-to-right IS the grouping the bare text already has.
    - A branch with its own `order_by`/`limit`/`offset`: without parentheses the tail reads as
      belonging to the whole set. The bound was guarded and the ordering was not, though the two
      need the same parentheses.
    """
    if branch.has_cte and not dialect.supports_cte_in_compound_branch:
        raise SnakeEmitError(
            "This engine does not accept a WITH RECURSIVE inside a branch of a "
            "UNION/EXCEPT/INTERSECT, so a recursion cannot be composed with a set operation here "
            "(only Postgres takes it). Run the recursion as its own query and combine the rows "
            "afterwards."
        )
    if dialect.supports_parenthesised_compound:
        return
    if regroups and isinstance(branch, SnakeCompound):
        raise SnakeEmitError(
            "This engine does not accept parentheses around the branches of a "
            "UNION/EXCEPT/INTERSECT, so a branch that is itself a UNION/EXCEPT/INTERSECT is "
            "inexpressible: without the parentheses the engine reads the operators left to right "
            "and composes a DIFFERENT set, with no error. Chain to the left instead "
            "(a.union(b).except_(c)), which means what it says on every engine, or run the inner "
            "set as its own query."
        )
    if branch.has_bounds or branch.has_order:
        raise SnakeEmitError(
            "This engine does not accept parentheses around the branches of a "
            "UNION/EXCEPT/INTERSECT, so a branch with its own limit()/offset()/order_by() is "
            "inexpressible: the tail would read as belonging to the whole set. Drop it from the "
            "branch, or order and bound the set with .order_by()/.limit() on the compound."
        )


def _compose(
    operator: SnakeSetOp,
    left: SnakeCompoundBranch[T],
    right: SnakeCompoundBranch[T],
) -> SnakeCompound[T]:
    """Builds the compound, rejecting whatever does not survive a set operation.

    An `include(...)` (relationships by JOIN) and a `for_update()` do not survive: the set's columns
    are the projection's. They are rejected at COMPOSE time, when the user still knows why they wrote it.
    """
    for branch in (left, right):
        if branch.has_includes:
            raise SnakeEmitError(
                "A query with include(...) cannot be composed with UNION/EXCEPT/INTERSECT: the "
                "columns of the set are those of the projection, so the loaded relationships "
                "would be lost. Compose the queries without include and load the relationships "
                "afterwards."
            )
        if branch.has_lock:
            raise SnakeEmitError(
                "A query with for_update() cannot be composed with UNION/EXCEPT/INTERSECT: the "
                "result of a set is not the rows of a specific table, so there is nothing to "
                "lock (Postgres forbids it explicitly). Lock the rows in a separate query on "
                "the table you want to reserve."
            )

    # RUNTIME BACKUP to the type lock: `.union` already demands the SAME model statically, but SQL
    # only demands that the number and types of the columns line up, so a UNION between similar
    # tables runs and the session instantiates every row as the first branch's model, with no error.
    if left.model is not right.model:
        raise SnakeEmitError(
            f"UNION/EXCEPT/INTERSECT demands that both queries be of the SAME model, and here "
            f"they are {left.model.__name__} and {right.model.__name__}. SQL only checks that the "
            f"columns line up, so this would run and return rows of one table instantiated as "
            f"the other, with the values in the wrong fields."
        )

    # THE SAME GUARD ONE LEVEL DOWN, over the columns instead of the table. `SELECT id, amount UNION
    # SELECT id, status` compiles wherever the types agree, and the session hydrates every row
    # against ONE of the two projections.
    if left.projected_columns != right.projected_columns:
        raise SnakeEmitError(
            "UNION/EXCEPT/INTERSECT demands that both queries project the SAME columns, and here "
            "they do not. SQL lines two projections up by position, so this would run and return "
            "rows with their values in the wrong fields. Say the same only()/defer() on both "
            "branches, or narrow neither."
        )
    return SnakeCompound(operator=operator, left=left, right=right)
