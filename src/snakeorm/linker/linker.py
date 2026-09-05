"""The Linker (Phase 2): resolves the relationships once every model is in place.

Register everything -> link at the end. The target comes out of the annotation; the FK pairs map
local columns to the target's PK by position. Two passes: to-one (FK) and then to-many (the
inverses), which read the child's already-resolved FK. Idempotent.
"""

from __future__ import annotations

import dataclasses
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from snakeorm.core.exceptions import (
    SnakeModelDefinitionError,
    SnakeRegistryError,
    SnakeUnknownRelationship,
)
from snakeorm.fields import SnakeToMany, SnakeToOne
from snakeorm.helpers.annotations import unwrap_optional
from snakeorm.helpers.inheritance import collect_inherited
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
    SnakeThroughInfo,
)
from snakeorm.registry.by_module import resolve_in_module, type_checking_names
from snakeorm.registry import SnakeRegistry, registry


def _guard_same_database(
    model: type,
    attr: str,
    target_cls: type,
    source_table: SnakeTableInfo | None,
    target_table: SnakeTableInfo,
) -> None:
    """Forbids a relationship whose target lives in ANOTHER database.

    Neither an FK (a constraint does not cross databases) nor a JOIN (a SELECT lives inside a single
    one) is possible. It is cut off at link time (at startup) instead of letting the `ALTER TABLE`
    or a JOIN blow up in production.
    """
    if source_table is None or source_table.database == target_table.database:
        return
    raise SnakeModelDefinitionError(
        f"Relationship {model.__name__}.{attr} crosses databases: {model.__name__} lives in "
        f"'{source_table.database}' and {target_cls.__name__} in '{target_table.database}'. There is "
        f"neither a foreign key nor a JOIN possible across connections. Move one of the two, or "
        f"store the identifier as a plain column and resolve it yourself with two queries."
    )


def _union_members(annotation: Any) -> tuple[Any, ...] | None:
    """The members of a union annotation, or `None` when it is not a union.

    Recognises both spellings, `Union[X, Y]` and PEP 604's `X | Y`, for the same reason
    `unwrap_optional` does: a model file may use either.
    """
    if get_origin(annotation) in (Union, types.UnionType):
        return get_args(annotation)
    return None


def _name_of(annotation: Any) -> str:
    """A readable name for an annotation member, for error messages only.

    `getattr` and not `.__name__` because the thing being named is precisely what may NOT have one:
    formatting a `types.UnionType` with `.__name__` is the crash this guard replaced.
    """
    if annotation is type(None):
        return "None"
    return getattr(annotation, "__name__", str(annotation))


def _guard_one_target_model(model: type, attr: str, annotation: Any) -> None:
    """Forbids a to-one whose target is a union of MODELS (`SnakeToOne[Card | Transfer]`).

    A relationship resolves to ONE target table: it is a single foreign key and a single JOIN.
    A union names several, and there is no row shape that answers for all of them.

    This guard is also what makes the typing of `SnakeToOne.__get__` sound, and that dependency runs
    the other way from how it looks. The descriptor unwraps `| None` through an overload on the type
    of `self`, and that overload has a hole exactly here: with two models plus `| None`, mypy infers
    `type[Never]` — a type and not an error, so it goes green over a meaningless expression — while
    pyright infers the union of the two. Refusing the shape makes the hole unreachable. See
    `SnakeToOne.__get__`, whose docstring names this function.

    It must be asked BEFORE `unwrap_optional`, which returns the first non-`None` member: given
    `Card | Transfer | None` it hands back `Card` and drops `Transfer` without a word, so a guard
    placed after it would be looking at a union that had already been silently resolved.
    """
    members = _union_members(annotation)
    if members is None:
        return
    models = tuple(member for member in members if member is not type(None))
    if len(models) < 2:
        return
    names = " | ".join(_name_of(member) for member in models)
    raise SnakeRegistryError(
        f"Relationship {model.__name__}.{attr} points at a union of models ({names}). A "
        f"relationship points at one model: it is one foreign key and one JOIN, and a union names "
        f"several tables with no single row shape between them. If these are one hierarchy, point "
        f"at the BASE class they share instead of listing them — this ORM expresses polymorphism "
        f"with single-table inheritance, so the concrete class is resolved from the discriminator "
        f"when the rows are read."
    )


def _guard_a_collection_is_never_optional(
    model: type, attr: str, annotation: Any
) -> None:
    """Forbids `SnakeToMany[Child | None]`: a collection comes back EMPTY, never absent.

    A to-one's `| None` states something true about the data — the foreign key may be NULL. A
    to-many's states nothing: a parent with no children is handed `[]`. And because instance access
    is typed `list[M]`, the annotation would additionally be promising a list that may contain
    `None`s, which no path in the ORM can produce.

    Refused rather than quietly unwrapped, because the annotation expresses a misunderstanding of
    what a collection is and silently correcting it would leave that misunderstanding in the model
    file. Before this, the to-many branch never called `unwrap_optional` at all and the annotation
    fell over with the same `AttributeError` about `__name__`.
    """
    members = _union_members(annotation)
    if members is None:
        return
    names = " | ".join(_name_of(member) for member in members)
    raise SnakeRegistryError(
        f"To-many relationship {model.__name__}.{attr} declares a union ({names}). A collection is "
        f"not optional and does not hold optionals: a parent with no children gets an empty list, "
        f"never `None`. Declare the child model on its own "
        f"(SnakeToMany[{_name_of(members[0])}])."
    )


def _validate_pairing(
    model: type,
    attr: str,
    target_cls: type,
    local: tuple[str, ...],
    target_columns: tuple[SnakeColumnInfo, ...],
    source_table: SnakeTableInfo | None,
) -> None:
    """Validates the POSITIONAL pairing source_column[i] <-> target_PK[i] before fixing the FK.

    The mapping is by position, and a wrong order in `snake_to_one()` would silently cross columns
    over. A loud catch: (1) the same number of local columns and of target PK columns; (2) Python
    types that match pair by pair.
    """
    if len(local) != len(target_columns):
        raise SnakeModelDefinitionError(
            f"Relationship {model.__name__}.{attr} declares {len(local)} FK column(s) "
            f"[{', '.join(local)}] but the PK of {target_cls.__name__} has "
            f"{len(target_columns)} column(s) [{', '.join(c.name for c in target_columns)}]. "
            f"snake_to_one() needs EXACTLY one local column per column of the target PK, "
            f"in the same order."
        )
    if source_table is None:
        return  # with no local table the types cannot be read (hand-made info); only the count
    for source_name, target_column in zip(local, target_columns, strict=True):
        source_column = source_table.get_column(source_name)
        if source_column is None:
            continue  # another validation (the compiler) covers the non-existent column
        if source_column.python_type is not target_column.python_type:
            raise SnakeModelDefinitionError(
                f"Relationship {model.__name__}.{attr} pairs local column "
                f"'{source_name}' ({source_column.python_type.__name__}) with remote column "
                f"'{target_column.name}' ({target_column.python_type.__name__}) of the PK of "
                f"{target_cls.__name__}, but their types do NOT match. The pairing is POSITIONAL: "
                f"check the ORDER of the arguments of snake_to_one()."
            )


def hints_of(model: type) -> dict[str, Any]:
    """A model's resolved annotations, seeing what its module imports under `if TYPE_CHECKING:`.

    `get_type_hints` evaluates against the module's RUNTIME globals, and a name imported only inside
    the block is never there. That is not an edge case: it is the layout every project lands in the
    moment its models span more than one file, because `accounts` needs `Note` and `notes` needs
    `Account`, so one of the two imports HAS to go inside the block or the package stops importing
    at all. Measured, with both at runtime:

        ImportError: cannot import name 'Account' from partially initialized module

    Without this, the linker dies on `NameError: name 'Note' is not defined`, a message naming
    neither the relationship nor the model nor anything the user typed.

    The block is read only AFTER `get_type_hints` has already failed. Reading it eagerly would put a
    source parse and a set of imports in front of every model in every project, to serve the one
    that needs it; and a module whose names are all in globals gets the same answer either way.

    This is not a new mechanism: `through="Tagging"` already resolves by reading the very same
    block.
    """
    try:
        return get_type_hints(model)
    except NameError:
        return get_type_hints(model, localns=type_checking_names(model))


def _to_one_relationships(
    model: type, reg: SnakeRegistry
) -> tuple[SnakeRelationshipInfo, ...]:
    """Resolves a model's to-one relationships by reading its SnakeToOne descriptors."""
    hints = hints_of(model)
    result: list[SnakeRelationshipInfo] = []
    # Walks the MRO: it also resolves the to-one relationships INHERITED from an abstract base.
    for attr, value in collect_inherited(model, SnakeToOne).items():
        # `SnakeToOne[Brand | None]` is the way of saying "this relationship may have no partner".
        # It is unwrapped just like on a column: the target is `Brand`, and the `| None` is what the
        # checker will use to force the case to be handled.
        declared = get_args(hints[attr])[0]
        # BEFORE unwrapping: `unwrap_optional` collapses `Card | Transfer | None` to `Card` and
        # drops the rest in silence, so asking afterwards would be asking about a union that no
        # longer exists.
        _guard_one_target_model(model, attr, declared)
        target_cls, optional_relation = unwrap_optional(declared)
        target_table = reg.table_of(target_cls)
        if target_table is None:
            raise SnakeRegistryError(
                f"Relationship {model.__name__}.{attr} points at {target_cls.__name__}, "
                f"which is not registered (did you import it?)."
            )
        value._target_table = target_table
        source_table = reg.table_of(model)
        _guard_same_database(model, attr, target_cls, source_table, target_table)
        local = value.local_column_names()
        _guard_nullability_parity(model, attr, local, source_table, optional_relation)
        target_columns = target_table.primary_key.columns
        _validate_pairing(model, attr, target_cls, local, target_columns, source_table)
        remote = tuple(column.name for column in target_columns)
        pairs = tuple(zip(local, remote, strict=True))
        foreign_key = SnakeForeignKeyInfo(
            target=target_cls.__name__,
            pairs=pairs,
            on_delete=value.on_delete,
            on_update=value.on_update,
        )
        result.append(
            SnakeRelationshipInfo(
                name=attr,
                target=target_cls.__name__,
                kind=SnakeRelationshipKind.TO_ONE,
                foreign_key=foreign_key,
                # RESOLVED qualified target: reducing it to `__name__` threw the identity away and
                # two apps each with their own `Customer` clobbered each other in the by-name index
                # (a crossed FK).
                target_table=f"{target_table.schema}.{target_table.name}",
            )
        )
    return tuple(result)


def _guard_nullability_parity(
    model: type,
    attr: str,
    local: tuple[str, ...],
    source_table: SnakeTableInfo | None,
    optional_relation: bool,
) -> None:
    """Demands that the relationship say the same thing as its foreign key about possibly not existing.

    With an FK that accepts NULL, `include()` does a LEFT JOIN, finds no partner and the ORM hangs a
    `None` off the relationship. If the type says `SnakeToOne[Brand]`, the checker approves
    `car.brand.name` and in production out comes an `AttributeError`: a lie of a type, which is
    the one thing this ORM does not allow itself.

    It is demanded in BOTH directions. With a `NOT NULL` FK there is always a partner, so declaring
    the relationship optional would force an impossible case to be handled — noise that hides the
    `None`s that are real.

    With a COMPOSITE key it is enough for ONE column to accept NULL: a key with a member at NULL
    matches no row at all, so the relationship can come back empty just the same.
    """
    if (
        source_table is None
    ):  # pragma: no cover - defensive: the model is registered before linking
        return
    by_name = {column.name: column for column in source_table.columns}
    columns = [by_name[name] for name in local if name in by_name]
    if not columns:  # pragma: no cover - `_validate_pairing` already rejected it
        return
    fk_optional = any(column.nullable for column in columns)
    if fk_optional == optional_relation:
        return
    names = ", ".join(local)
    if fk_optional:
        raise SnakeModelDefinitionError(
            f"{model.__name__}.{attr} is declared WITHOUT `| None`, but its foreign key "
            f"({names}) DOES accept NULL. When the key is NULL there is nothing to fetch and the "
            f"relationship is `None`, so the type would be lying: declare it "
            f"`SnakeToOne[... | None]` and the checker will force you to handle that case."
        )
    raise SnakeModelDefinitionError(
        f"{model.__name__}.{attr} is declared with `| None`, but its foreign key ({names}) "
        f"is NOT NULL, so there is always a partner and the relationship is never `None`. Drop the "
        f"`| None`: forcing an impossible case to be handled hides the ones that are real."
    )


def _to_many_relationships(
    model: type, reg: SnakeRegistry
) -> tuple[SnakeRelationshipInfo, ...]:
    """Resolves the to-many (inverse) relationships: they read the child's resolved FK (pass 2)."""
    hints = hints_of(model)
    result: list[SnakeRelationshipInfo] = []
    # Walks the MRO: it also resolves the to-many relationships INHERITED from an abstract base.
    for attr, value in collect_inherited(model, SnakeToMany).items():
        child_cls = get_args(hints[attr])[0]
        _guard_a_collection_is_never_optional(model, attr, child_cls)
        if value.through is not None:
            result.append(_link_through(model, attr, value, child_cls, reg))
            continue
        child_table = reg.table_of(child_cls)
        if child_table is None:
            raise SnakeRegistryError(
                f"To-many relationship {model.__name__}.{attr} points at "
                f"{child_cls.__name__}, which is not registered (did you import it?)."
            )
        value._target_table = child_table
        child_fk = next(
            (rel for rel in child_table.relationships if rel.name == value.fk_name),
            None,
        )
        if child_fk is None:
            raise SnakeUnknownRelationship(
                f"To-many relationship {model.__name__}.{attr} reverses "
                f"'{value.fk_name}', which is not an FK relationship of {child_cls.__name__}."
            )
        result.append(
            # Reuses the child's FK: its pairs (child_col -> parent_PK) serve for the select-in.
            SnakeRelationshipInfo(
                name=attr,
                target=child_cls.__name__,
                kind=SnakeRelationshipKind.TO_MANY,
                foreign_key=child_fk.foreign_key,
                target_table=f"{child_table.schema}.{child_table.name}",
            )
        )
    return tuple(result)


def _link_through(
    model: type,
    attr: str,
    value: SnakeToMany[Any],
    target_cls: type,
    reg: SnakeRegistry,
) -> SnakeRelationshipInfo:
    """Resolves a MANY-TO-MANY: the bridge's two hops, already turned into columns.

    Here and not at query time because here the classes are right in front of us; storing names and
    looking them up again produced bug #14 (an FK pointing at the table of a same-named model).
    """
    # A CLASS resolves directly; only a NAME has to be looked up. The docstring above says the
    # classes are right in front of us, and that was true of the target and false of the bridge:
    # `through=` only took a string, so it went through `model_by_name` — the index `register()`
    # overwrites in silence, which is the index bug #14 was about. Worse than the query case,
    # because the metadata is compiled ONCE: the wrong bridge ends up frozen in the
    # `SnakeThroughInfo`, and the `via`/`to` pair usually matches on both homonyms, so the SELECT
    # comes out valid and reads the table that is not.
    named = value.through if isinstance(value.through, str) else None
    # A NAME is resolved in the module that WROTE it, never through the registry's by-name index.
    # That index is kept by whichever model registered last, and it does not fail loudly: with two
    # apps declaring their own `Tagging`, the `via`/`to` pair matches on both, so the SELECT is
    # valid and the `ALTER TABLE ... REFERENCES` applies without complaint, leaving referential
    # integrity pointing at a stranger's table.
    #
    # The ANNOTATION of this very same declaration already resolves this way —`SnakeToOne["Post"]`
    # goes through `get_type_hints`, which evaluates against the module's globals.
    bridge_cls = resolve_in_module(model, named) if named is not None else value.through
    bridge_table = reg.table_of(bridge_cls) if isinstance(bridge_cls, type) else None
    if bridge_table is None:
        # The message names what the USER wrote — the string they typed, or the class they passed —
        # and not the table, which they never mentioned.
        spelling = (
            named
            if named is not None
            else getattr(value.through, "__name__", value.through)
        )
        raise SnakeRegistryError(
            f"The many-to-many {model.__name__}.{attr} uses bridge '{spelling}', which is "
            f"not registered. Did you import it? The bridge is a plain model with @snake_model."
        )

    def hop(name: str, role: str) -> tuple[tuple[str, str], ...]:
        """The (bridge_column, endpoint_column) pairs of one of the bridge's relationships."""
        relation = next(
            (rel for rel in bridge_table.relationships if rel.name == name), None
        )
        if relation is None or relation.kind is not SnakeRelationshipKind.TO_ONE:
            available = sorted(
                rel.name
                for rel in bridge_table.relationships
                if rel.kind is SnakeRelationshipKind.TO_ONE
            )
            raise SnakeUnknownRelationship(
                f"The many-to-many {model.__name__}.{attr} declares {role}='{name}', which is "
                f"not a to-one relationship of '{value.through}'. The ones it has: "
                f"{', '.join(available) or '(none)'}."
            )
        return relation.foreign_key.pairs

    target_table = reg.table_of(target_cls)
    if target_table is None:
        raise SnakeRegistryError(
            f"The many-to-many {model.__name__}.{attr} points at {target_cls.__name__}, which is "
            f"not registered (did you import it?)."
        )
    value._target_table = target_table
    to_parent = hop(value.via or "", "via")
    to_target = hop(value.to or "", "to")
    return SnakeRelationshipInfo(
        name=attr,
        target=target_cls.__name__,
        kind=SnakeRelationshipKind.TO_MANY_THROUGH,
        # The "main" FK is the bridge's one towards the PARENT: it is the one filtering the select-in.
        foreign_key=SnakeForeignKeyInfo(target=model.__name__, pairs=to_parent),
        through=SnakeThroughInfo(
            table=f"{bridge_table.schema}.{bridge_table.name}",
            to_parent=to_parent,
            to_target=to_target,
        ),
        target_table=f"{target_table.schema}.{target_table.name}",
    )


def _merge_polymorphic_columns(reg: SnakeRegistry) -> None:
    """Lifts onto each polymorphic BASE the columns belonging to all of its children.

    The physical table is ONE, so the base has to know its children's columns or the `CREATE TABLE`
    would come out without them. It goes here and not in the decorator because when `Animal` is
    decorated the children do not exist yet (resolving it earlier would depend on the import order).
    """
    contributed: dict[type, list[SnakeTableInfo]] = {}
    for model in reg.models():
        table = reg.table_of(model)
        if table is None or not table.is_polymorphic_child:
            continue
        base = next(
            (
                ancestor
                for ancestor in model.__mro__[1:]
                if (ancestor_table := reg.table_of(ancestor)) is not None
                and ancestor_table.polymorphic is not None
                and ancestor_table.polymorphic.is_base
            ),
            None,
        )
        if base is not None:
            contributed.setdefault(base, []).append(table)

    for base, children in contributed.items():
        table = reg.table_of(base)
        if table is None:  # pragma: no cover
            continue
        # Not just COLUMNS: also the indexes and CHECKs the child declared over them, or the base's
        # `CREATE TABLE` silently comes out without a constraint. They are identified by their name
        # resolved against the SAME physical table, so the discriminator's own one dedupes itself.
        known = {column.name for column in table.columns}
        known_indexes = {i.resolved_name(table.name) for i in table.indexes}
        known_checks = {c.resolved_name(table.name) for c in table.checks}
        new_columns: list[SnakeColumnInfo] = []
        new_indexes: list[SnakeIndexInfo] = []
        new_checks: list[SnakeCheckInfo] = []
        for child in children:
            for column in child.columns:
                if column.name not in known:
                    known.add(column.name)
                    new_columns.append(column)
            for index in child.indexes:
                name = index.resolved_name(table.name)
                if name not in known_indexes:
                    known_indexes.add(name)
                    new_indexes.append(index)
            for check in child.checks:
                name = check.resolved_name(table.name)
                if name not in known_checks:
                    known_checks.add(name)
                    new_checks.append(check)
        if new_columns or new_indexes or new_checks:
            reg.register(
                base,
                dataclasses.replace(
                    table,
                    columns=(*table.columns, *new_columns),
                    indexes=(*table.indexes, *new_indexes),
                    checks=(*table.checks, *new_checks),
                ),
            )


def snake_link(reg: SnakeRegistry = registry) -> None:
    """Links every model: pass 1 (to-one/FK), pass 2 (to-many/inverses)."""
    _merge_polymorphic_columns(reg)
    for model in reg.models():
        table = reg.table_of(model)
        if table is None:
            continue
        reg.register(
            model,
            dataclasses.replace(table, relationships=_to_one_relationships(model, reg)),
        )
    for model in reg.models():
        table = reg.table_of(model)
        if table is None:
            continue
        to_many = _to_many_relationships(model, reg)
        if to_many:
            reg.register(
                model,
                dataclasses.replace(
                    table, relationships=(*table.relationships, *to_many)
                ),
            )
