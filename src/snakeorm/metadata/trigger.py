"""Metadata of a TRIGGER: the signal that lives in the database.

Against a code signal (`snakeorm/signals.py`), a trigger holds even when the row is written by
another process or by a `psql`, because the rule lives in the schema. That is why the `body` is SQL
and only SQL: no callables, this is the border between the two mechanisms.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.core.exceptions import SnakeModelDefinitionError


class SnakeTriggerTiming(Enum):
    """When it fires relative to the operation. Engine-agnostic: all three are standard SQL."""

    BEFORE = "BEFORE"
    AFTER = "AFTER"
    INSTEAD_OF = "INSTEAD OF"


class SnakeTriggerEvent(Enum):
    """Which operation fires it."""

    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    TRUNCATE = "TRUNCATE"


@dataclass(frozen=True, slots=True)
class SnakeTriggerInfo:
    """A trigger on a table: when, on what, and what it runs.

    `body` is raw and opaque (`EXECUTE FUNCTION audit()`), as in `SnakeRoutineInfo`: the diff only
    compares the string (typing PL/pgSQL would mean putting a whole language inside the ORM).
    `for_each_row` tells a per-ROW trigger apart from a per-STATEMENT one; per row by default
    (required for `NEW`/`OLD`).
    """

    name: str
    table: str
    timing: SnakeTriggerTiming
    events: tuple[SnakeTriggerEvent, ...]
    body: str
    schema: str = DEFAULT_SCHEMA
    for_each_row: bool = True

    def __post_init__(self) -> None:
        """A trigger with no events fires on nothing: a dead object.

        It is rejected at DECLARATION time (not at emission), while the user still remembers what
        they meant to write.
        """
        if not self.events:
            raise SnakeModelDefinitionError(
                f"Trigger '{self.name}' does not declare any event, so it would never fire. "
                f"Declare at least one event (INSERT, UPDATE, DELETE or TRUNCATE)."
            )
