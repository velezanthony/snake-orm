"""SnakeJoinedQuery: a query with EXPLICIT JOIN(s) onto a collection.

A JOIN onto a collection MULTIPLIES rows (one per child): correct for TUPLES, a disaster for models.
That is why `.join()` returns a DIFFERENT type that only projects (no `.all()`/`.first()`):
hydrating multiplied models is a type error.

THE ALIAS PROBLEM: `Maker.name` gives the path `("name",)`, which in a query rooted at Nation would
be qualified with the ROOT's alias (wrong SQL). `joined.right` is a `SnakePathProxy` over the JOIN's
prefix: `joined.right.name` gives `("makers", "name")`, qualified with the JOIN's alias. Statically
`right` is `type[M]`; at runtime it is the proxy (the same trick as `SnakeToOne.__get__`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.expressions import SnakeCondition, SnakeExpr, SnakeOrder, SnakeValue
from snakeorm.fields.relationship import (
    SnakeCollection,
    SnakePathProxy,
    _registry_of,
)
from snakeorm.metadata import SnakeTableInfo
from snakeorm.query.join_kind import SnakeJoin
from snakeorm.query.query import SnakeQuery, _include_path, _relationship
from snakeorm.registry import registry

T = TypeVar("T")
M = TypeVar("M")
N = TypeVar("N")


@dataclass(frozen=True, slots=True)
class _JoinSpec:
    """An explicit JOIN, already resolved: prefix (relative to the root), whether it is LEFT, and the child table."""

    prefix: tuple[str, ...]
    left: bool
    child_table: SnakeTableInfo


def _child_table_for(root: SnakeTableInfo, prefix: tuple[str, ...]) -> SnakeTableInfo:
    """Resolves the table reached by a prefix of relationships from the root (it walks the graph)."""
    table = root
    for step in prefix:
        relationship = _relationship(table, step)
        target = registry.resolve_relationship(relationship)[0]
        if target is None:
            raise SnakeRegistryError(
                f"The target '{relationship.target}' of relationship '{step}' is not registered."
            )
        table = target
    return table


def _resolve_join(
    root_model: type[Any], collection: SnakeCollection[Any], how: SnakeJoin
) -> _JoinSpec:
    """Builds the `_JoinSpec` of a `.join()`: it extracts the prefix and resolves the child table.

    `collection` is the class access to a to-many: a real `SnakeCollection` (`.path`) on the first
    `.join()`, or a `SnakePathProxy` with the accumulated prefix on a chained `.join()`.
    """
    root_table = registry.table_of(root_model)
    if root_table is None:
        raise SnakeRegistryError(
            f"{root_model.__name__} is not registered: is it missing @snake_model?"
        )
    prefix = _include_path(collection)
    child_table = _child_table_for(root_table, prefix)
    return _JoinSpec(prefix=prefix, left=how is SnakeJoin.LEFT, child_table=child_table)


class SnakeJoinedQuery(Generic[T, M]):
    """Query with explicit JOIN(s) onto collections. Projectable only; immutable.

    `T` is the ROOT model; `M` that of the last joined child (exposed by `.right`). It delegates the
    normal state to a wrapped `SnakeQuery[T]` and adds the list of explicit JOINs.
    """

    __slots__ = ("_query", "_joins")

    def __init__(self, query: SnakeQuery[T], joins: tuple[_JoinSpec, ...]) -> None:
        self._query = query
        self._joins = joins

    @property
    def model(self) -> type[T]:
        """The ROOT model. The session uses it to qualify/coerce the projection."""
        return self._query.model

    @property
    def right(self) -> type[M]:
        """Right-hand side of the LAST JOIN, with the path already prefixed with the right alias.

        Statically `type[M]` (`joined.right.name` re-triggers the class access -> `SnakeExpr`); at
        runtime a `SnakePathProxy` whose path (`("makers","name")`) is qualified with the JOIN's
        alias, not the root's.
        """
        spec = self._joins[-1]
        proxy = SnakePathProxy(spec.child_table, spec.prefix, _registry_of(self.model))
        return cast("type[M]", proxy)

    def filter(self, *conditions: SnakeCondition) -> SnakeJoinedQuery[T, M]:
        """Adds conditions (AND) to the WHERE. Returns a NEW query; the current one is untouched."""
        return SnakeJoinedQuery(self._query.filter(*conditions), self._joins)

    def order_by(self, *keys: SnakeExpr[Any] | SnakeOrder) -> SnakeJoinedQuery[T, M]:
        """Adds ordering keys. It can order by the child's columns (`joined.right.col`)."""
        return SnakeJoinedQuery(self._query.order_by(*keys), self._joins)

    def limit(self, limit: int) -> SnakeJoinedQuery[T, M]:
        """Sets the LIMIT (it replaces the previous one). Returns a new query."""
        return SnakeJoinedQuery(self._query.limit(limit), self._joins)

    def offset(self, offset: int) -> SnakeJoinedQuery[T, M]:
        """Sets the OFFSET (it replaces the previous one). Returns a new query."""
        return SnakeJoinedQuery(self._query.offset(offset), self._joins)

    def distinct(self) -> SnakeJoinedQuery[T, M]:
        """Marks the projection as `SELECT DISTINCT`. Returns a new query."""
        return SnakeJoinedQuery(self._query.distinct(), self._joins)

    def join(
        self, collection: SnakeCollection[N], how: SnakeJoin = SnakeJoin.INNER
    ) -> SnakeJoinedQuery[T, N]:
        """Chains ANOTHER explicit JOIN (starting from `joined.right.<collection>`).

        The new child `N` becomes the right-hand side of `.right`, with its accumulated prefix.
        """
        spec = _resolve_join(self._query.model, collection, how)
        return SnakeJoinedQuery(self._query, (*self._joins, spec))

    def to_project_sql(
        self, dialect: SnakeDialect, columns: Sequence[SnakeValue[Any]]
    ) -> tuple[str, tuple[object, ...]]:
        """Compiles the projection combining the explicit JOINs with the column/WHERE/order paths."""
        explicit = tuple((spec.prefix, spec.left) for spec in self._joins)
        return self._query.to_project_sql(dialect, columns, explicit_joins=explicit)
