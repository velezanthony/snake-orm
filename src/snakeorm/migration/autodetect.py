"""Django-style autogen: rebuilds the state by replaying migrations and diffs it.

`replay` applies the operations of every migration onto an empty SchemaState -> the state the
schema SHOULD have according to the history. `autodetect` diffs that against the current
metadata (the code-first source of truth) and returns the operations for the new migration.
Neither snapshots nor reflection: the migration history IS the record of the state.
"""

from __future__ import annotations

from collections.abc import Iterable

from snakeorm.metadata import SnakeRoutineInfo, SnakeTableInfo, SnakeTriggerInfo
from snakeorm.migration.diff import diff_routines, diff_schema, diff_triggers
from snakeorm.migration.operations import SnakeOperation
from snakeorm.migration.runner import Migration
from snakeorm.migration.state import SchemaState
from snakeorm.registry import SnakeRegistry, registry


def current_schema(
    reg: SnakeRegistry = registry,
    *,
    database: str | None = None,
    include_unmanaged: bool = False,
) -> list[SnakeTableInfo]:
    """The current metadata (code-first source of truth): the tables of the registered models.

    Excludes MIRROR models (`@snake_db_first`): they are not a source of truth, and autogen must not
    touch them. With `database`, only those of THAT connection (which avoids creating every table in
    every DB). `include_unmanaged=True` returns them too: drift detection uses it (comparing the
    mirror against the DB), but MIGRATIONS never touch them (the default behaviour).
    """
    return [
        table
        for model in reg.models()
        if (table := reg.table_of(model)) is not None
        and (include_unmanaged or table.is_managed)
        and (database is None or table.database == database)
        # A polymorphic CHILD contributes no table: it shares its base's (which already carries
        # the whole hierarchy after `snake_link()`). Including it would duplicate the `CREATE TABLE`
        # and produce phantom drift on every `makemigrations`.
        and not table.is_polymorphic_child
    ]


def current_routines(reg: SnakeRegistry = registry) -> list[SnakeRoutineInfo]:
    """The desired routines (code-first source of truth): those declared with `snake_function`."""
    return list(reg.routines())


def current_triggers(reg: SnakeRegistry = registry) -> list[SnakeTriggerInfo]:
    """The DESIRED triggers: those declared with `snake_trigger(...)`."""
    return list(reg.triggers())


def replay(migrations: Iterable[Migration]) -> SchemaState:
    """Rebuilds the schema state by applying the migrations' operations in order."""
    state = SchemaState()
    for migration in migrations:
        for operation in migration.operations:
            operation.apply_to_state(state)
    return state


def autodetect(
    migrations: Iterable[Migration],
    current: Iterable[SnakeTableInfo],
    routines: Iterable[SnakeRoutineInfo] | None = None,
    triggers: Iterable[SnakeTriggerInfo] | None = None,
) -> list[SnakeOperation]:
    """Diffs the state replayed from the history against the current metadata -> new operations.

    Resolves FK targets by model name through the global registry. Global order: tables -> FKs ->
    views (topological) -> functions -> triggers (each one depends on the ones before it).
    """
    state = replay(migrations)
    desired_routines = current_routines() if routines is None else list(routines)
    # The state's triggers go in with the tables, and NOT because they are diffed here — that is
    # `diff_triggers`, further down. A `RebuildTable` on an engine without `ALTER TABLE ADD
    # CONSTRAINT` drops the table it remakes, which takes its triggers with it, and the operation
    # has to carry them because `SnakeTableInfo` has no field for one. This is the only caller that
    # has them, so this is where they are handed over.
    schema_ops = diff_schema(
        state.tables(),
        current,
        registry.table_by_name,
        registry.table_by_qualified,
        triggers=state.triggers(),
    )
    routine_ops = diff_routines(state.routines(), desired_routines)
    # TRIGGERS go last: a Postgres one executes a FUNCTION, which has to exist beforehand.
    trigger_ops = diff_triggers(
        state.triggers(), current_triggers() if triggers is None else list(triggers)
    )
    return [*schema_ops, *routine_ops, *trigger_ops]
