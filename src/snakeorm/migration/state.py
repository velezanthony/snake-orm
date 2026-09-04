"""SchemaState: the schema's mutable state, rebuilt by replaying migrations.

It is the equivalent of Django's `ProjectState`. Every operation knows how to mutate it
(`apply_to_state`), just as it knows how to emit its SQL. Autogen replays the migrations'
operations onto an empty SchemaState to obtain the "previous state", and diffs that against the
current metadata.
"""

from __future__ import annotations

from collections.abc import Iterable

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.metadata import SnakeRoutineInfo, SnakeTableInfo, SnakeTriggerInfo


class SchemaState:
    """A mutable collection of tables (and routines), indexed by name."""

    def __init__(
        self,
        tables: Iterable[SnakeTableInfo] = (),
        routines: Iterable[SnakeRoutineInfo] = (),
        triggers: Iterable[SnakeTriggerInfo] = (),
    ) -> None:
        self._tables: dict[str, SnakeTableInfo] = {
            table.name: table for table in tables
        }
        self._routines: dict[str, SnakeRoutineInfo] = {
            routine.name: routine for routine in routines
        }
        # A trigger's key is (table, name): in Postgres the name is not unique, two tables can
        # each have one of the same name, and indexing by name alone would overwrite one silently.
        self._triggers: dict[tuple[str, str], SnakeTriggerInfo] = {
            (trigger.table, trigger.name): trigger for trigger in triggers
        }
        # `public` always exists in Postgres: nobody creates it and nobody should drop it.
        self._schemas: set[str] = {DEFAULT_SCHEMA}

    def add_table(self, table: SnakeTableInfo) -> None:
        """Adds (or replaces) a table in the state."""
        self._tables[table.name] = table

    def remove_table(self, name: str) -> None:
        """Removes a table from the state AND the triggers that hung off it.

        A trigger belongs to its table on all three engines: a `DROP TABLE` takes it along, and
        nothing is left to drop afterwards. The state used to keep it, and it was the only thing in
        the system still believing in it — `squash`, which re-emits everything the state holds, put
        a `CreateTrigger` in the collapsed migration for a table that migration never creates, and a
        fresh install died on that statement.

        A rename goes through here too, and there the trigger does NOT disappear: it follows the
        table. `RenameTable.apply_to_state` puts it back under the new name, for the same reason it
        already re-points the foreign keys.
        """
        self._tables.pop(name, None)
        for key in [key for key in self._triggers if key[0] == name]:
            del self._triggers[key]

    def get_table(self, name: str) -> SnakeTableInfo | None:
        """Returns the table by name, or None if it is not in the state."""
        return self._tables.get(name)

    def tables(self) -> tuple[SnakeTableInfo, ...]:
        """The tables of the current state."""
        return tuple(self._tables.values())

    def add_schema(self, schema: str) -> None:
        """Records a schema as existing."""
        self._schemas.add(schema)

    def remove_schema(self, schema: str) -> None:
        """Removes a schema from the state (idempotent if it was not there)."""
        self._schemas.discard(schema)

    def schemas(self) -> frozenset[str]:
        """Schemas the state takes to exist."""
        return frozenset(self._schemas)

    def add_routine(self, routine: SnakeRoutineInfo) -> None:
        """Adds (or replaces) a routine (function/procedure) in the state."""
        self._routines[routine.name] = routine

    def remove_routine(self, name: str) -> None:
        """Removes a routine from the state (idempotent if it is not there)."""
        self._routines.pop(name, None)

    def get_routine(self, name: str) -> SnakeRoutineInfo | None:
        """Returns the routine by name, or None if it is not in the state."""
        return self._routines.get(name)

    def routines(self) -> tuple[SnakeRoutineInfo, ...]:
        """The routines of the current state."""
        return tuple(self._routines.values())

    def add_trigger(self, trigger: SnakeTriggerInfo) -> None:
        """Adds (or replaces) a trigger. The key is (table, name), not the name alone."""
        self._triggers[(trigger.table, trigger.name)] = trigger

    def remove_trigger(self, table: str, name: str) -> None:
        """Removes a trigger from the state (idempotent if it is not there)."""
        self._triggers.pop((table, name), None)

    def triggers(self) -> tuple[SnakeTriggerInfo, ...]:
        """The triggers of the current state."""
        return tuple(self._triggers.values())
