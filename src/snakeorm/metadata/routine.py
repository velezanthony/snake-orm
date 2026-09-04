"""Immutable metadata of a DB ROUTINE (stored function or procedure).

OPAQUE SQL that lives in the DB: the ORM does not check what it does. `body` is the whole
`CREATE [OR REPLACE] FUNCTION ...`, raw and non-portable; with no columns to diff, the diff only
compares the `body` string. It is declared with `snake_function(...)` and autodetect emits
Create/Alter/DropFunction.
"""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm.core.placement import DEFAULT_SCHEMA


@dataclass(frozen=True, slots=True)
class SnakeRoutineInfo:
    """Metadata of a routine: name, raw SQL body and schema.

    `body` is the whole `CREATE OR REPLACE FUNCTION ...` (opaque): the diff only compares the
    string, and the creation DDL IS the body itself.
    """

    name: str
    body: str
    schema: str = DEFAULT_SCHEMA
