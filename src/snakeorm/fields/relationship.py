"""The SnakeToOne descriptor and its field specifier snake_to_one (to-one relation)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, Generic, Literal, Never, TypeVar, overload

from snakeorm.core.exceptions import (
    SnakeModelError,
    SnakeRegistryError,
    SnakeRelationshipNotLoaded,
    SnakeUnknownColumn,
    SnakeUnknownRelationship,
    SnakeUnlinkedRelationship,
    SnakeUnsupportedFeature,
)
from snakeorm.expressions import (
    SnakeAggFunc,
    SnakeAnd,
    SnakeCondition,
    SnakeExists,
    SnakeExistsJoin,
    SnakeExpr,
    SnakeSubqueryAggregate,
    condition_paths,
)
from snakeorm.fields.column import SnakeColumn
from snakeorm.metadata import (
    SnakeFkAction,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.registry import SnakeRegistry, registry_of

M = TypeVar("M")
N = TypeVar("N")


def relationship_storage_key(name: str) -> str:
    """Per-instance key where a loaded relation lives. Same computation as `__set_name__`."""
    return f"__snake_{name}"


def attach_relationship(instance: object, name: str, value: object) -> None:
    """Hang an ALREADY LOADED relation off the instance. The session loader uses this.

    It writes the internal key directly instead of going through the descriptor, because the
    `__set__` of relations now RAISES: assigning and loading are different things and each one has
    its own door. Assigning is a user error (the FK would not move); loading is the ORM placing
    what it has just brought back from the database, which is exactly the opposite.
    """
    object.__setattr__(instance, relationship_storage_key(name), value)


def _registry_of(model: type) -> SnakeRegistry:
    """Alias of `registry.registry_of`, kept so this module's own call sites read locally.

    The answer belongs to the registry and now lives there. It used to live here, private, and be
    imported across package boundaries by `query/` and `fields/check.py` — which is what a helper
    looks like just before it becomes public by accident.
    """
    return registry_of(model)


class SnakePathProxy:
    """Runtime navigation over the linked graph (the counterpart of class access, which the
    checker sees as `type[M]`).

    By attribute: a column of the target → `SnakeExpr` carrying the accumulated path; a relation →
    a new `SnakePathProxy` over its target. The `registry` is mandatory on purpose, so that no
    place falls back to the global one silently.
    """

    def __init__(
        self, table: SnakeTableInfo, path: tuple[str, ...], reg: SnakeRegistry
    ) -> None:
        self._table = table
        self._path = path
        self._registry = reg

    def __getattr__(self, name: str) -> Any:
        # `name` is the Python attribute; the path carries the SQL name (the one emitted). With
        # `snake_column(name=...)` they differ.
        column = self._table.get_column_by_attr(name)
        if column is not None:
            return SnakeExpr(
                path=(*self._path, column.name), python_type=column.python_type
            )
        for relationship in self._table.relationships:
            if relationship.name == name:
                target = self._registry.resolve_relationship(relationship)[0]
                if target is None:
                    raise AttributeError(
                        f"Target '{relationship.target}' of '{name}' is not registered."
                    )
                return SnakePathProxy(target, (*self._path, name), self._registry)
        raise AttributeError(
            f"'{self._table.name}' has no column or relation called '{name}'."
        )


def path_of(proxy: object) -> tuple[str, ...]:
    """The navigation path a to-one proxy has accumulated (`Post.author.country` -> two hops).

    A FUNCTION and not a property, and that is not style. `SnakePathProxy.__getattr__` IS the target
    model's namespace: every public attribute the class grows shadows a column of that name, so a
    model with a `path` column would lose it to the ORM's own plumbing without an error anywhere.
    Asking from outside costs one import and cannot collide with anybody's schema.

    It takes `object` and narrows at runtime, because the two halves of a descriptor disagree on
    purpose: class access is TYPED `type[M]` and IS a `SnakePathProxy`, so a signature demanding the
    proxy would reject `path_of(Post.author)` — every real call site. The isinstance check is the
    contract, and it is what the caller gets told about.
    """
    if not isinstance(proxy, SnakePathProxy):
        raise TypeError(
            f"path_of() takes a SnakePathProxy (class access on a to-one, like `Post.author`), "
            f"not {type(proxy).__name__}."
        )
    return proxy._path


class SnakeToOne(Generic[M]):
    """To-one relation descriptor.

    CLASS access (`House.owner`) → `type[M]` (for navigation/queries).
    INSTANCE access (`house.owner`) → the related object (`M`).
    It also holds the local FK columns and the referential actions for the compiler.
    """

    def __init__(
        self,
        *source_columns: SnakeColumn[Any],
        on_delete: SnakeFkAction = SnakeFkAction.NO_ACTION,
        on_update: SnakeFkAction = SnakeFkAction.NO_ACTION,
    ) -> None:
        self._local_columns = source_columns
        self.on_delete = on_delete
        self.on_update = on_update
        self._attr_name = ""
        self._storage_key = ""
        self._target_table: SnakeTableInfo | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        """Capture the property name and compute the per-instance storage key."""
        self._attr_name = name
        self._storage_key = f"__snake_{name}"

    def local_column_names(self) -> tuple[str, ...]:
        """SQL names of the local FK columns (resolved at compile time)."""
        return tuple(column.column_name for column in self._local_columns)

    @overload
    def __get__(self: SnakeToOne[N | None], instance: None, owner: Any) -> type[N]: ...
    @overload
    def __get__(self: SnakeToOne[M], instance: None, owner: Any) -> type[M]: ...
    @overload
    def __get__(self, instance: object, owner: Any) -> M: ...
    def __get__(self, instance: object | None, owner: Any) -> Any:
        """Class access gives the target to navigate from; instance access gives the loaded value.

        The FIRST overload is what lets a NULLABLE relation be navigated. Without it, class access
        on `SnakeToOne[Author | None]` is `type[Author | None]`, which distributes to
        `type[Author] | type[None]`; `type[None]` has no columns, so `Post.editor.username` is an
        error in both checkers with a `SnakeExpr[str] | Any` leaking out behind it. Narrowing `self`
        to `SnakeToOne[N | None]` binds `N` to the model alone and hands back `type[N]`.

        Dropping the `| None` is correct HERE and only here: class access does not read a value, it
        names the far side of a LEFT JOIN, a table that always exists whether or not any given row
        has a partner. The third overload deliberately does NOT narrow `self`, so instance access
        keeps `M` whole and `post.editor` stays `Author | None` — the row really may have no editor.

        THE ORDER IS LOAD-BEARING AND FAILS SILENTLY. Overload resolution takes the first arm that
        matches, and the narrow arm matches a subset of the generic one; declared second it never
        wins and this whole mechanism quietly reverts, with no checker, linter or test of the
        signature itself complaining. `src/test/typing/test_the_optional_overload_comes_first.py`
        is what notices.

        THE SIGNATURE HAS ONE HOLE, AND THE LINKER IS WHAT CLOSES IT. Given a union of two or more
        models plus `| None` — `SnakeToOne[Card | Transfer | None]` — the two checkers disagree:
        mypy infers `type[Never]` and pyright infers `type[Card] | type[Transfer]`. `type[Never]` is
        not an error but a TYPE, so mypy would pass in green over an expression that means nothing
        and the project's two gates would answer differently about the same line. That case is made
        UNREACHABLE rather than patched here: `_guard_one_target_model` in `linker/linker.py`
        refuses a relationship whose target is a union of models. A hierarchy is pointed at through
        its base class instead (`SnakeToOne[Payment]`), which is how this ORM expresses
        polymorphism anyway.
        """
        if instance is None:
            if self._target_table is None:
                raise SnakeUnlinkedRelationship(
                    f"Relation '{self._attr_name}' is not linked; call snake_link() first."
                )
            return SnakePathProxy(
                self._target_table, (self._attr_name,), _registry_of(owner)
            )
        try:
            return getattr(instance, self._storage_key)
        except AttributeError:
            raise SnakeRelationshipNotLoaded(
                f"Relation '{self._attr_name}' was not loaded. "
                f"Use .include({owner.__name__}.{self._attr_name}) in the query."
            ) from None

    def __set__(self, instance: object, value: Never) -> None:
        """FORBIDDEN to assign a relation. The type rejects it; this covers whoever skips the type.

        `value: Never` is what makes it a CHECKER error: no value is assignable to `Never`, so mypy
        and pyright reject the line. The method still exists at runtime on purpose: without
        `__set__` the descriptor would stop being a data descriptor and an `instance.__dict__`
        would shadow it.
        """
        raise SnakeModelError(
            f"'{self._attr_name}' is a relation: it is not assigned. Saving the object would NOT move "
            f"the foreign key, so the row would keep pointing where it was and the change would be "
            f"lost without a single warning. To POINT at another row write its FK column "
            f"({', '.join(self.local_column_names()) or 'the local FK'}); to READ the relation "
            f"load it with .include(...) in the query."
        )


def snake_to_one(
    *source_columns: SnakeColumn[Any],
    on_delete: SnakeFkAction = SnakeFkAction.NO_ACTION,
    on_update: SnakeFkAction = SnakeFkAction.NO_ACTION,
    init: Literal[False] = False,
) -> Any:
    """Declare a to-one relation (FK). It references the model's local FK columns.

    The target comes from the `SnakeToOne[Target]` annotation; the mapping to the PK is resolved
    in the linker. It is excluded from the constructor (it gets loaded with `.include(...)`): the
    `init: Literal[False]` is the typing signal — without it the checker read it as "a field with
    a default" and blessed a line that the runtime rejects with `TypeError`.
    """
    return SnakeToOne(*source_columns, on_delete=on_delete, on_update=on_update)


class SnakeCollection(Generic[M]):
    """COLLECTION view: what CLASS access to a to-many returns (`Nation.makers`).

    A to-many changes the cardinality, so it does NOT expose the child's columns (implicit
    navigation): only collection operations — `.any(...)` (a correlated EXISTS) and the scalar
    aggregates `.count()/.sum_()/.avg()/.min_()/.max_()`. That way `Nation.makers.name` is a TYPE
    error, not unrunnable SQL. Generic in `M` so the child's type travels into the condition.
    """

    __slots__ = (
        "_parent_table",
        "_child_table",
        "_relationship",
        "_attr_name",
        "_registry",
    )

    def __init__(
        self,
        parent_table: SnakeTableInfo,
        child_table: SnakeTableInfo,
        relationship: SnakeRelationshipInfo,
        attr_name: str,
        reg: SnakeRegistry,
    ) -> None:
        self._parent_table = parent_table
        self._child_table = child_table
        self._relationship = relationship
        self._attr_name = attr_name
        self._registry = reg

    @property
    def path(self) -> tuple[str, ...]:
        """One-hop path for `.include(...)` (select-in resolves it as a to-many)."""
        return (self._attr_name,)

    def any(self, condition: SnakeCondition | None = None) -> SnakeExists:
        """Correlated EXISTS: does the parent have at least one child [matching `condition`]?

        The condition is over the CHILD MODEL (relative paths, re-anchored at emission time). It
        can navigate the child's to-one relations (`Maker.nation.name`): those JOINs are resolved
        here and emitted INSIDE the EXISTS with their own alias space. See
        `_resolve_exists_joins`.
        """
        joins: tuple[SnakeExistsJoin, ...] = ()
        if condition is not None:
            joins = _resolve_exists_joins(
                self._child_table, condition_paths(condition), self._registry
            )
        return SnakeExists(
            child_schema=self._child_table.schema,
            child_name=self._child_table.name,
            pairs=self._relationship.foreign_key.pairs,
            condition=condition,
            joins=joins,
        )

    def count(self) -> SnakeSubqueryAggregate[int]:
        """Scalar `COUNT(*)` subquery over the correlated children. Comparable (`.count() > 3`).

        No `| None`: a parent without children counts 0, not NULL. The only aggregate that gets
        away with it; the rest carry `| None` because they aggregate zero rows. See `sum_`.
        """
        return self._aggregate(SnakeAggFunc.COUNT, None)

    def sum_(self, column: SnakeExpr[N]) -> SnakeSubqueryAggregate[N | None]:
        """`SUM(col)` over the correlated children. The child column's type, plus `None`.

        The `None` is not theoretical: a parent without children aggregates zero rows, and `SUM`
        of zero rows is NULL.
        """
        return self._aggregate(SnakeAggFunc.SUM, column)

    def avg(self, column: SnakeExpr[Any]) -> SnakeSubqueryAggregate[float | None]:
        """`AVG(col)` over the correlated children. The average is real (`float`), or NULL with no children."""
        return self._aggregate(SnakeAggFunc.AVG, column)

    def min_(self, column: SnakeExpr[N]) -> SnakeSubqueryAggregate[N | None]:
        """`MIN(col)` over the correlated children. The child column's type, or NULL with no children."""
        return self._aggregate(SnakeAggFunc.MIN, column)

    def max_(self, column: SnakeExpr[N]) -> SnakeSubqueryAggregate[N | None]:
        """`MAX(col)` over the correlated children. The child column's type, or NULL with no children."""
        return self._aggregate(SnakeAggFunc.MAX, column)

    def _guard_child_column(self, path: tuple[str, ...]) -> None:
        """Demand that `path` be a DIRECT column of the child. Fails loudly if it is not.

        At runtime and not in the type: `SnakeExpr[T]` carries the type of the VALUE, not the
        owning model, so `Maker.id` and `Truck.id` are indistinguishable to the checker; putting
        the owner in would kill deep navigation and the `&`. Without this,
        `Nation.makers.sum_(Truck.id)` emitted valid SQL but the answer to another question (a
        multi-step path demands a JOIN that has not been built).
        """
        _guard_direct_child_column(
            self._child_table,
            path,
            "A collection's aggregates only accept direct columns of the child model.",
        )

    def _aggregate(
        self, func: SnakeAggFunc, column: SnakeExpr[Any] | None
    ) -> SnakeSubqueryAggregate[Any]:
        """Build the scalar correlated-aggregation subquery over the child's FK.

        The argument column (or `None` for COUNT(*)) belongs to the CHILD MODEL: relative paths
        re-anchored at emission time. It is validated to be a DIRECT column of the child: see
        `_guard_child_column`.
        """
        if column is not None:
            for path in column.paths():
                self._guard_child_column(path)
        return SnakeSubqueryAggregate(
            func=func,
            arg=column,
            child_schema=self._child_table.schema,
            child_name=self._child_table.name,
            pairs=self._relationship.foreign_key.pairs,
        )


class SnakeToMany(Generic[M]):
    """To-many relation descriptor: the INVERSE of an FK on the child.

    CLASS access (`Country.cities`) → `SnakeCollection[M]`; INSTANCE access → `list[M]`.
    It holds the NAME of the child FK to reverse (`fk_name`); the linker resolves the child from
    the `SnakeToMany[Child]` annotation and the FK columns from that relation.
    """

    def __init__(
        self,
        fk_name: str,
        *,
        through: str | type | None = None,
        via: str | None = None,
        to: str | None = None,
    ) -> None:
        self.fk_name = fk_name
        # The BRIDGE of a many-to-many. It reuses this descriptor because the typed behaviour is
        # identical; what changes is only HOW the rows get loaded.
        self.through = through
        self.via = via
        self.to = to
        self._attr_name = ""
        self._storage_key = ""
        self._target_table: SnakeTableInfo | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        """Capture the property name and compute the per-instance storage key."""
        self._attr_name = name
        self._storage_key = f"__snake_{name}"

    @overload
    def __get__(self, instance: None, owner: Any) -> SnakeCollection[M]: ...
    @overload
    def __get__(self, instance: object, owner: Any) -> list[M]: ...
    def __get__(self, instance: object | None, owner: Any) -> Any:
        if instance is None:
            return self._collection(owner)
        try:
            return getattr(instance, self._storage_key)
        except AttributeError:
            raise SnakeRelationshipNotLoaded(
                f"Relation '{self._attr_name}' was not loaded. "
                f"Use .include({owner.__name__}.{self._attr_name}) in the query."
            ) from None

    def _collection(self, owner: type) -> SnakeCollection[M]:
        """Build the SnakeCollection of class access, resolving the parent's relation."""
        if self._target_table is None:
            raise SnakeUnlinkedRelationship(
                f"Relation '{self._attr_name}' is not linked; call snake_link() first."
            )
        reg = _registry_of(owner)
        parent_table = reg.table_of(owner)
        relationship = _find_relationship(parent_table, self._attr_name)
        if parent_table is None or relationship is None:
            raise SnakeUnlinkedRelationship(
                f"Relation '{self._attr_name}' is not linked; call snake_link() first."
            )
        return SnakeCollection(
            parent_table=parent_table,
            child_table=self._target_table,
            relationship=relationship,
            attr_name=self._attr_name,
            reg=reg,
        )

    def __set__(self, instance: object, value: Never) -> None:
        """FORBIDDEN to assign a collection. Same criterion as the to-one (see
        `SnakeToOne.__set__`).

        Here it is even clearer: the children hold THEIR own FK, so hanging a list off the parent
        writes absolutely nothing to the database.
        """
        raise SnakeModelError(
            f"'{self._attr_name}' is a collection: it is not assigned. The children point at the parent "
            f"through THEIR own foreign key, so hanging a list here would write NOTHING to the "
            f"database. To add a child, give it the parent's FK and save it (session.add); to READ "
            f"the collection load it with .include(...) in the query."
        )


def _resolve_exists_joins(
    child_table: SnakeTableInfo,
    paths: Iterable[tuple[str, ...]],
    reg: SnakeRegistry,
) -> tuple[SnakeExistsJoin, ...]:
    """Validate the paths of an `.any()` condition and build the navigation JOINs.

    Last step = column; intermediate ones = to-one relations of the model in play, navigated inside
    the EXISTS. An intermediate to-many step would change the cardinality →
    `SnakeUnsupportedFeature` (nest it with another `.any()`). It returns the JOINs without
    duplicating prefixes, ordered from parent to child, ready for emission to assign aliases in its
    own space.
    """
    joins: dict[tuple[str, ...], SnakeExistsJoin] = {}
    for path in paths:
        _collect_navigation(child_table, path, joins, reg)
    return tuple(
        joins[prefix]
        for prefix in sorted(joins, key=lambda prefix: (len(prefix), prefix))
    )


def _collect_navigation(
    child_table: SnakeTableInfo,
    path: tuple[str, ...],
    joins: dict[tuple[str, ...], SnakeExistsJoin],
    reg: SnakeRegistry,
) -> None:
    """Walk ONE path validating it against the graph and accumulate its navigation JOINs in `joins`."""
    if len(path) == 1:
        if child_table.get_column(path[0]) is None:
            raise SnakeUnknownColumn(
                f"'{path[0]}' is not a column of the child model '{child_table.name}' nor a navigable "
                f"relation. The .any() of a collection filters by columns of the child or "
                f"navigates its to-one relations."
            )
        return
    table = child_table
    for depth, step in enumerate(path[:-1]):
        relationship = _find_relationship(table, step)
        if relationship is None:
            raise SnakeUnknownColumn(
                f"'{step}' is neither a column nor a relation of '{table.name}': there is no way to "
                f"navigate the condition of the .any() ({'.'.join(path)})."
            )
        if relationship.kind is not SnakeRelationshipKind.TO_ONE:
            raise SnakeUnsupportedFeature(
                f"'{step}' is a to-many relation: navigating it inside an EXISTS would change the "
                f"cardinality. Nest the existence with another explicit .any()."
            )
        target = reg.resolve_relationship(relationship)[0]
        if target is None:
            raise SnakeRegistryError(
                f"Target '{relationship.target}' of '{step}' is not registered."
            )
        prefix = path[: depth + 1]
        if prefix not in joins:
            joins[prefix] = SnakeExistsJoin(
                prefix=prefix,
                schema=target.schema,
                name=target.name,
                pairs=relationship.foreign_key.pairs,
            )
        table = target
    if table.get_column(path[-1]) is None:
        raise SnakeUnknownColumn(
            f"'{path[-1]}' is not a column of '{table.name}' (target of the navigation "
            f"{'.'.join(path)})."
        )


def _guard_direct_child_column(
    child_table: SnakeTableInfo, path: tuple[str, ...], reason: str
) -> None:
    """Demand that `path` be a DIRECT column of `child_table`; fail loudly if it is not.

    The single point of truth for the "direct column of the child" criterion (shared by the
    aggregates, `.any()` and the `.filter()` of a prefetch). A multi-step path is navigation (a
    JOIN that has not been built); both → `SnakeUnknownColumn`. `reason` gives the context of who
    did the validating.
    """
    if len(path) != 1 or child_table.get_column(path[0]) is None:
        name = ".".join(path)
        raise SnakeUnknownColumn(
            f"'{name}' is not a direct column of '{child_table.name}'. {reason}"
        )


def _find_relationship(
    table: SnakeTableInfo | None, name: str
) -> SnakeRelationshipInfo | None:
    """Look up the relation by name in the linked table, or None if it is not there yet."""
    if table is None:
        return None
    for relationship in table.relationships:
        if relationship.name == name:
            return relationship
    return None


def snake_to_many_through(
    *, through: str | type, via: str, to: str, init: Literal[False] = False
) -> Any:
    """Declare a MANY-TO-MANY that crosses a DECLARED bridge table.

        tags: SnakeToMany["Tag"] = snake_to_many_through(
            through="PostTag", via="post", to="tag"
        )

    `through` is the BRIDGE model (a normal one), `via` the bridge relation pointing at THIS model
    and `to` the one pointing at the target. The bridge is a real model (not an implicit
    Django-style m2m): adding a column to it is just one more field. It is NAVIGATION, not writing:
    linking means inserting the bridge row with `add()`.

    `through` takes a NAME or the CLASS. The name is the usual way, because the bridge is normally
    declared after the model that crosses it and there is no class to hand over yet. The class is
    the way out when the name is ambiguous: two apps can each declare a `Tagging`, and a name is
    resolved through an index kept by whichever registered LAST — the same index that produced bug
    #14. With the class there is nothing to look up, so nothing to get wrong. Handing it over means
    declaring the bridge first, with string annotations pointing back.
    """
    return SnakeToMany(via, through=through, via=via, to=to)


def snake_to_many(fk_name: str, *, init: Literal[False] = False) -> Any:
    """Declare a to-many relation: the inverse of the child's FK relation `fk_name`.

    The child comes out of the `SnakeToMany[Child]` annotation. It is EXCLUDED from the
    constructor (you do not build it, you load it with `.include(...)`): the `init:
    Literal[False]` is the signal that mypy and pyright read. It has to be a string because the
    child is usually defined AFTER the parent.
    """
    return SnakeToMany(fk_name)


@dataclass(frozen=True, slots=True)
class SnakePrefetchHop:
    """A normalised hop of a prefetch chain (already resolved against the metadata graph).

    `SnakePrefetch` produces it at construction time (with the relations already linked). The
    session consumes it level by level: to_many with select-in (a list per parent), to_one with an
    extra query (an object per parent). It carries the parent's table and the child's model+table
    (to instantiate it).
    """

    name: str
    kind: SnakeRelationshipKind
    """The same cardinality (and the SAME type) as `SnakeRelationshipInfo`, not a copy of the enum."""
    parent_table: SnakeTableInfo
    child_model: type[object]
    child_table: SnakeTableInfo
    relationship: SnakeRelationshipInfo
    # OPTIONAL filter for the level: it narrows which CHILDREN get loaded (direct columns). It is
    # ADDED with AND to the `WHERE fk IN (...)` of the select-in; a parent with no matching children
    # gets [] but STILL comes back. Different from `query.filter()`, which would drop the parent.
    child_filter: SnakeCondition | None = None


class SnakePrefetch(Generic[M]):
    """EXPLICIT chain of nested (eager) loading that starts at a to-many (`Nation.makers`).

    A collection does not expose the child's relations, so the chain is not navigated: it is
    declared with `SnakePrefetch(Nation.makers).then(Maker.trucks)`. Generic in the model of the
    LAST hop so that `.then(...)` only accepts relations of THAT child. The session resolves it
    with ONE query per LEVEL (never N+1).
    """

    __slots__ = ("_hops",)

    def __init__(self, root: SnakeCollection[M]) -> None:
        # The root is ALWAYS a to-many: that is what needs nesting. The to-ones already get loaded
        # with a LEFT JOIN via `.include(User.car)`.
        self._hops: tuple[SnakePrefetchHop, ...] = (_hop_from_collection(root),)

    @overload
    def then(self, relation: SnakeCollection[N]) -> SnakePrefetch[N]: ...
    @overload
    def then(self, relation: type[N]) -> SnakePrefetch[N]: ...
    def then(self, relation: SnakeCollection[Any] | type[Any]) -> SnakePrefetch[Any]:
        """Chain one more hop onto the current child: to-many (`SnakeCollection`) or to-one
        (`type`).

        It returns a NEW `SnakePrefetch` (immutable). A column (`SnakeExpr`) matches no overload:
        `.then(Truck.model)` does not compile.
        """
        current = self._hops[-1].child_table
        extended: SnakePrefetch[Any] = SnakePrefetch.__new__(SnakePrefetch)
        extended._hops = (*self._hops, *_hops_for_then(current, relation))
        return extended

    def filter(self, condition: SnakeCondition) -> SnakePrefetch[M]:
        """Narrow WHICH CHILDREN get loaded at the CURRENT level (the last hop), WITHOUT dropping
        parents.

        Different from `query.filter()` (which discards parents): it only narrows the select-in of
        the level, a parent with no matching children gets [] but STILL comes back. It accumulates
        with AND and returns a NEW `SnakePrefetch` (immutable) of the SAME type. The condition must
        be over DIRECT columns of the model at THAT level; navigating or naming another column →
        `SnakeUnknownColumn`.
        """
        last = self._hops[-1]
        for path in condition_paths(condition):
            _guard_direct_child_column(
                last.child_table,
                path,
                "A prefetch's .filter() only narrows by columns of that level's model.",
            )
        merged = (
            condition
            if last.child_filter is None
            else SnakeAnd(parts=(last.child_filter, condition))
        )
        filtered: SnakePrefetch[Any] = SnakePrefetch.__new__(SnakePrefetch)
        filtered._hops = (*self._hops[:-1], replace(last, child_filter=merged))
        return filtered

    def hops(self) -> tuple[SnakePrefetchHop, ...]:
        """The normalised hops in order (root first). The session walks them, one per level."""
        return self._hops


def _hop_from_collection(collection: SnakeCollection[Any]) -> SnakePrefetchHop:
    """Normalise class access to a to-many (`SnakeCollection`) into a prefetch hop."""
    relationship = collection._relationship  # noqa: SLF001 - same module, internal contract
    child_table = collection._child_table  # noqa: SLF001 - same module, internal contract
    child_model = collection._registry.resolve_relationship(relationship)[1]  # noqa: SLF001
    if child_model is None:
        raise SnakeRegistryError(
            f"Target '{relationship.target}' of '{relationship.name}' is not registered."
        )
    return SnakePrefetchHop(
        # The relation dictates the KIND, it is not hardcoded: an m2m (to-many-through) routes to
        # another planner, and assuming TO_MANY sent it to the wrong one (a direct FK that does not
        # exist → error).
        name=collection._attr_name,  # noqa: SLF001 - same module, internal contract
        kind=relationship.kind,
        parent_table=collection._parent_table,  # noqa: SLF001 - same module, internal contract
        child_model=child_model,
        child_table=child_table,
        relationship=relationship,
    )


def _hops_for_then(
    parent_table: SnakeTableInfo, relation: SnakeCollection[Any] | type[Any]
) -> tuple[SnakePrefetchHop, ...]:
    """Resolve the argument of `.then(...)` into one or more hops against the current child.

    A `SnakeCollection` is a single to-many hop. A to-one arrives at runtime as a `SnakePathProxy`
    (even though the checker sees it as `type[M]`): its path gets expanded into to-one hops. A
    to-many hidden inside the path is rejected: to nest a to-many you use another explicit
    `.then(...)`.
    """
    if isinstance(relation, SnakeCollection):
        return (_hop_from_collection(relation),)
    if not isinstance(relation, SnakePathProxy):
        # Anything that is not relation navigation. The checker already rejects it; the guard gives
        # a clear message instead of an `AttributeError` from the guts of the prefetch.
        raise SnakeUnknownRelationship(
            f"`.then()` expects a RELATION navigated from the class (e.g. `.then(Brand.cars)`), "
            f"not {type(relation).__name__!r}. A relation name given as text is no good here."
        )
    proxy = relation
    hops: list[SnakePrefetchHop] = []
    table = parent_table
    for step in proxy._path:  # noqa: SLF001 - same module, internal contract
        relationship = _relationship_of(table, step)
        target_table, target_model = proxy._registry.resolve_relationship(relationship)  # noqa: SLF001
        if target_table is None or target_model is None:
            raise SnakeRegistryError(
                f"Target '{relationship.target}' of '{step}' is not registered."
            )
        if relationship.kind is not SnakeRelationshipKind.TO_ONE:
            raise SnakeUnsupportedFeature(
                f"'{step}' is to-many: chain it with another explicit .then(...), do not navigate it."
            )
        hops.append(
            SnakePrefetchHop(
                name=step,
                kind=SnakeRelationshipKind.TO_ONE,
                parent_table=table,
                child_model=target_model,
                child_table=target_table,
                relationship=relationship,
            )
        )
        table = target_table
    return tuple(hops)


def _relationship_of(table: SnakeTableInfo, name: str) -> SnakeRelationshipInfo:
    """Look up a relation by name in the table; fails clearly if absent (a `.then` step)."""
    for relationship in table.relationships:
        if relationship.name == name:
            return relationship
    raise SnakeUnknownRelationship(f"'{table.name}' has no relation called '{name}'.")
