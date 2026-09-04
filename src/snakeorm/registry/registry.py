"""The Registry: the store of compiled models (class → SnakeTableInfo)."""

from __future__ import annotations

from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.metadata import (
    SnakeRelationshipInfo,
    SnakeRoutineInfo,
    SnakeTableInfo,
    SnakeTriggerInfo,
)


class SnakeRegistry:
    """A class → SnakeTableInfo store (and name → SnakeRoutineInfo alongside it).

    @snake_model populates it (Phase 1); the linker reads it and replaces the already-linked tables
    (Phase 2). The routines from `snake_function(...)` live apart (`_routines`): they are not
    models, just a DESIRED function the diff compares against.
    """

    def __init__(self) -> None:
        self._tables: dict[type, SnakeTableInfo] = {}
        self._by_name: dict[str, SnakeTableInfo] = {}
        self._model_by_name: dict[str, type] = {}
        self._table_owner: dict[str, type] = {}
        self._routines: dict[str, SnakeRoutineInfo] = {}
        # Key (table, name): in Postgres a trigger's name is NOT unique on its own.
        self._triggers: dict[tuple[str, str], SnakeTriggerInfo] = {}
        # qualified table -> {discriminator value: class}. Nested (not a composite key) because the
        # mapper asks for the WHOLE map ONCE and resolves each row with `dict.get`.
        self._polymorphic: dict[str, dict[str, type]] = {}

    def register(self, model: type, table: SnakeTableInfo) -> None:
        """Registers (or replaces) a model's compiled table.

        Guard: two DIFFERENT models cannot map to the same qualified name (re-registering the SAME
        model is fine, e.g. after snake_link). Exception: a polymorphic hierarchy shares a table on
        purpose; it is recognised from the metadata (`is_polymorphic_child`), not from a flag, so
        nobody gets to skip the guard "just this once".
        """
        qualified = f"{table.schema}.{table.name}"
        owner = self._table_owner.get(qualified)
        if table.is_polymorphic_child:
            assert table.polymorphic is not None
            self._tables[model] = table
            self._by_name[model.__name__] = table
            self._model_by_name[model.__name__] = model
            self._polymorphic.setdefault(qualified, {})[
                table.polymorphic.value or ""
            ] = model
            return
        if owner is not None and owner is not model:
            raise SnakeRegistryError(
                f"Table collision: '{qualified}' is already registered by "
                f"{owner.__qualname__}. Disambiguate with prefix= or table= in @snake_model."
            )
        self._table_owner[qualified] = model
        self._tables[model] = table
        self._by_name[model.__name__] = table
        self._model_by_name[model.__name__] = model

    def polymorphic_map(self, table: SnakeTableInfo) -> dict[str, type]:
        """Every subclass of that table, indexed by its discriminator value.

        The WHOLE map is returned (not one class per value) because the mapper asks for it ONCE and
        resolves each row with `dict.get`; asking per row was 55% slower on the hottest path. A
        value with no subclass simply is not in the map, and that is NOT an error: it is hydrated as
        the base class (you lose the subclass's fields, not the row).
        """
        return self._polymorphic.get(f"{table.schema}.{table.name}", {})

    def table_of(self, model: type) -> SnakeTableInfo | None:
        """Returns a model's compiled table, or None if it is not registered."""
        return self._tables.get(model)

    def table_by_name(self, name: str) -> SnakeTableInfo | None:
        """Returns the table by the model's name (to resolve relation targets)."""
        return self._by_name.get(name)

    def model_by_name(self, name: str) -> type | None:
        """Returns the model's CLASS by its name (to instantiate related objects in .include())."""
        return self._model_by_name.get(name)

    def table_by_qualified(self, qualified: str) -> SnakeTableInfo | None:
        """Returns the table by its QUALIFIED name (`schema.table`), which IS unique.

        The class name is not (two apps can each have their own `Customer`, and the index keyed by
        `__name__` is kept by whichever comes last). The qualified one is protected by the collision
        guard in `register()`.
        """
        return (
            self._tables.get(self._table_owner[qualified])
            if qualified in self._table_owner
            else None
        )

    def model_by_qualified(self, qualified: str) -> type | None:
        """Returns the CLASS that owns a qualified table. Counterpart of `table_by_qualified`."""
        return self._table_owner.get(qualified)

    def resolve_relationship(
        self, relationship: SnakeRelationshipInfo
    ) -> tuple[SnakeTableInfo | None, type | None]:
        """Resolves a relation's target to `(table, class)`, unambiguously when ambiguity exists.

        It prefers the linker's qualified `target_table`; it falls back to the class name only when
        there is none (a relation rebuilt from a migration, which does not carry it). Centralised
        here so that fixing the wrong target is ONE change and not twelve copies.
        """
        if relationship.target_table:
            table = self.table_by_qualified(relationship.target_table)
            if table is not None:
                return table, self.model_by_qualified(relationship.target_table)
        return self.table_by_name(relationship.target), self.model_by_name(
            relationship.target
        )

    def models(self) -> tuple[type, ...]:
        """Lists the registered models."""
        return tuple(self._tables)

    def register_routine(self, routine: SnakeRoutineInfo) -> None:
        """Registers (or replaces) a DESIRED routine declared with `snake_function(...)`.

        Keyed by `name`: redeclaring the same name replaces the `body`, like a `CREATE OR REPLACE`.
        """
        self._routines[routine.name] = routine

    def routine_by_name(self, name: str) -> SnakeRoutineInfo | None:
        """Returns the desired routine by name, or None if it is not declared."""
        return self._routines.get(name)

    def routines(self) -> tuple[SnakeRoutineInfo, ...]:
        """Lists the registered desired routines (autodetect's code-first source of truth)."""
        return tuple(self._routines.values())

    def register_trigger(self, trigger: SnakeTriggerInfo) -> None:
        """Registers (or replaces) a DESIRED trigger declared with `snake_trigger(...)`.

        Keyed by (table, name): by name alone, a trigger of the same name on another table would
        stomp on it.
        """
        self._triggers[(trigger.table, trigger.name)] = trigger

    def triggers(self) -> tuple[SnakeTriggerInfo, ...]:
        """Lists the registered desired triggers."""
        return tuple(self._triggers.values())


registry = SnakeRegistry()
"""The default global registry that @snake_model populates."""


def registry_of(model: type) -> SnakeRegistry:
    """The registry where the model lives (the decorator put it there), or the global one.

    It is what makes `@snake_model(registry=reg)` work: everything downstream —typed navigation,
    the query, the session— has to resolve against THAT registry and not the global one, or a model
    in its own registry is registered and unreachable.

    It lives here rather than in `fields/` because it answers a REGISTRY question, and because two
    other packages were already importing the private `_registry_of` across a package boundary,
    which is the shape a helper takes just before it becomes public by accident.
    """
    return getattr(model, "__snake_registry__", registry)
