"""JOIN planning for deep navigation: relationship paths → aliases + JOIN clauses.

A path is `("rel1", ..., "column")`. It assigns an alias to the root (t0) and to every unique prefix
(t1...), one JOIN per prefix, ordered from parent to child; shared prefixes reuse an alias. It lives
in `sql/` because it emits SQL; each relationship's target is resolved by an injected
`resolve_target`.
"""

from __future__ import annotations

from collections.abc import Iterable

from snakeorm.dialects import SnakeDialect
from snakeorm.sql.resolver import SnakeRelationshipResolver
from snakeorm.core.exceptions import (
    SnakeRegistryError,
    SnakeUnknownRelationship,
    SnakeUnsupportedFeature,
)
from snakeorm.metadata import (
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.sql.refs import qualified


class JoinPlan:
    """Resolves a set of relationship paths against the graph → aliases + JOIN clauses."""

    def __init__(
        self,
        root: SnakeTableInfo,
        paths: Iterable[tuple[str, ...]],
        dialect: SnakeDialect,
        resolver: SnakeRelationshipResolver,
        relationship_paths: Iterable[tuple[str, ...]] = (),
        explicit_joins: Iterable[tuple[tuple[str, ...], bool]] = (),
    ) -> None:
        self._dialect = dialect
        self._resolver = resolver
        self._alias: dict[tuple[str, ...], str] = {(): "t0"}
        self._table: dict[tuple[str, ...], SnakeTableInfo] = {(): root}
        self._joins: list[str] = []

        # FILTER/order prefixes: paths ending in a column → INNER JOIN.
        filter_prefixes: set[tuple[str, ...]] = set()
        for path in paths:
            steps = path[:-1]  # the last element is the column, not a relationship
            for length in range(1, len(steps) + 1):
                filter_prefixes.add(steps[:length])
        # INCLUDE prefixes: these are relationships to load → LEFT JOIN (does not lose rows with a
        # null FK).
        include_prefixes: set[tuple[str, ...]] = set()
        for path in relationship_paths:
            for length in range(1, len(path) + 1):
                include_prefixes.add(path[:length])
        # EXPLICIT JOINs (`.join()`): a to-many IS allowed (it multiplies rows on purpose) and its
        # `how` overrides the inference. It is the ONLY route by which a to-many gets joined.
        explicit: dict[tuple[str, ...], bool] = dict(explicit_joins)
        # Sort by length (parent before child) and then lexicographically (deterministic).
        every = filter_prefixes | include_prefixes | set(explicit)
        for prefix in sorted(every, key=lambda p: (len(p), p)):
            if prefix in explicit:
                # The explicit `how` wins; the to-many is allowed (it is what was asked for).
                self._add_join(prefix, left=explicit[prefix], allow_to_many=True)
                continue
            # LEFT only if it is a pure include; if it is also filtered, INNER (the filter already
            # demands a match).
            left = prefix in include_prefixes and prefix not in filter_prefixes
            self._add_join(prefix, left=left)

    @property
    def root_alias(self) -> str:
        """Alias of the query's root table."""
        return "t0"

    @property
    def has_joins(self) -> bool:
        """Tells whether the plan generated any JOIN (there is relationship navigation)."""
        return bool(self._joins)

    @property
    def joins(self) -> tuple[str, ...]:
        """The JOIN clauses in parent-to-child order."""
        return tuple(self._joins)

    def alias_for(self, prefix: tuple[str, ...]) -> str:
        """Alias of the table reached by a relationship prefix (`()` = root)."""
        return self._alias[prefix]

    def table_for(self, prefix: tuple[str, ...]) -> SnakeTableInfo:
        """Table reached by a relationship prefix (`()` = root). For the SELECT of includes."""
        return self._table[prefix]

    def _add_join(
        self, prefix: tuple[str, ...], left: bool = False, allow_to_many: bool = False
    ) -> None:
        """Registers the prefix's JOIN leaning on its parent (already present thanks to the order).

        A to-many is only joined with `allow_to_many` (an explicit `.join()`): in any other case
        duplicating rows would be a silent bug, so it is rejected.
        """
        parent = prefix[:-1]
        relationship = self._relationship(self._table[parent], prefix[-1])
        if relationship.kind is SnakeRelationshipKind.TO_MANY and not allow_to_many:
            # A to-many would duplicate rows and its ON would go the other way round (the FK lives
            # in the child). The type net already forbids it; this is the runtime one.
            raise SnakeUnsupportedFeature(
                f"'{prefix[-1]}' is a to-many relationship and changes the number of rows. "
                f"Use <Model>.{prefix[-1]}.any(...) to filter by existence, "
                f"or .join(...) if you want the child rows."
            )
        # Through the RELATIONSHIP, not through its class name. `.target` is the class name, and
        # the qualified name the linker computed —`relationship.target_table`— sits on this very
        # object; asking by name went through the index `register()` overwrites in silence, so two
        # apps with their own `Customer` in one process produced a JOIN onto the wrong table. Valid
        # SQL, real rows, no warning. `resolve_relationship` already preferred the qualified name
        # and its docstring already said it existed "so that fixing the wrong target is ONE change
        # and not twelve copies" — twelve places used it and these six did not.
        target, _ = self._resolver.resolve_relationship(relationship)
        if target is None:
            raise SnakeRegistryError(
                f"The target '{relationship.target}' of relationship "
                f"'{prefix[-1]}' is not registered."
            )
        alias = f"t{len(self._alias)}"
        self._alias[prefix] = alias
        self._table[prefix] = target

        quote = self._dialect.quote_ident
        parent_alias = self._alias[parent]
        if relationship.kind is SnakeRelationshipKind.TO_MANY:
            # In a to-many the FK lives in the CHILD, so the ON is written the other way round:
            # `child.fk = parent.pk`. Its pairs are (child_column, parent_column), precisely so the
            # direction is not flipped.
            on = " AND ".join(
                f"{alias}.{quote(child_col)} = {parent_alias}.{quote(parent_col)}"
                for child_col, parent_col in relationship.foreign_key.pairs
            )
        else:
            on = " AND ".join(
                f"{parent_alias}.{quote(local)} = {alias}.{quote(remote)}"
                for local, remote in relationship.foreign_key.pairs
            )
        table_ref = qualified(target.schema, target.name, self._dialect)
        keyword = "LEFT JOIN" if left else "JOIN"
        self._joins.append(f"{keyword} {table_ref} AS {alias} ON {on}")

    @staticmethod
    def _relationship(table: SnakeTableInfo, name: str) -> SnakeRelationshipInfo:
        """Looks the relationship up by name on the table; fails clearly if it does not exist."""
        for relationship in table.relationships:
            if relationship.name == name:
                return relationship
        raise SnakeUnknownRelationship(
            f"'{table.name}' does not have a relationship named '{name}'."
        )
