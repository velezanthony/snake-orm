"""`snake_function`: DECLARES a DESIRED stored function/procedure for the autodetect.

A module helper (not a decorator: the routine has no Python body) that registers the routine in the
registry. The `body` is the raw and complete `CREATE OR REPLACE FUNCTION ...` (the ORM does not
check what it does). The autodetect compares it against the history and emits
`CreateFunction`/`AlterFunction` (the `body` changed)/`DropFunction`. Functions are created AFTER
tables and views and are NOT ordered among themselves.
"""

from __future__ import annotations

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.metadata import SnakeRoutineInfo
from snakeorm.registry import registry


def snake_function(
    *, name: str, body: str, schema: str = DEFAULT_SCHEMA
) -> SnakeRoutineInfo:
    """Declare and register a desired routine; return its compiled `SnakeRoutineInfo`.

    Registering the same `name` replaces the previous `body` (CREATE OR REPLACE semantics). Using
    the returned object is optional: the source of truth is the registry, which the autodetect
    consults.
    """
    routine = SnakeRoutineInfo(name=name, body=body, schema=schema)
    registry.register_routine(routine)
    return routine
