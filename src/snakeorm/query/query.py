"""SnakeQuery: an IMMUTABLE builder of queries over a compiled model.

`.filter()`/`.order_by()`/... accumulate state by returning a NEW query; `.to_sql(dialect)` compiles
to `(sql, params)`. EXECUTION does not live here (that is `session/`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import (
    SnakeEmitError,
    SnakeRegistryError,
    SnakeUnknownColumn,
    SnakeUnknownRelationship,
    SnakeUnsupportedFeature,
)
from snakeorm.expressions import (
    SnakeAnd,
    SnakeCondition,
    SnakeExpr,
    SnakeLock,
    SnakeOrder,
    SnakeSubquery,
    SnakeValue,
    condition_paths,
)
from snakeorm.fields.relationship import SnakeCollection, SnakePathProxy, SnakePrefetch
from snakeorm.helpers.inheritance import is_abstract
from snakeorm.metadata import (
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.query.compound import (
    SnakeCompoundBranch,
    SnakeCompound,
    SnakeSetOp,
    _compose,
)
from snakeorm.query.join_kind import SnakeJoin
from snakeorm.query.recursive import SnakeRecursive, build_recursive
from snakeorm.registry import SnakeRegistry, registry, registry_of
from snakeorm.sql import (
    JoinPlan,
    emit_count,
    emit_delete,
    emit_delete_pk_in_subquery,
    emit_exists,
    emit_project,
    emit_select,
    emit_select_with_includes,
    emit_update,
    emit_update_pk_in_subquery,
)

if TYPE_CHECKING:
    # Import for the checker only: `compound` imports this module (it needs the type of the
    # branches), so at module level it would be a cycle. The composition methods import it inside.
    from snakeorm.query.joined import SnakeJoinedQuery

T = TypeVar("T")
V = TypeVar("V")
M = TypeVar("M")

IncludeSegment = tuple[tuple[str, ...], type, SnakeTableInfo]


def _include_path(relation: type[Any] | SnakeCollection[Any]) -> tuple[str, ...]:
    """Extracts the path of a class navigation for `.include()`.

    A to-many arrives as a `SnakeCollection` (`.path`); a to-one as a `SnakePathProxy` (even though
    the checker sees it as `type[M]`), with the path in `._path`. A column is not navigable: it gets
    rejected in plain words.
    """
    if isinstance(relation, SnakeCollection):
        return relation.path
    if isinstance(relation, SnakePathProxy):
        return relation._path
    # A column (`SnakeExpr`) is not navigable: `.include(Model.column)` makes no sense. The checker
    # already rejects it (`[arg-type]`), but whoever skips the types deserves a clear message and not
    # an `AttributeError: 'SnakeExpr' has no '_path'` from the builder's guts.
    detail = (
        f" (got {'.'.join(relation.path)})" if isinstance(relation, SnakeExpr) else ""
    )
    raise SnakeUnknownRelationship(
        f"`.include()` expects a RELATIONSHIP (a `SnakeToOne`/`SnakeToMany`), not a column and "
        f"not an expression{detail}. To bring related data in, navigate to the relationship, "
        f"e.g. `.include(Car.brand)`."
    )


def _relationship(table: SnakeTableInfo, name: str) -> SnakeRelationshipInfo:
    """Looks a relationship up by name in the table; fails in plain words if it does not exist."""
    for relationship in table.relationships:
        if relationship.name == name:
            return relationship
    raise SnakeUnknownRelationship(
        f"'{table.name}' does not have a relationship named '{name}'."
    )


def _discriminator_filter(table: SnakeTableInfo) -> tuple[SnakeCondition, ...]:
    """The `WHERE kind = 'dog'` of a polymorphic child; empty for any other table.

    The BASE carries no filter: querying `Animal` must see the whole hierarchy.
    """
    if not table.is_polymorphic_child:
        return ()
    assert table.polymorphic is not None  # is_polymorphic_child guarantees it
    column: SnakeExpr[str] = SnakeExpr(path=(table.polymorphic.column,))
    return (column == table.polymorphic.value,)


# Slots that are NOT a knob: the query's identity and its WHERE, which every emitter honours.
# Everything else in `__slots__` is something the caller ASKED for, and `_guard_unsupported` derives
# the list from there so a new knob cannot be left out of the guard.
_NOT_A_KNOB = frozenset({"_model", "_table", "_filters", "_registry"})
"""Slots that are NOT something the caller asked the emitter to write.

`_registry` belongs here and forgetting it breaks EVERY select: the guards derive their list
from `__slots__` by comparing against a pristine query, and a query built on a custom registry
differs from the default one in exactly that slot — so every plain SELECT would refuse itself
with "does not emit registry()"."""

# `_prefetches` and `_includes` are honoured by the plain SELECT even though it writes NEITHER: the
# SESSION resolves them afterwards, one query per level, and `session.py:274` takes exactly this
# route when every include is a to-many. They are DEFERRED, not dropped, and the difference is the
# whole point of this guard — refusing them here turned eighteen green tests red, which is how the
# distinction got measured rather than assumed.
_HONOURED_BY_SELECT = frozenset(
    {
        "_order",
        "_limit",
        "_offset",
        "_distinct",
        "_lock",
        "_includes",
        "_prefetches",
        "_columns",
    }
)

# A COUNT ignores order/limit/offset by design (they do not change how many rows match) and the
# includes do not change the number of ROOT rows either. What it cannot ignore is `group_by`,
# `having` and `distinct`: each of those makes the answer a different number.
_HONOURED_BY_COUNT = frozenset(
    {"_order", "_limit", "_offset", "_includes", "_prefetches"}
)
_HONOURED_BY_INCLUDES = frozenset(
    {"_order", "_limit", "_offset", "_includes", "_prefetches"}
)

# How a knob is SPELT by the person who set it. A message that says `lock` sends the reader looking
# for something they never typed; they typed `for_update()`. Only the knobs whose slot name differs
# from their method need an entry — the rest fall back to the slot, so this cannot go stale into a
# wrong answer, only into a duller one.
_KNOB_SPELLING = {
    "_lock": "for_update()",
    "_includes": "include()",
    "_prefetches": "include()",
    "_order": "order_by()",
    "_columns": "only()/defer()",
}
"""How each knob is SPELLED to the user. The fallback —the slot without its underscore— only works
where the two happen to match, and where they do not the message names a method that does not
exist: `_order` came out as `order()`, `_prefetches` as `prefetches()`. Somebody reading that goes
looking for a call they never made."""

# What to do INSTEAD, per knob rather than per path. The remedy each caller passes describes its own
# emitter —"count the projection", "lock in a separate query"— and that is right until two different
# knobs are dropped at once: the message then names `columns()` and advises about locking, which
# reads like the ORM answering a question nobody asked. Measured on the first `only().include()`.
#
# Only the knobs whose remedy does not depend on the path get an entry, which is why this is small.
_KNOB_REMEDY = {
    "_columns": (
        "Ask for the columns with select(...) if what you want is the values, or drop the "
        "only()/defer()."
    ),
}


class SnakeQuery(Generic[T]):
    """Typed query over a model. Immutable: every method returns a new query."""

    __slots__ = (
        "_model",
        "_table",
        "_filters",
        "_order",
        "_limit",
        "_offset",
        "_includes",
        "_prefetches",
        "_group_by",
        "_having",
        "_distinct",
        "_lock",
        "_columns",
        "_registry",
    )

    def __init__(
        self, model: type[T], *, registry: SnakeRegistry | None = None
    ) -> None:
        """The query and the REGISTRY it resolves against, which is the model's unless told otherwise.

        It used to ask the global registry unconditionally, so `@snake_model(registry=reg)`
        produced a model that could not be queried — and said so with a message that MISDIRECTED:
        "is it missing @snake_model?", with the decorator right there. The answer was one `getattr`
        away the whole time.

        `registry=` is for the case where the model itself does not say: a `SnakeRow`, or a query
        built before the decorator ran. Otherwise the model's own answer wins, which is what makes
        navigation, the session and the emitter agree without anybody threading it through.
        """
        registry = registry_of(model) if registry is None else registry
        table = registry.table_of(model)
        if table is None:
            # An abstract base is NOT an oversight, and suggesting @snake_model would be sending
            # them off to turn into a table something that exists precisely so as not to be one.
            if is_abstract(model):
                raise SnakeRegistryError(
                    f"{model.__name__} is an abstract base (@snake_abstract): it contributes its "
                    f"columns to the tables that inherit from it, but it is not a table and "
                    f"cannot be queried. Query the concrete model that inherits it."
                )
            raise SnakeRegistryError(
                f"{model.__name__} is not registered: is it missing @snake_model?"
            )
        self._model = model
        self._table = table
        self._registry = registry
        # A polymorphic CHILD starts out with its discriminator filtered: it shares a table with
        # its siblings, so `session.all(Dog)` would otherwise also return cats hydrated as dogs.
        # It goes in the constructor (not in the emitter) so every path inherits it for free (all,
        # first, count, exists, delete_where...).
        self._filters: tuple[SnakeCondition, ...] = _discriminator_filter(table)
        self._order: tuple[SnakeOrder, ...] = ()
        self._limit: int | None = None
        self._offset: int | None = None
        self._includes: tuple[tuple[str, ...], ...] = ()
        self._prefetches: tuple[SnakePrefetch[Any], ...] = ()
        self._group_by: tuple[SnakeValue[Any], ...] = ()
        self._having: tuple[SnakeCondition, ...] = ()
        self._distinct: bool = False
        self._lock: SnakeLock | None = None
        # The columns to bring, by NAME, or `None` for "all of them". It is the resolved set and not
        # the user's two verbs, because `only` and `defer` are one question asked from two sides and
        # keeping both would mean every reader downstream doing the subtraction again.
        self._columns: frozenset[str] | None = None

    @property
    def projected_columns(self) -> frozenset[str] | None:
        """The columns `only()`/`defer()` asked for, or `None` for every one of them.

        The session asks for this rather than counting the row's width: two columns of one table can
        be projected two ways, and lining a plan up by counting is how a value lands on the wrong
        attribute without anybody noticing.
        """
        return self._columns

    @property
    def model(self) -> type[T]:
        """The model being queried. The session uses it to map the rows back to T."""
        return self._model

    def filter(self, *conditions: SnakeCondition) -> SnakeQuery[T]:
        """Adds conditions (AND). Returns a NEW query; the current one is untouched."""
        clone = self._clone()
        clone._filters = (*self._filters, *conditions)
        return clone

    @property
    def registry(self) -> SnakeRegistry:
        """The registry this query resolves against: the model's own unless one was passed.

        Public because the SESSION has to ask it. Reaching for the global registry there is the same
        defect one layer up: it works until two models share a class name, or until somebody uses
        `@snake_model(registry=...)`, and then it is wrong in silence.
        """
        return self._registry

    def order_by(self, *keys: SnakeExpr[Any] | SnakeOrder) -> SnakeQuery[T]:
        """Adds ordering keys. A bare column orders ascending."""
        normalized = tuple(
            key if isinstance(key, SnakeOrder) else key.asc() for key in keys
        )
        clone = self._clone()
        clone._order = (*self._order, *normalized)
        return clone

    def limit(self, limit: int) -> SnakeQuery[T]:
        """Sets the LIMIT (it replaces the previous one). Returns a new query."""
        clone = self._clone()
        clone._limit = limit
        return clone

    def offset(self, offset: int) -> SnakeQuery[T]:
        """Sets the OFFSET (it replaces the previous one). Returns a new query."""
        clone = self._clone()
        clone._offset = offset
        return clone

    def group_by(self, *columns: SnakeValue[Any]) -> SnakeQuery[T]:
        """Groups by the given columns. Returns a NEW query; the current one is untouched."""
        clone = self._clone()
        clone._group_by = (*self._group_by, *columns)
        return clone

    def having(self, condition: SnakeCondition) -> SnakeQuery[T]:
        """Filters over the groups (cumulative with AND, just like `.filter()`)."""
        clone = self._clone()
        clone._having = (*self._having, condition)
        return clone

    def distinct(self) -> SnakeQuery[T]:
        """Marks the query as `SELECT DISTINCT`. Returns a new query.

        It applies to the full SELECT and to the projection. Standard `DISTINCT` only (no `DISTINCT ON`).
        """
        clone = self._clone()
        clone._distinct = True
        return clone

    def only(self, *columns: SnakeValue[Any]) -> SnakeQuery[T]:
        """Brings ONLY these columns (plus the primary key). Returns a new query.

        What it buys is bytes on a wide table; what it costs is an instance that is not whole, and
        reading a column left out RAISES rather than handing back the column's default. That refusal
        is the feature: without it a deferred name reads as `None` and the caller never learns.

        The PRIMARY KEY comes back whether it was named or not, and that is not a convenience. An
        instance with no identity cannot be updated, deleted, or matched to the children of a
        prefetch — it would be a tuple with methods.

        When what you want is the VALUES rather than the model, `session.select(query, a, b)` is the
        better tool: typed tuples, no half-built instance, and nothing that can raise later.
        """
        return self._with_columns(self._named(columns), verb="only")

    def defer(self, *columns: SnakeValue[Any]) -> SnakeQuery[T]:
        """Brings everything EXCEPT these columns. Returns a new query.

        The other side of `only()`, and the same warning applies to what comes back. Deferring the
        primary key is refused: see `only()`.
        """
        deferred = self._named(columns)
        keys = {column.name for column in self._table.primary_key.columns}
        if deferred & keys:
            raise SnakeUnsupportedFeature(
                f"the primary key cannot be deferred ({', '.join(sorted(deferred & keys))}): a row "
                f"with no identity cannot be written back nor matched to its relations. Deferring "
                f"is for the wide columns a page does not print."
            )
        every = {column.name for column in self._table.columns}
        return self._with_columns(every - deferred, verb="defer")

    def _named(self, columns: tuple[SnakeValue[Any], ...]) -> set[str]:
        """The column NAMES behind the given expressions, refusing anything this table lacks."""
        known = {column.name for column in self._table.columns}
        names: set[str] = set()
        for column in columns:
            path = getattr(column, "path", None)
            if path is None or len(path) != 1 or path[0] not in known:
                raise SnakeUnknownColumn(
                    f"only()/defer() take columns of {self._model.__name__} itself; got "
                    f"{column!r}. A column of a related model cannot be deferred: it arrives "
                    f"through its own include()."
                )
            names.add(path[0])
        return names

    def _with_columns(self, columns: set[str], *, verb: str) -> SnakeQuery[T]:
        """Records the resolved column set, refusing a second, contradictory answer."""
        if self._columns is not None:
            raise SnakeUnsupportedFeature(
                f"this query already names the columns to bring; a second {verb}() would be a "
                f"second answer to one question. Say it once, with every column it needs."
            )
        if not columns:
            raise SnakeUnsupportedFeature(
                f"{verb}() would leave the row with no columns at all"
            )
        clone = self._clone()
        # The PK always travels, whether or not it was named: an instance without identity cannot be
        # updated, deleted, or matched to the children of a prefetch.
        clone._columns = frozenset(
            columns | {column.name for column in self._table.primary_key.columns}
        )
        return clone

    def for_update(
        self, *, nowait: bool = False, skip_locked: bool = False
    ) -> SnakeQuery[T]:
        """Locks the selected rows until the end of the transaction (`SELECT ... FOR UPDATE`).

        It is HALF of concurrency control (the other half is the isolation level). `nowait` fails if
        the row is already locked; `skip_locked` ignores it (the queue pattern): they are opposites,
        asking for both is an error.
        """
        if nowait and skip_locked:
            raise SnakeUnsupportedFeature(
                'nowait and skip_locked are mutually exclusive: one says "if it is locked, fail" '
                'and the other "if it is locked, skip it". Choose the behaviour you want.'
            )
        if self._table.is_view:
            raise SnakeUnsupportedFeature(
                f"'{self._table.name}' is a READ-ONLY view: there is nothing of its own to lock. "
                f"Lock the rows of the base table."
            )
        clone = self._clone()
        if skip_locked:
            clone._lock = SnakeLock.SKIP_LOCKED
        elif nowait:
            clone._lock = SnakeLock.NOWAIT
        else:
            clone._lock = SnakeLock.WAIT
        return clone

    def join(
        self, collection: SnakeCollection[M], how: SnakeJoin = SnakeJoin.INNER
    ) -> SnakeJoinedQuery[T, M]:
        """EXPLICITLY joins a collection (to-many) to get THE CHILD'S ROWS into the projection.

        It returns a `SnakeJoinedQuery`, a different type that only projects: a JOIN onto a
        collection multiplies rows (a disaster for models), so it has no `.all()`/`.first()`. `how`
        chooses whether childless parents show up.
        """
        from snakeorm.query.joined import SnakeJoinedQuery, _resolve_join

        spec = _resolve_join(self._model, collection, how)
        return SnakeJoinedQuery(self, (spec,))

    def as_scalar(self, column: SnakeExpr[V]) -> SnakeSubquery[V]:
        """Wraps the query as a scalar subquery of ONE column, for `.in_(...)`.

        DIRECT column and flat WHERE only: navigating a relationship would demand a JOIN inside the
        subquery, which is not built yet, so it gets rejected in plain words.
        """
        if len(column.path) != 1:
            raise SnakeUnsupportedFeature(
                "a scalar subquery projects a direct column of its table, not a deep navigation "
                "of relationships."
            )
        where = self._combined_where()
        if where is not None and any(len(path) > 1 for path in condition_paths(where)):
            raise SnakeUnsupportedFeature(
                "the WHERE of a scalar subquery cannot navigate relationships (the JOIN inside the "
                "subquery is not built yet); filter by direct columns."
            )
        return SnakeSubquery(
            schema=self._table.schema,
            name=self._table.name,
            column=column.path[0],
            where=where,
        )

    def include(
        self, *relations: type[Any] | SnakeCollection[Any] | SnakePrefetch[Any]
    ) -> SnakeQuery[T]:
        """Asks for relationships to be loaded (eagerly). Returns a new query.

        To-one (`User.car`, proxies carrying a path) -> LEFT JOIN; to-many (`SnakeCollection`) ->
        select-in. To nest to-many you pass a `SnakePrefetch(...).then(...)` (the collection does not
        expose the child's relationships). Without `.include()`, touching the relationship blows up
        with `SnakeRelationshipNotLoaded` (there is no silent N+1).
        """
        prefetches = tuple(r for r in relations if isinstance(r, SnakePrefetch))
        paths = tuple(
            _include_path(r) for r in relations if not isinstance(r, SnakePrefetch)
        )
        clone = self._clone()
        clone._includes = (*self._includes, *paths)
        clone._prefetches = (*self._prefetches, *prefetches)
        return clone

    @property
    def has_includes(self) -> bool:
        """Tells whether the query asks for relationships to be loaded (it picks the session's route)."""
        return bool(self._includes) or bool(self._prefetches)

    @property
    def has_lock(self) -> bool:
        """Tells whether the query asks for rows to be locked (`for_update`). The compound looks at this."""
        return self._lock is not None

    @property
    def has_bounds(self) -> bool:
        """Tells whether the query carries `limit`/`offset` of its own. The compound looks at this."""
        return self._limit is not None or self._offset is not None

    @property
    def has_order(self) -> bool:
        """Tells whether the query carries `order_by` of its own. The compound looks at this.

        The same question as `has_bounds` and for the same reason: both need the branch's
        parentheses to stay inside the branch, and only one of the two was being asked.
        """
        return bool(self._order)

    @property
    def has_cte(self) -> bool:
        """Whether the emitted SQL opens with a `WITH`. A plain query never does."""
        return False

    def prefetches(self) -> tuple[SnakePrefetch[Any], ...]:
        """Nested prefetch chains (deep to-many); the session resolves them level by level."""
        return self._prefetches

    def to_one_includes(self) -> tuple[tuple[str, ...], ...]:
        """Includes that are to-one chains (loaded with a JOIN in the same query)."""
        return self._classify_includes()[0]

    def to_many_includes(self) -> tuple[SnakeRelationshipInfo, ...]:
        """To-many relationships to load (resolved with a separate select-in, in the session)."""
        return self._classify_includes()[1]

    def _classify_includes(
        self,
    ) -> tuple[tuple[tuple[str, ...], ...], tuple[SnakeRelationshipInfo, ...]]:
        """Splits the includes into to-one chains (JOIN) and to-many relationships (select-in).

        By direct navigation only these are admitted: to-one chains and a to-many of ONE hop.
        Nesting to-many or mixing them is done with `SnakePrefetch(...)`.
        """
        to_one: list[tuple[str, ...]] = []
        to_many: list[SnakeRelationshipInfo] = []
        for path in self._includes:
            kinds = self._hop_kinds(path)
            # A SINGLE to-many hop (direct or through a bridge) -> select-in. It is compared against
            # the enum, not against tuples of strings (that comparison stayed False forever and
            # disabled to-many loading; mypy caught it).
            if kinds in (
                (SnakeRelationshipKind.TO_MANY,),
                (SnakeRelationshipKind.TO_MANY_THROUGH,),
            ):
                to_many.append(_relationship(self._table, path[0]))
            elif all(kind is SnakeRelationshipKind.TO_ONE for kind in kinds):
                to_one.append(path)
            else:
                raise SnakeUnsupportedFeature(
                    f"an include with mixed navigation or a deep to-many is not navigable: {path}. "
                    f"To nest to-many use SnakePrefetch(<collection>).then(<relationship>)."
                )
        return tuple(to_one), tuple(to_many)

    def _hop_kinds(self, path: tuple[str, ...]) -> tuple[SnakeRelationshipKind, ...]:
        """The cardinality of each hop of the path (walking the linked graph)."""
        kinds: list[SnakeRelationshipKind] = []
        table: SnakeTableInfo | None = self._table
        for step in path:
            if table is None:
                break
            relationship = _relationship(table, step)
            kinds.append(relationship.kind)
            table = registry.resolve_relationship(relationship)[0]
        return tuple(kinds)

    def include_segments(self) -> tuple[IncludeSegment, ...]:
        """Segments to load in order: root + each relationship prefix (parent before child).

        Each segment is `(prefix, model, table)`. It includes ALL the prefixes
        (`.include(User.car.brand)` also loads `car`, so brand can be nested inside car).
        """
        segments: list[IncludeSegment] = [((), self._model, self._table)]
        for prefix in self._include_prefixes():
            model: type = self._model
            table = self._table
            for step in prefix:
                relationship = _relationship(table, step)
                resolved_table, resolved_model = registry.resolve_relationship(
                    relationship
                )
                if resolved_model is None or resolved_table is None:
                    raise SnakeRegistryError(
                        f"The target '{relationship.target}' of '{step}' is not registered."
                    )
                model, table = resolved_model, resolved_table
            segments.append((prefix, model, table))
        return tuple(segments)

    def to_include_sql(self, dialect: SnakeDialect) -> tuple[str, tuple[object, ...]]:
        """Compiles the SELECT that loads the root + the included relationships (with their LEFT JOINs)."""
        self._guard_unsupported(
            "A SELECT with include(...)",
            _HONOURED_BY_INCLUDES,
            "Lock the rows in a separate query on the table you want to reserve, then load the "
            "relationships.",
        )
        where = self._combined_where()
        column_paths = condition_paths(where) if where is not None else []
        column_paths = [
            *column_paths,
            *(p for key in self._order for p in key.expr.paths()),
        ]
        plan = JoinPlan(
            self._table,
            column_paths,
            dialect,
            self._registry,
            relationship_paths=self.to_one_includes(),
        )
        segments = [
            (prefix, table) for prefix, _model, table in self.include_segments()
        ]
        return emit_select_with_includes(
            dialect,
            segments,
            plan,
            where=where,
            order_by=self._order,
            limit=self._limit,
            offset=self._offset,
        )

    def _include_prefixes(self) -> list[tuple[str, ...]]:
        """Unique prefixes of the to-one includes, sorted parent-before-child (for the JOIN)."""
        prefixes: set[tuple[str, ...]] = set()
        for path in self.to_one_includes():
            for length in range(1, len(path) + 1):
                prefixes.add(path[:length])
        return sorted(prefixes, key=lambda prefix: (len(prefix), prefix))

    def union(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`UNION`: the rows of both, WITHOUT duplicates.

        The type demands the SAME model, a guarantee SQL does not give (it is happy if the columns line up).
        """

        return _compose(SnakeSetOp.UNION, self, other)

    def union_all(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`UNION ALL`: the rows of both, KEEPING duplicates.

        It is not an optimised `UNION`: a plain `UNION` deduplicates the whole result. Both exist so
        the choice is made consciously.
        """

        return _compose(SnakeSetOp.UNION_ALL, self, other)

    def except_(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`EXCEPT`: the ones of this query that are NOT in the other. Trailing underscore: `except` is a reserved word."""

        return _compose(SnakeSetOp.EXCEPT, self, other)

    def intersect(self, other: SnakeCompoundBranch[T]) -> SnakeCompound[T]:
        """`INTERSECT`: only the rows that are in BOTH queries."""

        return _compose(SnakeSetOp.INTERSECT, self, other)

    def recursive(
        self, *, on: tuple[SnakeExpr[Any], SnakeExpr[Any]], distinct: bool = False
    ) -> SnakeRecursive[T]:
        """Expands this query by following a hop onto ITSELF (`WITH RECURSIVE`).

        This query is the ANCHOR and `on` is the pair of columns that chains each level: first the
        one pointing upwards, then the one identifying the row reached. Swapping it walks the
        ANCESTORS (perfectly legitimate).

            SnakeQuery(Category).filter(Category.id == 1).recursive(on=(Category.parent_id, Category.id))

        `distinct` picks the operator joining each step: `False` (default) emits `UNION ALL`, what a
        TREE wants; `True` emits `UNION`, so each step drops the rows already seen.

        **Pass `distinct=True` if the data may have CYCLES**, which only the caller knows — a
        self-referencing FK admits one. With `UNION ALL` a cyclic walk never ends: every lap yields
        rows the engine counts as new, so it hangs instead of failing. `limit()` is NOT a
        substitute — it bounds what comes back, not the walk. Measured on Postgres, a cyclic walk
        with `order_by()` and `LIMIT 3` never returns.
        """

        return build_recursive(self, self._table, on[0], on[1], distinct)

    def _guard_unsupported(
        self, path: str, honoured: frozenset[str], remedy: str
    ) -> None:
        """Refuses the knobs this emitter carries but does NOT emit.

        A knob that is set and not emitted is a question the caller asked and got no answer to,
        while still getting AN answer — which is the worst shape a failure can take. Three read
        paths did exactly that: the plain SELECT swallowed `group_by`/`having`, the COUNT swallowed
        those plus `distinct` (so a paginator counted rows instead of groups), and the SELECT with
        includes swallowed `for_update` (so a lock the caller asked for was never taken).

        `honoured` is what the emitter DOES write; everything else is derived from `__slots__`, so a
        tenth knob added to this class is guarded the day it appears instead of the day someone
        remembers. That is the difference between this and `_guard_bulk_write`, which lists its
        knobs by hand and is one `or` away from the same hole.
        """
        carried = {
            slot
            for slot in self.__slots__
            if slot not in _NOT_A_KNOB and getattr(self, slot)
        }
        missing = carried - honoured
        dropped = sorted(
            _KNOB_SPELLING.get(slot, f"{slot.lstrip('_')}()") for slot in missing
        )
        if dropped:
            # The per-knob remedies come first, and the path's own only if some dropped knob has
            # none of its own. Appending it always is what produced "does not emit only()/defer()
            # ... lock the rows in a separate query" — advice about a knob nobody had touched.
            advice = [
                _KNOB_REMEDY[slot] for slot in sorted(missing) if slot in _KNOB_REMEDY
            ]
            if not missing <= _KNOB_REMEDY.keys():
                advice.append(remedy)
            raise SnakeUnsupportedFeature(
                f"{path} does not emit {', '.join(dropped)}, and dropping what you asked for "
                f"would answer a different question without saying so. {' '.join(advice)}"
            )

    def to_sql(self, dialect: SnakeDialect) -> tuple[str, tuple[object, ...]]:
        """Compiles the query to `(sql, params)`, generating JOINs if there is deep navigation."""
        self._guard_unsupported(
            "A plain SELECT",
            _HONOURED_BY_SELECT,
            "Use select(...) + group_by(...) to project a grouping.",
        )
        where = self._combined_where()
        return emit_select(
            self._table,
            dialect,
            where=where,
            order_by=self._order,
            limit=self._limit,
            offset=self._offset,
            plan=self._plan(where, dialect, include_order=True),
            distinct=self._distinct,
            lock=self._lock,
            columns=self._columns,
        )

    def to_count_sql(self, dialect: SnakeDialect) -> tuple[str, tuple[object, ...]]:
        """Compiles a `SELECT COUNT(*)` with the same filters/JOINs (it ignores order and limit)."""
        self._guard_unsupported(
            "A COUNT(*)",
            _HONOURED_BY_COUNT,
            "Count the projection with select(...) if you need the number of groups or of "
            "distinct rows.",
        )
        where = self._combined_where()
        return emit_count(
            self._table, dialect, where=where, plan=self._plan(where, dialect)
        )

    def to_exists_sql(self, dialect: SnakeDialect) -> tuple[str, tuple[object, ...]]:
        """Compiles a `SELECT EXISTS(...)` with the same filters/JOINs.

        IT GUARDS THE SAME KNOBS AS THE COUNT, and it did not until this line was written. `exists`
        was the one read path that called no guard at all, so it swallowed `group_by`, `having`,
        `distinct` and `lock` in silence — an EXISTS over groups is a different question from an
        EXISTS over rows, and the caller who asked got the second one with no word about it.

        It is the same shape as entry #18 of the bug journal, which is about `count()` being fixed
        and its two brothers being left. This is the third brother, found by adding a tenth knob and
        noticing that one path did not refuse it.

        What it honours is what a COUNT honours, for the same reasons: order, limit and offset do not
        change whether a row exists, and the includes are resolved afterwards by the session.
        """
        self._guard_unsupported(
            "A SELECT EXISTS",
            _HONOURED_BY_COUNT,
            "Ask it of the projection with select(...) if the question is about groups.",
        )
        where = self._combined_where()
        return emit_exists(
            self._table, dialect, where=where, plan=self._plan(where, dialect)
        )

    def to_update_sql(
        self, dialect: SnakeDialect, values: Mapping[str, object]
    ) -> tuple[str, tuple[object, ...]]:
        """Compiles a BULK UPDATE with the query's WHERE (EXECUTION lives in the session).

        The values arrive already as SQL column names. If the WHERE navigates a relationship it is
        rewritten to `<pk> IN (subquery)` (no `UPDATE ... FROM`). The guards are put in place by
        `_guard_bulk_write`.
        """
        self._guard_bulk_write("UPDATE")
        where = self._combined_where()
        deep_plan = self._deep_write_plan(where, dialect)
        if deep_plan is not None:
            assert where is not None  # a deep plan exists => a WHERE exists
            return emit_update_pk_in_subquery(
                self._table, dialect, values, deep_plan, where
            )
        return emit_update(self._table, dialect, values, where=where)

    def to_delete_sql(self, dialect: SnakeDialect) -> tuple[str, tuple[object, ...]]:
        """Compiles a BULK DELETE with the query's WHERE (EXECUTION lives in the session).

        Like `to_update_sql`: a WHERE that navigates is rewritten to `<pk> IN (subquery)` (no `DELETE ... FROM`).
        """
        self._guard_bulk_write("DELETE")
        where = self._combined_where()
        deep_plan = self._deep_write_plan(where, dialect)
        if deep_plan is not None:
            assert where is not None  # a deep plan exists => a WHERE exists
            return emit_delete_pk_in_subquery(self._table, dialect, deep_plan, where)
        return emit_delete(self._table, dialect, where=where)

    def _deep_write_plan(
        self, where: SnakeCondition | None, dialect: SnakeDialect
    ) -> JoinPlan | None:
        """JoinPlan for the subquery of a deep bulk write, or None if the WHERE is flat.

        It returns the plan only when some path navigates a relationship.
        """
        if where is None:
            return None
        paths = condition_paths(where)
        if not any(len(path) > 1 for path in paths):
            return None
        return JoinPlan(self._table, paths, dialect, self._registry)

    def _guard_bulk_write(self, verb: str) -> None:
        """Guards the bulk write: WHERE only, with a filter, and not over a view.

        - It only uses the filter: limit/offset/order_by/group_by/having/include are rejected (better
          an error than ignoring them in silence).
        - With no filter it would hit the WHOLE table: an explicit WHERE is demanded.
        - A WHERE that navigates IS fine (it is rewritten to `<pk> IN (subquery)`).
        - Over a VIEW there is no writing (a runtime reinforcement).
        """
        if self._table.is_view:
            raise SnakeUnsupportedFeature(
                f"'{self._table.name}' is a READ-ONLY view: it does not accept a bulk {verb}."
            )
        # DERIVED from `__slots__`, not listed by hand: a knob added to this class is guarded the
        # day it appears rather than the day someone remembers. The hand-written chain named six of
        # the ten and dropped four in SILENCE — `distinct()`, `for_update()`, `only()`/`defer()` and
        # the `_prefetches` half of `include()`. A `delete_where(q.distinct())` emitted a plain
        # DELETE and answered a different question.
        #
        # Compared against a PRISTINE query rather than by truthiness, and that is not style:
        # `limit(0)`/`offset(0)` are legal and FALSY, so `getattr(self, slot)` would read `limit(0)`
        # as "no limit set" and emit a DELETE with no limit at all — destroying every matching row
        # for a caller who asked for at most zero.
        pristine = type(self)(self._model)
        carried = sorted(
            slot
            for slot in self.__slots__
            if slot not in _NOT_A_KNOB
            and getattr(self, slot) != getattr(pristine, slot)
        )
        if carried:
            dropped = ", ".join(
                _KNOB_SPELLING.get(slot, f"{slot.lstrip('_')}()") for slot in carried
            )
            raise SnakeUnsupportedFeature(
                f"a bulk {verb} only uses the filter (WHERE), and it does not emit {dropped}. "
                f"Dropping what you asked for would answer a different question without saying so: "
                f"select the rows first if you need those, then write by primary key."
            )
        if self._combined_where() is None:
            raise SnakeUnsupportedFeature(
                f"a {verb} without a WHERE would affect the WHOLE table; if that is what you want, "
                f"pass it an explicit filter with .filter(...)."
            )

    def to_project_sql(
        self,
        dialect: SnakeDialect,
        columns: Sequence[SnakeValue[Any]],
        explicit_joins: Sequence[tuple[tuple[str, ...], bool]] = (),
    ) -> tuple[str, tuple[object, ...]]:
        """Compiles a `SELECT <columns>` (projection) with filters, GROUP BY/HAVING and their JOINs.

        The paths of columns, WHERE, GROUP BY and HAVING all go into the `JoinPlan` (that is how a
        `group_by(Truck.maker.name)` generates its JOIN); `paths()` of a `COUNT(*)` is empty.
        `explicit_joins` are the `.join()`s onto collections: if there are any, the plan is ALWAYS
        built (the JOIN already demands aliases).
        """
        where = self._combined_where()
        having = self._combined_having()
        paths = condition_paths(where) if where is not None else []
        paths = [
            *paths,
            *(p for column in columns for p in column.paths()),
            *(p for key in self._order for p in key.expr.paths()),
            *(p for column in self._group_by for p in column.paths()),
            *(condition_paths(having) if having is not None else []),
        ]
        plan = None
        if explicit_joins or any(len(path) > 1 for path in paths):
            plan = JoinPlan(
                self._table,
                paths,
                dialect,
                self._registry,
                explicit_joins=explicit_joins,
            )
        return emit_project(
            self._table,
            dialect,
            columns,
            where=where,
            plan=plan,
            group_by=self._group_by,
            having=having,
            order_by=self._order,
            limit=self._limit,
            offset=self._offset,
            distinct=self._distinct,
        )

    def to_annotate_sql(
        self, dialect: SnakeDialect, aggregates: Sequence[SnakeValue[Any]]
    ) -> tuple[str, tuple[object, ...]]:
        """Compiles the SELECT of `annotate()`: base model columns + aggregates, grouping by the PK.

        The remaining columns depend functionally on the PK (Postgres accepts that). An explicit
        `group_by` is an error: to group by something else there is `select()` + `group_by()`.
        """
        if self._group_by:
            raise SnakeEmitError(
                "annotate() groups by the PK of the base model and does not accept an explicit "
                "group_by(). To group by another column use select() + group_by()."
            )
        base_columns: tuple[SnakeValue[Any], ...] = tuple(
            SnakeExpr(path=(column.name,)) for column in self._table.columns
        )
        group_by: tuple[SnakeValue[Any], ...] = tuple(
            SnakeExpr(path=(column.name,)) for column in self._table.primary_key.columns
        )
        columns: tuple[SnakeValue[Any], ...] = (*base_columns, *aggregates)
        where = self._combined_where()
        paths = condition_paths(where) if where is not None else []
        paths = [
            *paths,
            *(p for column in columns for p in column.paths()),
            *(p for key in self._order for p in key.expr.paths()),
        ]
        plan = None
        if any(len(path) > 1 for path in paths):
            plan = JoinPlan(self._table, paths, dialect, self._registry)
        return emit_project(
            self._table,
            dialect,
            columns,
            where=where,
            plan=plan,
            group_by=group_by,
            order_by=self._order,
            limit=self._limit,
            offset=self._offset,
            functional_dependency=True,
        )

    def _plan(
        self,
        where: SnakeCondition | None,
        dialect: SnakeDialect,
        include_order: bool = False,
    ) -> JoinPlan | None:
        """Builds the JoinPlan if some path is deep; None if everything belongs to the root table."""
        paths = condition_paths(where) if where is not None else []
        if include_order:
            paths = [*paths, *(p for key in self._order for p in key.expr.paths())]
        if any(len(path) > 1 for path in paths):
            return JoinPlan(self._table, paths, dialect, self._registry)
        return None

    def _clone(self) -> SnakeQuery[T]:
        """Copies the current state into a new query (the basis of the immutability)."""
        clone = SnakeQuery(self._model)
        clone._filters = self._filters
        clone._order = self._order
        clone._limit = self._limit
        clone._offset = self._offset
        clone._includes = self._includes
        clone._prefetches = self._prefetches
        clone._group_by = self._group_by
        clone._having = self._having
        clone._distinct = self._distinct
        clone._lock = self._lock
        clone._columns = self._columns
        return clone

    def _combined_where(self) -> SnakeCondition | None:
        """Combines every filter into a single condition (a flat AND), or None if there are none."""
        return self._combine(self._filters)

    def _combined_having(self) -> SnakeCondition | None:
        """Combines the HAVING conditions into a single one (a flat AND), or None if there are none."""
        return self._combine(self._having)

    @staticmethod
    def _combine(conditions: tuple[SnakeCondition, ...]) -> SnakeCondition | None:
        """Reduces a tuple of conditions to a flat AND (or the only one, or None)."""
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return SnakeAnd(parts=conditions)
