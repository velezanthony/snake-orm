"""Triggers: the signal that lives in the DATABASE.

They are not the Python signals (6.2). The difference is not one of implementation, it is one of
GUARANTEE: a trigger holds even if the row is written by another process, a script or a `psql`,
because the rule lives in the schema. A code signal only fires if the write goes through the session.

Hence `snake_trigger` does NOT accept a Python callable: it is not a limitation, it is the border
between the two mechanisms, and the type makes it unwritable.

The body is OPAQUE (`body: str`), just as in `SnakeRoutineInfo`: the diff compares the string. Typing
PL/pgSQL would mean putting a whole language inside the ORM.
"""

from __future__ import annotations

from typing import cast

import pytest

from snakeorm import PostgresDialect
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.metadata import SnakeTriggerEvent, SnakeTriggerInfo, SnakeTriggerTiming
from snakeorm.migration import (
    AlterTrigger,
    CreateTrigger,
    DropTrigger,
    SnakeOperation,
    emit_create_trigger,
    emit_drop_trigger,
)

_DIALECT = PostgresDialect()


def _one(statements: list[str]) -> str:
    """The single statement these cases produce, with the reason it is single.

    `emit_create_trigger` returns a LIST because on PostgreSQL an inline body becomes a function plus
    the trigger that calls it. Every trigger in this file already declares the PostgreSQL shape
    (`EXECUTE FUNCTION ...`), which the dialect leaves alone — so one declaration, one statement. The
    wrapping is exercised in `test_trigger_body_is_engine_specific.py`.
    """
    assert len(statements) == 1, statements
    return statements[0]


def _trigger(body: str = "EXECUTE FUNCTION auditar()") -> SnakeTriggerInfo:
    """Audit trigger on `orders`."""
    return SnakeTriggerInfo(
        name="tg_auditar_orders",
        table="orders",
        timing=SnakeTriggerTiming.AFTER,
        events=(SnakeTriggerEvent.INSERT, SnakeTriggerEvent.UPDATE),
        body=body,
    )


def test_it_emits_the_timing_and_every_event() -> None:
    """The DDL carries the timing and ALL the events, separated by OR as SQL demands."""
    sql = _one(emit_create_trigger(_trigger(), _DIALECT))

    assert sql.startswith('CREATE TRIGGER "tg_auditar_orders" AFTER INSERT OR UPDATE')
    assert 'ON "public"."orders"' in sql
    assert sql.endswith("FOR EACH ROW EXECUTE FUNCTION auditar()")


def test_the_events_keep_their_declared_order() -> None:
    """The declared order is respected: `INSERT OR DELETE` does not read as `DELETE OR INSERT`.

    SQL treats them the same, but a DDL that reorders what the user wrote makes noise in every
    diff and in every code review, gaining nothing.
    """
    trigger = SnakeTriggerInfo(
        name="tg",
        table="t",
        timing=SnakeTriggerTiming.BEFORE,
        events=(SnakeTriggerEvent.DELETE, SnakeTriggerEvent.INSERT),
        body="EXECUTE FUNCTION f()",
    )

    assert "BEFORE DELETE OR INSERT" in _one(emit_create_trigger(trigger, _DIALECT))


def test_a_trigger_without_events_is_refused() -> None:
    """A trigger that fires at NOTHING is a dead object: it is refused at declaration time."""
    with pytest.raises(SnakeModelDefinitionError, match="does not declare any event"):
        SnakeTriggerInfo(
            name="tg",
            table="t",
            timing=SnakeTriggerTiming.BEFORE,
            events=(),
            body="EXECUTE FUNCTION f()",
        )


def test_dropping_names_the_table() -> None:
    """`DROP TRIGGER` needs the table: in Postgres the name is not unique on its own.

    Two tables can have a trigger with the same name, so forgetting the `ON` is not a matter of
    style — it is that the statement does not identify what it wants to drop.
    """
    sql = _one(emit_drop_trigger(_trigger(), _DIALECT))

    assert sql == 'DROP TRIGGER "tg_auditar_orders" ON "public"."orders"'


def test_the_operations_are_reversible() -> None:
    """Creating and dropping are exact inverses, which is what makes a `rollback` usable."""
    trigger = _trigger()

    assert CreateTrigger(trigger).up_sql(_DIALECT) == [
        _one(emit_create_trigger(trigger, _DIALECT))
    ]
    assert CreateTrigger(trigger).down_sql(_DIALECT) == [
        _one(emit_drop_trigger(trigger, _DIALECT))
    ]
    assert DropTrigger(trigger).up_sql(_DIALECT) == [
        _one(emit_drop_trigger(trigger, _DIALECT))
    ]
    assert DropTrigger(trigger).down_sql(_DIALECT) == [
        _one(emit_create_trigger(trigger, _DIALECT))
    ]


def test_altering_replaces_the_whole_trigger() -> None:
    """Postgres has no portable `CREATE OR REPLACE TRIGGER`: it is dropped and created.

    And the `down` does the same with the OLD body, so undoing a trigger change gives back
    exactly the one that was there.
    """
    old, new = _trigger("EXECUTE FUNCTION v1()"), _trigger("EXECUTE FUNCTION v2()")
    operation = AlterTrigger(old, new)

    assert operation.up_sql(_DIALECT) == [
        _one(emit_drop_trigger(old, _DIALECT)),
        _one(emit_create_trigger(new, _DIALECT)),
    ]
    assert operation.down_sql(_DIALECT) == [
        _one(emit_drop_trigger(new, _DIALECT)),
        _one(emit_create_trigger(old, _DIALECT)),
    ]


def test_a_trigger_survives_the_round_trip() -> None:
    """The full cycle: operation → migration file → import → identical operation.

    It is point 2 of the contract, and the one `db_comment` forgot back in the day: metadata that
    gets captured and stored but never reaches the file is dead metadata. Here it is checked by
    executing the generated file, not by reading it.
    """
    from snakeorm.migration.render import render_migration

    operations: list[SnakeOperation] = [
        CreateTrigger(_trigger()),
        AlterTrigger(_trigger("v1()"), _trigger("v2()")),
    ]
    source = render_migration("0001_triggers", operations)

    namespace: dict[str, object] = {}
    exec(compile(source, "0001_triggers.py", "exec"), namespace)  # noqa: S102
    rebuilt = cast("list[SnakeOperation]", namespace["operations"])

    emitted = [sql for op in operations for sql in op.up_sql(_DIALECT)]
    remade = [sql for op in rebuilt for sql in op.up_sql(_DIALECT)]
    assert remade == emitted


def test_the_enums_are_rendered_by_member_not_by_value() -> None:
    """The file says `SnakeTriggerTiming.AFTER`, not `"AFTER"`.

    Migrations get READ, and an enum member says which family it belongs to and what other options
    there are. Same criterion as `SnakeFkAction` or `SnakeServerDefault`.
    """
    from snakeorm.migration.render import render_migration

    source = render_migration("0001_t", [CreateTrigger(_trigger())])

    assert "SnakeTriggerTiming.AFTER" in source
    assert "SnakeTriggerEvent.INSERT" in source


def test_a_trigger_declared_with_snake_trigger_reaches_the_migration() -> None:
    """`snake_trigger(...)` -> registry -> `autodetect` -> `CreateTrigger`. The whole path, once.

    Everything else in this file builds a `SnakeTriggerInfo(...)` by hand, which is the right shape
    for testing the EMISSION and skips the one thing `snake_trigger` does that the constructor does
    not: `registry.register_trigger`. So the public function was never called anywhere in `src/` or
    `frameworks/` — it lived in two documentation pages and nowhere else — and the path by which a
    declared trigger actually reaches a migration had no exercise behind it.

    An isolated registry rather than the global one: a trigger left behind in the shared registry
    would show up in another test's `autodetect` as a change nobody asked for.
    """
    from snakeorm.decorators import snake_trigger
    from snakeorm.migration.autodetect import autodetect, current_triggers
    from snakeorm.registry import SnakeRegistry

    aparte = SnakeRegistry()
    declarado = snake_trigger(
        name="tg_audit_orders",
        table="orders",
        timing=SnakeTriggerTiming.AFTER,
        events=(SnakeTriggerEvent.INSERT,),
        body="EXECUTE FUNCTION audit()",
        registry=aparte,
    )

    assert current_triggers(aparte) == [declarado], (
        "snake_trigger returned the info but did not register it, so autodetect never sees it"
    )
    operaciones = autodetect([], [], triggers=current_triggers(aparte))
    creados = [op for op in operaciones if isinstance(op, CreateTrigger)]

    assert [op.definition.name for op in creados] == ["tg_audit_orders"]
