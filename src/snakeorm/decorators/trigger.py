"""Declaring TRIGGERS: the signal that lives inside the database.

It mirrors `snake_function`: you declare it, it gets registered and the autodetect compares it
against the history (source of truth: the registry). It does NOT accept a Python callable on
purpose: the trigger holds even if another process or a `psql` does the writing, because the rule
lives in the engine. For Python code there is `snake_on`, which only fires if the write goes
through the session.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.metadata import SnakeTriggerEvent, SnakeTriggerInfo, SnakeTriggerTiming
from snakeorm.registry import SnakeRegistry
from snakeorm.registry import registry as default_registry


def snake_trigger(
    *,
    name: str,
    table: str,
    timing: SnakeTriggerTiming,
    events: Sequence[SnakeTriggerEvent],
    body: str,
    schema: str = DEFAULT_SCHEMA,
    for_each_row: bool = True,
    registry: SnakeRegistry = default_registry,
) -> SnakeTriggerInfo:
    """Declare and register a desired trigger; return its `SnakeTriggerInfo`.

    `body` is raw, opaque SQL: the diff only compares it as a string. Redeclaring the same
    `(table, name)` replaces the previous one; the key carries the table because in Postgres the
    name of a trigger is not unique on its own.
    """
    trigger = SnakeTriggerInfo(
        name=name,
        table=table,
        timing=timing,
        events=tuple(events),
        body=body,
        schema=schema,
        for_each_row=for_each_row,
    )
    registry.register_trigger(trigger)
    return trigger
