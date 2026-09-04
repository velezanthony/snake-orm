"""Turning declared specs into the SHAPES that get written: annotations, nesting, and write order.

The metadata graph has the last word here. A spec carries paths, which are names; what a name MEANS
— a column of this type, a to-one that may find nothing, a collection — is a question only the
compiled `SnakeTableInfo` can answer, and asking it is this module's whole job.

Three rules, each of which has a way of being quietly wrong:

NULLABILITY is accumulated over the WHOLE path and never read off the last step. One nullable key
anywhere along the way means the value can arrive as `None`, however NOT NULL the column at the end
is. `editor.username` is `str | None`; so is `author.country.name`, where the only nullable hop is
in the middle and both ends are required.

NESTING resolves to another SPEC, never to the far model's columns. Zero specs for that model is an
error; two is an error naming both. Picking whichever is bug #14 in another costume — it does not
fail, it publishes the wrong shape.

ORDER is by DEPENDENCY. Python reads a file top to bottom, so a class that mentions another has to
come after it, whichever order the two declarations were written in. A cycle has no such order, so
it is named and refused rather than resolved into a file that does not import.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto.spec import SnakeDtoPick, SnakeDtoSpec
from snakeorm.helpers.pytype import type_annotation
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
)
from snakeorm.registry import registry_of


@dataclass(frozen=True, slots=True)
class SnakeDtoField:
    """One key of a generated class: its name, its annotation as SOURCE, and the import it needs."""

    name: str
    annotation: str
    requires: str | None = None
    """The module that has to be in scope for `annotation` to resolve, or `None` for a builtin.

    It travels with the field because the generator writes into somebody's file and never writes
    their imports: without this the writer could not refuse a field it cannot spell there.
    """


@dataclass(frozen=True, slots=True)
class SnakeDtoShape:
    """One class ready to be written: its name and its keys, in the order they go in."""

    name: str
    fields: tuple[SnakeDtoField, ...]


def resolve_all(specs: Sequence[SnakeDtoSpec]) -> tuple[SnakeDtoShape, ...]:
    """Every spec of one file resolved together, in the order they have to be WRITTEN in.

    Together and not one at a time, because a nested field points at another spec: a DTO cannot be
    resolved without the set it belongs to.
    """
    _guard_unique_names(specs)
    by_name = {spec.name: spec for spec in specs}
    shapes: dict[str, SnakeDtoShape] = {}
    needs: dict[str, set[str]] = {}
    for spec in specs:
        fields, depends = _shape_of(spec, specs, by_name)
        shapes[spec.name] = SnakeDtoShape(name=spec.name, fields=fields)
        needs[spec.name] = depends
    return tuple(shapes[name] for name in _write_order(specs, needs))


def _guard_unique_names(specs: Sequence[SnakeDtoSpec]) -> None:
    """Two specs of one name in one file would be two classes of one name: the second wins, silently."""
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise SnakeDtoError(
                f"{spec.name!r} is declared twice in this file. Two classes of one name means the "
                f"second silently replaces the first: give one of them a name of its own."
            )
        seen.add(spec.name)


def _write_order(
    specs: Sequence[SnakeDtoSpec], needs: dict[str, set[str]]
) -> list[str]:
    """Names sorted so that everything a class nests is defined above it. Declaration order breaks ties.

    A plain depth-first walk with a colour mark, which is what makes the CYCLE reportable: the grey
    set IS the stack, so the names in it when an edge points back are exactly the loop, in order.
    Ties keep the declaration order, so two classes that depend on nothing do not get reshuffled —
    a sort that churned independent classes would rewrite the region for no reason, and the diff is
    the product here.
    """
    order: list[str] = []
    done: set[str] = set()
    stack: list[str] = []

    def visit(name: str) -> None:
        if name in done:
            return
        if name in stack:
            loop = [*stack[stack.index(name) :], name]
            raise SnakeDtoError(
                f"these DTOs nest each other in a cycle: {' -> '.join(loop)}. There is no order "
                f"that defines each one before it is mentioned, so nothing was written: break the "
                f"loop by dropping one of the nested fields."
            )
        stack.append(name)
        for nested in sorted(needs.get(name, set())):
            visit(nested)
        stack.pop()
        done.add(name)
        order.append(name)

    for spec in specs:
        visit(spec.name)
    return order


def _shape_of(
    spec: SnakeDtoSpec,
    specs: Sequence[SnakeDtoSpec],
    by_name: dict[str, SnakeDtoSpec],
) -> tuple[tuple[SnakeDtoField, ...], set[str]]:
    """One spec's fields, and the names of the DTOs it nests."""
    table = _table_of(spec.model)
    fields: list[SnakeDtoField] = []
    depends: set[str] = set()
    taken: set[str] = set()
    for pick in _picks(spec, table):
        field, nested = _field_of(pick, spec, table, specs, by_name)
        if field.name in taken:
            raise SnakeDtoError(
                f"{spec.name} would carry the key {field.name!r} twice: two of its fields resolve "
                f"to the same name. A generated key is named after its whole path, so rename the "
                f"column or drop one of the two."
            )
        taken.add(field.name)
        fields.append(field)
        if nested is not None:
            depends.add(nested)
    return tuple(fields), depends


def _picks(spec: SnakeDtoSpec, table: SnakeTableInfo) -> list[SnakeDtoPick]:
    """What the spec selects: what it named, or every column when it named nothing.

    Neither switch is every COLUMN and no relationship. Nesting by default would drag an object
    graph into a response nobody asked for, and could not be written at all without a spec for every
    model it reached.
    """
    if spec.fields is not None:
        return list(spec.fields)
    dropped = {path[0] for path in spec.exclude}
    return [
        SnakeDtoPick(path=(_attribute(column.attr_name, column.name),))
        for column in table.columns
        if _attribute(column.attr_name, column.name) not in dropped
    ]


def _field_of(
    pick: SnakeDtoPick,
    spec: SnakeDtoSpec,
    table: SnakeTableInfo,
    specs: Sequence[SnakeDtoSpec],
    by_name: dict[str, SnakeDtoSpec],
) -> tuple[SnakeDtoField, str | None]:
    """One selected path resolved into a field, plus the DTO it nests if it nests one."""
    landing, optional = _walk(table, spec.model, pick.path, spec.name)
    name = "_".join(pick.path)
    if isinstance(landing, SnakeRelationshipInfo):
        nested = _nested_name(landing, pick, spec, specs, by_name)
        many = landing.kind is not SnakeRelationshipKind.TO_ONE
        annotation = f"list[{nested}]" if many else nested
        # A collection is never `None`: a parent with no children gets `[]`. What CAN vanish is the
        # collection's owner, when the path crossed a nullable key to reach it.
        if optional:
            annotation = f"{annotation} | None"
        return SnakeDtoField(name=name, annotation=annotation), nested
    spelled, module = type_annotation(landing.python_type)
    nullable = landing.nullable or optional
    return (
        SnakeDtoField(
            name=name,
            annotation=f"{spelled} | None" if nullable else spelled,
            requires=module,
        ),
        None,
    )


def _nested_name(
    relationship: SnakeRelationshipInfo,
    pick: SnakeDtoPick,
    spec: SnakeDtoSpec,
    specs: Sequence[SnakeDtoSpec],
    by_name: dict[str, SnakeDtoSpec],
) -> str:
    """Which DTO a relationship field nests: the one the user named, or the only candidate.

    "The only" is load-bearing. Two specs over one model and no rule to choose between them is the
    same defect as resolving a model by class name — it produces a valid-looking class describing
    the wrong shape, and nothing anywhere goes red.
    """
    reg = registry_of(spec.model)
    target = reg.resolve_relationship(relationship)[1]
    if target is None:
        raise SnakeDtoError(
            f"{spec.name} nests {relationship.name!r}, whose target {relationship.target!r} is not "
            f"registered. Import the module that declares it, and call `snake_link()`."
        )
    candidates = [item.name for item in specs if item.model is target]
    if pick.dto is not None:
        named = by_name.get(pick.dto)
        if named is None:
            raise SnakeDtoError(
                f"{spec.name} nests {relationship.name!r} as {pick.dto!r}, and no spec of that "
                f"name is declared in this file. Over {target.__name__} there is: "
                f"{', '.join(candidates) or '(none)'}."
            )
        if named.model is not target:
            raise SnakeDtoError(
                f"{spec.name} nests {relationship.name!r} as {pick.dto!r}, which describes "
                f"{named.model.__name__} and not {target.__name__}. It would type-check and it "
                f"would put another table's fields in this response."
            )
        return named.name
    if not candidates:
        raise SnakeDtoError(
            f"{spec.name} nests {relationship.name!r}, and no spec describes {target.__name__}. A "
            f"relationship is written as the DTO of its model, so declare one: "
            f"`snake_dto({target.__name__}, fields=[...], name=...)`."
        )
    if len(candidates) > 1:
        listed = ", ".join(sorted(candidates))
        raise SnakeDtoError(
            f"{spec.name} nests {relationship.name!r} and {target.__name__} has more than one "
            f"spec ({listed}), so there is no telling which shape this field is. Nothing is "
            f"picked: say which, with "
            f"`({spec.model.__name__}.{relationship.name}, {sorted(candidates)[0]!r})`."
        )
    return candidates[0]


def _walk(
    table: SnakeTableInfo, model: type, path: tuple[str, ...], dto: str
) -> tuple[SnakeColumnInfo | SnakeRelationshipInfo, bool]:
    """Follows a path across to-ones and returns what it LANDS on, and whether it can find nothing.

    The landing is a `SnakeColumnInfo` or a `SnakeRelationshipInfo` — a column or a relationship —
    and the caller decides what to do with each. `optional` accumulates over every hop and is never
    reset: that is the correctness of this function in one line.
    """
    reg = registry_of(model)
    optional = False
    current, owner = table, model
    for index, step in enumerate(path):
        column = current.get_column_by_attr(step)
        relationship = _relationship_named(current, step)
        last = index == len(path) - 1
        if column is not None and last:
            return column, optional
        if relationship is None:
            known = ", ".join(
                [_attribute(item.attr_name, item.name) for item in current.columns]
                + [item.name for item in current.relationships]
            )
            raise SnakeDtoError(
                f"{dto} selects {'.'.join(path)!r}, and {owner.__name__} has no {step!r}. It has: "
                f"{known}."
            )
        if last:
            # The LAST hop counts too, and forgetting it is the bug this line exists for: a path
            # that ends ON a to-one crosses that key, so `Post.editor` is `EditorDto | None` for
            # exactly the reason `Post.editor.username` is `str | None`. A to-many is never
            # optional by its own key — that key lives on the child, and no children is `[]`.
            if relationship.kind is SnakeRelationshipKind.TO_ONE:
                optional = optional or _to_one_is_optional(current, relationship)
            return relationship, optional
        if relationship.kind is not SnakeRelationshipKind.TO_ONE:
            raise SnakeDtoError(
                f"step {step!r} of {'.'.join(path)!r} in {dto} is a {relationship.kind.value}, and "
                f"a path can only be continued across a to-one. A collection has no single row to "
                f"read the next step off: nest it whole instead."
            )
        optional = optional or _to_one_is_optional(current, relationship)
        target, target_model = reg.resolve_relationship(relationship)
        if target is None or target_model is None:
            raise SnakeDtoError(
                f"step {step!r} of {'.'.join(path)!r} in {dto} points at "
                f"{relationship.target!r}, which is not registered. Import the module that "
                f"declares it, and call `snake_link()`."
            )
        current, owner = target, target_model
    raise SnakeDtoError(f"{dto} selects an empty path, which names nothing.")


def _to_one_is_optional(
    table: SnakeTableInfo, relationship: SnakeRelationshipInfo
) -> bool:
    """Whether crossing this to-one can find NOTHING. One nullable member of the key is enough.

    A pair whose local column is not on the table RAISES rather than being skipped. Skipping it and
    letting `any()` fall through to `False` would answer NOT NULL for a key it could not read, and
    that is the one direction this function must never fail in: the DTO promises a value that
    arrives as `None`, the checker believes it, and nothing anywhere goes red.

    The pair is `(source_column, target_column)` and the source side belongs to the declaring table,
    so this cannot happen while the linker is right. That is precisely why it is worth saying out
    loud — an invariant nobody checks is a defect waiting to be plausible.
    """
    by_name = {column.name: column for column in table.columns}
    missing = [
        pair[0] for pair in relationship.foreign_key.pairs if pair[0] not in by_name
    ]
    if missing:
        raise SnakeDtoError(
            f"the key of {relationship.name!r} reads {', '.join(missing)} off {table.name}, which "
            f"has no such column, so there is no telling whether crossing it can find nothing. "
            f"Nothing was written: this is the graph being inconsistent, not the declaration."
        )
    return any(by_name[pair[0]].nullable for pair in relationship.foreign_key.pairs)


def _relationship_named(
    table: SnakeTableInfo, name: str
) -> SnakeRelationshipInfo | None:
    """The relationship with that attribute name, or `None`."""
    return next((item for item in table.relationships if item.name == name), None)


def _table_of(model: type) -> SnakeTableInfo:
    """The model's compiled table, asked of the registry the model itself lives in."""
    table = registry_of(model).table_of(model)
    if table is None:
        raise SnakeDtoError(
            f"{getattr(model, '__name__', model)!r} is not a compiled model, so there is no column "
            f"list to read."
        )
    return table


def _attribute(attr_name: str, sql_name: str) -> str:
    """The column's PYTHON name, which `snake_column(name=...)` can split from its SQL one."""
    return attr_name or sql_name
