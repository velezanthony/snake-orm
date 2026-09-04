"""Tests of FKs in migrations (option B: at the end, as a separate AddForeignKey operation).

Uses the domain with relations Truck→Maker→Nation. The FKs are detected in the diff (with the
registry resolver) and come out AFTER the table operations, so as not to depend on the order.
"""

from __future__ import annotations

import dataclasses

import pytest

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.decorators import snake_table
from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.linker import snake_link
from snakeorm.migration import (
    AddForeignKey,
    CreateTable,
    Migration,
    RebuildTable,
    autodetect,
    diff_schema,
    emit_add_foreign_key,
    emit_drop_foreign_key,
    realize,
    replay,
)
from snakeorm.registry import registry
from test.scenarios.deep_domain import Maker, Truck


def _maker_rel() -> object:
    """The `maker` relation of Truck (after linking)."""
    snake_link()
    return snake_table(Truck).relationships[0]


def test_emit_add_foreign_key() -> None:
    """Verifies the ADD CONSTRAINT ... FOREIGN KEY ... REFERENCES with the resolved target."""
    snake_link()
    truck, maker = snake_table(Truck), snake_table(Maker)
    ddl = emit_add_foreign_key(truck, truck.relationships[0], maker, PostgresDialect())
    assert ddl == (
        'ALTER TABLE "public"."trucks" ADD CONSTRAINT "fk_trucks_maker" '
        'FOREIGN KEY ("maker_id") REFERENCES "public"."makers" ("id")'
    )


def test_emit_drop_foreign_key() -> None:
    """Verifies the DROP CONSTRAINT with the same deterministic name."""
    snake_link()
    truck = snake_table(Truck)
    ddl = emit_drop_foreign_key(truck, truck.relationships[0], PostgresDialect())
    assert ddl == 'ALTER TABLE "public"."trucks" DROP CONSTRAINT "fk_trucks_maker"'


def test_diff_detects_new_fk() -> None:
    """Verifies that a relation appearing on an EXISTING table produces a rebuild carrying it.

    The key is the table's only change here — the column it sits on is already there — and a key on
    a table that already exists is what SQLite can only add by remaking the table. `AddForeignKey`
    is still what a NEW table's key rides in on (see the test below) and what the twenty written
    migrations of the demos use.
    """
    snake_link()
    truck = snake_table(Truck)
    truck_without_fk = dataclasses.replace(truck, relationships=())
    operations = diff_schema([truck_without_fk], [truck], registry.table_by_name)
    assert len(operations) == 1
    rebuild = operations[0]
    assert isinstance(rebuild, RebuildTable)
    assert [rel.name for rel in rebuild.after.relationships] == ["maker"]
    assert rebuild.before.relationships == ()


def test_autodetect_puts_fk_after_create_table() -> None:
    """Verifies option B: first CreateTable, the FK AT THE END."""
    snake_link()
    operations = autodetect([], [snake_table(Truck)])
    assert isinstance(operations[0], CreateTable)
    assert isinstance(operations[-1], AddForeignKey)


def test_the_sqlite_refusal_names_the_rebuild_instead_of_hand_written_sql() -> None:
    """Verifies the FK refusal describes the ORM of today, which owns the rebuild it needs.

    It used to end with "On SQLite the only way is to rebuild the table ... and that is the user's
    call, not the ORM's: do it with a `RunSQL`". That sentence outlived its facts. `RebuildTable`
    exists, `realize` imports it in this very module, and `test_diff_detects_new_fk` above shows the
    diff collapsing a pure key change straight into one. A refusal that hands the reader a shovel
    while the ORM is holding the digger costs them the whole job.
    """
    snake_link()
    truck, maker = snake_table(Truck), snake_table(Maker)

    with pytest.raises(SnakeMigrationError) as error:
        realize([AddForeignKey(truck, truck.relationships[0], maker)], SQLiteDialect())

    message = str(error.value)
    assert "RebuildTable" in message
    assert "the user's call, not the ORM's" not in message
    assert "do it with a `RunSQL`" not in message


def test_the_sqlite_refusal_says_when_the_orm_does_it_and_when_it_does_not() -> None:
    """Verifies it explains WHY the reader is seeing this instead of the rebuild the diff writes.

    The collapse is conditional: `_is_a_pure_constraint_change` refuses to swallow a table that also
    moves a column, an index or its comment, because a rebuild that ate those would take
    `rename_suggestions` down with it. So arriving here means one of two things, and naming both is
    what turns the refusal into something the reader can act on rather than a fact about SQLite.
    """
    snake_link()
    truck, maker = snake_table(Truck), snake_table(Maker)

    with pytest.raises(SnakeMigrationError) as error:
        realize([AddForeignKey(truck, truck.relationships[0], maker)], SQLiteDialect())

    message = str(error.value)
    assert "ONLY change" in message
    assert "written by hand" in message


def test_the_rebuild_the_fk_refusal_prescribes_is_accepted_by_sqlite() -> None:
    """Verifies the prescribed operation passes the gate that just refused the `AddForeignKey`.

    Same mechanical check the CHECK pair gets: build the plan the sentence describes and hand it
    back to `realize` on the engine that refused. A prescription no gate accepts is the bug this
    whole pass is about.
    """
    snake_link()
    truck = snake_table(Truck)
    without_key = dataclasses.replace(truck, relationships=())
    rebuild = RebuildTable(without_key, truck)

    assert realize([rebuild], SQLiteDialect()) == [rebuild]


def test_replay_of_create_plus_fk_converges() -> None:
    """Replaying CreateTable + AddForeignKey leaves the FK in the state: it is not re-generated."""
    snake_link()
    truck, maker = snake_table(Truck), snake_table(Maker)
    history = [
        Migration(
            "001",
            (
                CreateTable(truck),
                AddForeignKey(truck, truck.relationships[0], maker),
            ),
        )
    ]
    state = replay(history)
    stored = state.get_table("trucks")
    assert stored is not None
    assert [rel.name for rel in stored.relationships] == ["maker"]
    # and the diff against the current metadata no longer proposes anything
    assert diff_schema(state.tables(), [truck], registry.table_by_name) == []
