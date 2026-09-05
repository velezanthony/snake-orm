"""Collapsing N migrations into a single one, declaring which ones it replaces.

The collapse is a replay up to the final state. The delicate part is the DB where the originals have
ALREADY been applied: there the squash must not run (its `CREATE TABLE` would die against tables
that exist), hence the `replaces` the runner uses to decide (see `MigrationRunner.apply`). It is a
DESKTOP operation (it does not touch the DB), and that is why it cannot merge DATA operations.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.migration.autodetect import replay
from snakeorm.migration.diff import diff_routines, diff_schema, diff_triggers
from snakeorm.migration.operations import RunPython, RunSQL, SnakeOperation
from snakeorm.migration.runner import Migration


def squash(migrations: Sequence[Migration], *, version: str) -> Migration:
    """Collapses `migrations` into ONE producing the same final state.

    It emits the state they lead to, not the steps (a column added and then dropped does not show
    up). Crossing a DATA operation (`RunPython`, `RunSQL`) is rejected: its `apply_to_state` is a
    no-op, so merging them would demand EXECUTING them, and the collapse does not touch the DB
    (losing them would silently leave data unmigrated).
    """
    if not migrations:
        raise SnakeMigrationError("A squash needs at least one migration to collapse.")

    for migration in migrations:
        for operation in migration.operations:
            if isinstance(operation, (RunPython, RunSQL)):
                raise SnakeMigrationError(
                    f"Migration '{migration.version}' contains a DATA operation "
                    f"({type(operation).__name__}), which cannot be collapsed: mutating rows "
                    f"demands running it, and a squash does not touch the database. Collapse the "
                    f"stretch that reaches UP TO it and leave the rest of the history as it is."
                )

    # The replayed final state, diffed against nothing: that IS the squash. EVERY collection the
    # state holds has to be re-emitted, and in `autodetect`'s order — tables first, then the
    # routines and triggers that may reference them. Anything not re-emitted here is dropped from
    # the collapsed history in silence, and a fresh install comes up without it.
    #
    # That is not hypothetical: it happened to the routines, was fixed by adding their line, and the
    # triggers stayed missing for exactly as long, because the test written that day knew only about
    # routines. The two callers are compared in `test_squash.py` now, so the next collection added
    # to `SchemaState` cannot be forgotten the same way.
    state = replay(migrations)
    operations: list[SnakeOperation] = [
        *diff_schema([], state.tables()),
        *diff_routines([], state.routines()),
        *diff_triggers([], state.triggers()),
    ]
    return Migration(
        version=version,
        operations=tuple(operations),
        replaces=tuple(migration.version for migration in migrations),
    )
