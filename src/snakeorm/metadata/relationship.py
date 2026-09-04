"""Immutable metadata of a relationship between models."""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm.metadata.foreign_key import SnakeForeignKeyInfo
from snakeorm.metadata.relationship_kind import SnakeRelationshipKind


@dataclass(frozen=True, slots=True)
class SnakeThroughInfo:
    """The BRIDGE of a many-to-many: its table and both hops, already resolved.

    `to_parent`/`to_target` are `(bridge_column, endpoint_column)` pairs, resolved by the linker and
    not by name (bug #14: resolving by class name sent the FK to a different table with the same
    name). A composite FK fits with no special case: tuples of pairs, as in `SnakeForeignKeyInfo`.
    """

    table: str
    """The bridge's table, QUALIFIED (`schema.table`)."""
    to_parent: tuple[tuple[str, str], ...]
    to_target: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class SnakeRelationshipInfo:
    """A navigation view over an FK.

    `kind` tells to_one (`user.owner` -> `User`) apart from to_many (`country.cities` ->
    `list[City]`). `target` is the NAME of the target model.

    `target_table` is that target already resolved and qualified (`schema.table`). It exists
    because a class name does not identify a model (two apps each with their own `Customer`; the
    index keyed by `__name__` was kept by whichever registered last -> FK to the wrong table,
    depending on import order). The qualified table IS unique (the registry's collision guard).

    A DERIVED field, not a declared one: the linker fills it in, it is NOT serialised and does NOT
    enter the diff. Old migrations keep replaying with an empty `target_table` and fall back to
    resolving by name.
    """

    name: str
    target: str
    kind: SnakeRelationshipKind
    foreign_key: SnakeForeignKeyInfo
    through: SnakeThroughInfo | None = None
    """The bridge, only on `to_many_through`. It tells a to-many over a direct FK apart from one
    that crosses an intermediate table: they load differently, and mixing them up would fire a
    select-in against the wrong table."""
    target_table: str = ""

    def __post_init__(self) -> None:
        """Normalises `kind` to the enum, accepting the string of already-written history.

        Converting at the boundary lets everything inside compare with `is`, no exceptions.
        `object.__setattr__` because the dataclass is `frozen` (the same mechanism the generated
        `__init__` uses).
        """
        object.__setattr__(self, "kind", SnakeRelationshipKind.coerce(self.kind))
