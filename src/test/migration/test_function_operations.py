"""Migrations of FUNCTIONS/PROCEDURES: CreateFunction / DropFunction / AlterFunction.

A routine (function/procedure) is OPAQUE SQL: its body (`body`) is the whole `CREATE OR REPLACE
FUNCTION ...`, raw and NOT portable (PL/pgSQL or SQL). There is no AddColumn/AlterColumn of a
routine: if it changes, it gets REPLACED whole (AlterFunction, via CREATE OR REPLACE). The reverse
of creating is `DROP FUNCTION name`. They are not auto-diffed (there is no "desired" metadata to
compare unless the user declares it): these operations are hand-written in a migration. The render
round-trips.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeRoutineInfo
from snakeorm.migration import (
    AlterFunction,
    CreateFunction,
    DropFunction,
    Migration,
    SchemaState,
    SnakeMigrationOperation,
    SnakeOperation,
    emit_create_function,
    emit_drop_function,
    render_migration,
)

_DIALECT = PostgresDialect()

_BODY = (
    "CREATE OR REPLACE FUNCTION calcular_nomina(emp integer) "
    "RETURNS TABLE(employee_id integer, gross numeric, net numeric) AS $$ "
    "SELECT emp, 2000::numeric, 1600::numeric $$ LANGUAGE sql"
)
_BODY_V2 = _BODY.replace("1600::numeric", "1700::numeric")


def _routine(name: str = "calcular_nomina", body: str = _BODY) -> SnakeRoutineInfo:
    """Minimal routine with the given body."""
    return SnakeRoutineInfo(name=name, body=body)


def test_create_function_up_and_down() -> None:
    """CreateFunction emits the body (CREATE OR REPLACE FUNCTION) and its reverse `DROP FUNCTION`."""
    op = CreateFunction(_routine())
    assert op.up_sql(_DIALECT) == [_BODY]
    assert op.down_sql(_DIALECT) == ['DROP FUNCTION "public"."calcular_nomina"']


def test_drop_function_up_and_down() -> None:
    """DropFunction emits `DROP FUNCTION` and its reverse recreates the routine with its old body."""
    op = DropFunction(_routine())
    assert op.up_sql(_DIALECT) == ['DROP FUNCTION "public"."calcular_nomina"']
    assert op.down_sql(_DIALECT) == [_BODY]


def test_alter_function_replaces_the_body() -> None:
    """AlterFunction emits the new body (CREATE OR REPLACE); its reverse restores the old one."""
    op = AlterFunction(_routine(body=_BODY), _routine(body=_BODY_V2))
    assert op.up_sql(_DIALECT) == [_BODY_V2]
    assert op.down_sql(_DIALECT) == [_BODY]


def test_function_operations_mutate_the_state() -> None:
    """apply_to_state adds/removes/replaces the routine in the abstract state."""
    state = SchemaState()
    CreateFunction(_routine()).apply_to_state(state)
    stored = state.get_routine("calcular_nomina")
    assert stored is not None and stored.body == _BODY

    AlterFunction(_routine(), _routine(body=_BODY_V2)).apply_to_state(state)
    replaced = state.get_routine("calcular_nomina")
    assert replaced is not None and replaced.body == _BODY_V2

    DropFunction(_routine(body=_BODY_V2)).apply_to_state(state)
    assert state.get_routine("calcular_nomina") is None


def test_emit_create_and_drop_standalone() -> None:
    """The standalone DDL emitters: create returns the raw body; drop builds the qualified DROP."""
    routine = _routine()
    assert emit_create_function(routine, _DIALECT) == _BODY
    assert (
        emit_drop_function(routine, _DIALECT)
        == 'DROP FUNCTION "public"."calcular_nomina"'
    )


def _reconstruct(source: str) -> list[SnakeMigrationOperation]:
    """Executes the generated code in a clean namespace and returns its operations."""
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated-migration>", "exec"), namespace)  # noqa: S102
    migration = namespace["migration"]
    assert isinstance(migration, Migration)
    return list(migration.operations)


def _sql(
    operations: Sequence[SnakeMigrationOperation],
) -> list[tuple[list[str], list[str]]]:
    """The SQL signature (up/down) of each operation: what the round-trip must preserve."""
    signatures: list[tuple[list[str], list[str]]] = []
    for op in operations:
        assert isinstance(op, SnakeOperation)
        signatures.append((op.up_sql(_DIALECT), op.down_sql(_DIALECT)))
    return signatures


def test_render_round_trip_of_function_operations() -> None:
    """Render of CreateFunction/AlterFunction/DropFunction: re-running gives the SAME up/down SQL."""
    operations: list[SnakeOperation] = [
        CreateFunction(_routine()),
        AlterFunction(_routine(body=_BODY), _routine(body=_BODY_V2)),
        DropFunction(_routine(name="other", body=_BODY)),
    ]
    source = render_migration("004", operations)
    assert "SnakeRoutineInfo(" in source
    assert _sql(_reconstruct(source)) == _sql(operations)
