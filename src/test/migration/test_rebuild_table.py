"""`RebuildTable`: the constraint change SQLite can only make by remaking the table, WRITTEN DOWN.

SQLite has no `ALTER TABLE ADD/DROP CONSTRAINT`, and that is permanent — no capability declares it
away. The standard answer is the table rebuild, and the decision this operation encodes is WHERE it
is allowed to happen: in the migration file, with a name, a `before` and an `after`, and not as a
side effect somebody discovers while applying an `AddCheck`.

    Postgres / MySQL   ALTER TABLE ... DROP CONSTRAINT / ADD CONSTRAINT      the minimal change
    SQLite             CREATE new, copy, DROP old, RENAME, recreate indexes  the whole rebuild

One operation, three spellings — the same shape `AlterView` already has, where an engine without
`CREATE OR REPLACE VIEW` gets a drop plus a create.

THE TWO SNAPSHOTS DIFFER ONLY IN CONSTRAINTS, and it is enforced rather than assumed. A `before` with
other columns than its `after` would apply on SQLite (the rebuild recreates from `after`) and NOT on
Postgres (whose minimal change emits no `ALTER COLUMN`), so the same file would leave two engines
with different schemas and neither would say a word. That is the exact shape of failure this
repository keeps paying for, so it is refused at construction time with the fields named.

THE FOREIGN KEYS, MEASURED, BECAUSE THE DESIGN'S ANSWER DOES NOT WORK AND NEITHER DOES ITS CHECK.

The design said the runner should wrap the rebuild in `PRAGMA foreign_keys = OFF` and finish with
`PRAGMA foreign_key_check`. Both halves were measured against SQLite 3.50 and both come back wrong:

1. `PRAGMA foreign_keys = OFF` is a documented NO-OP inside a transaction, and `SQLiteDriver` opens
   one lazily before the first statement — so the runner emits it, gets no error, and rebuilds with
   the keys armed. Django checks for exactly this and refuses to continue; measured here, the pragma
   is issued and `PRAGMA foreign_keys` still answers 1.
2. `PRAGMA foreign_key_check` and the COMMIT DISAGREE. Deferred violations live in a COUNTER, not in
   a recheck: after a rebuild that drops a table another key points at, `foreign_key_check` returns
   an empty list and the COMMIT still fails. A net whose answer contradicts the verdict is the kind
   this branch keeps deleting.

THE TRIGGERS TRAVEL IN THE PAYLOAD, and that is the second thing this operation carries that a
`SnakeTableInfo` does not. A `DROP TABLE` takes the table's triggers with it exactly as it takes its
indexes, and the indexes come back because `after.indexes` is inside the snapshot. Triggers are not:
`SnakeTableInfo` has no `triggers` field — they live in the REGISTRY and in the replayed
`SchemaState`, neither of which `up_sql(self, dialect)` can reach. So they ride in a third field,
`RebuildTable(before, after, triggers=...)`, filled by the only caller that has the state at hand,
and are recreated at the END for the same reason the indexes are: their names are still occupied
until the old table is gone.

The alternative shapes were rejected in writing: widening `up_sql` to take the state touches
twenty-eight operations and the Protocol for one case, and surrounding the rebuild with a
`DropTrigger` and a `CreateTrigger` in the file makes it say three loose things instead of one, with
no hint that the middle one takes the other two down with it.

So what the operation carries is `PRAGMA defer_foreign_keys = ON`, which IS designed to be set inside
a transaction and moves the verdict to the COMMIT. It is enough for a table nothing else points at,
which is the case the two blocked migrations of the demos are. It is NOT enough when another table's
key names the one being rebuilt: the counter goes up at the `DROP TABLE` and nothing brings it down,
so the COMMIT refuses and the migration rolls back. That is a loud, atomic failure and not a corrupt
schema — and the only way to lift it is `foreign_keys = OFF` on a connection with no transaction
open, which no method of the driver Protocol can reach today.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable, Iterator
from typing import cast

import pytest

from snakeorm import PsycopgDriver, PyMySQLDriver, SQLiteDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SnakeDialect, SQLiteDialect
from snakeorm.drivers.base import SnakeDriver
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
    SnakeTriggerEvent,
    SnakeTriggerInfo,
    SnakeTriggerTiming,
)
from snakeorm.migration import (
    CreateTable,
    CreateTrigger,
    Migration,
    RebuildTable,
    SchemaState,
    SnakeOperation,
    autodetect,
    diff_schema,
    emit_create_table,
    emit_create_trigger,
    realize,
    render_migration,
)
from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON
from test.scenarios.db import dsn

_MAKERS, _TRUCKS = "rbt_makers", "rbt_trucks"

_MAKER_ID = SnakeColumnInfo(name="id", python_type=int)
_MAKERS_TABLE = SnakeTableInfo(
    name=_MAKERS,
    columns=(_MAKER_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_MAKER_ID,)),
)

_TRUCK_ID = SnakeColumnInfo(name="id", python_type=int)
_AXLES = SnakeColumnInfo(name="axles", python_type=int)
_MAKER_FK = SnakeColumnInfo(name="maker_id", python_type=int, nullable=True)
_INDEX = SnakeIndexInfo(columns=("maker_id",), name="ix_rbt_trucks_maker")

_CHECK = SnakeCheckInfo(
    condition=SnakeExpr[int](path=("axles",)) > 0, name="ck_rbt_trucks_axles"
)
_RELATION = SnakeRelationshipInfo(
    name="maker",
    target="RbtMaker",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="RbtMaker", pairs=(("maker_id", "id"),)),
    target_table=f"public.{_MAKERS}",
)

_BEFORE = SnakeTableInfo(
    name=_TRUCKS,
    columns=(_TRUCK_ID, _AXLES, _MAKER_FK),
    primary_key=SnakePrimaryKeyInfo(columns=(_TRUCK_ID,)),
    indexes=(_INDEX,),
)
_AFTER = SnakeTableInfo(
    name=_TRUCKS,
    columns=(_TRUCK_ID, _AXLES, _MAKER_FK),
    primary_key=SnakePrimaryKeyInfo(columns=(_TRUCK_ID,)),
    indexes=(_INDEX,),
    checks=(_CHECK,),
    relationships=(_RELATION,),
)

_LOG = "rbt_log"
_TRIGGER = SnakeTriggerInfo(
    name="tg_rbt_trucks_logged",
    table=_TRUCKS,
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.INSERT,),
    # The trailing `;` belongs to the body: SQLite wraps it in `BEGIN ... END` and its grammar
    # demands the inner statement be terminated. The body is opaque to the ORM by design.
    body=f'INSERT INTO "{_LOG}" ("truck_id") VALUES (NEW."id");',
)
_FOREIGN_TRIGGER = SnakeTriggerInfo(
    name="tg_rbt_makers_logged",
    table=_MAKERS,
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.INSERT,),
    body="SELECT 1;",
)

_POSTGRES = PostgresDialect()


# --- What the two snapshots are allowed to say ---------------------------------------------


def test_it_refuses_a_pair_that_disagrees_about_the_columns() -> None:
    """Verifies a `before`/`after` differing outside the constraints is refused, with the field named.

    SQLite would apply the difference (it recreates the table from `after`) and Postgres would not
    (its minimal change emits no `ALTER COLUMN`), so the same migration file would leave the two
    engines holding different schemas in silence. That is the failure the operation exists to avoid,
    not one it is allowed to cause.
    """
    widened = SnakeTableInfo(
        name=_TRUCKS,
        columns=(_TRUCK_ID, _AXLES),
        primary_key=SnakePrimaryKeyInfo(columns=(_TRUCK_ID,)),
        indexes=(_INDEX,),
        checks=(_CHECK,),
    )

    with pytest.raises(SnakeMigrationError) as error:
        RebuildTable(_BEFORE, widened)

    assert "columns" in str(error.value)


def test_it_refuses_a_pair_that_disagrees_about_the_name() -> None:
    """Verifies a rebuild cannot smuggle in a rename: that is `RenameTable`, a different operation."""
    renamed = SnakeTableInfo(
        name="rbt_lorries",
        columns=_AFTER.columns,
        primary_key=_AFTER.primary_key,
        indexes=_AFTER.indexes,
        checks=_AFTER.checks,
        relationships=_AFTER.relationships,
    )

    with pytest.raises(SnakeMigrationError) as error:
        RebuildTable(_BEFORE, renamed)

    assert "RenameTable" in str(error.value)


def test_a_pair_differing_only_in_constraints_is_accepted() -> None:
    """Verifies the legal case builds: same columns, same indexes, different checks and keys."""
    operation = RebuildTable(_BEFORE, _AFTER)

    assert operation.before is _BEFORE
    assert operation.after is _AFTER


# --- How each engine spells it -------------------------------------------------------------


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect()],
    ids=lambda dialect: type(dialect).__name__,
)
def test_an_engine_with_add_constraint_only_emits_the_minimal_alter(
    dialect: SnakeDialect,
) -> None:
    """Verifies Postgres and MySQL get exactly the `ALTER`s `AddCheck`/`AddForeignKey` used to emit.

    No table is remade where the engine can change the constraint in place: the operation names the
    WORST case, and each dialect writes the least it needs.
    """
    statements = RebuildTable(_BEFORE, _AFTER).up_sql(dialect)

    assert all("ADD CONSTRAINT" in statement for statement in statements)
    assert len(statements) == 2, statements
    assert "FOREIGN KEY" in statements[0]
    assert "CHECK" in statements[1]
    assert not any("CREATE TABLE" in statement for statement in statements)


def test_the_minimal_alter_drops_before_it_adds() -> None:
    """Verifies the reverse direction drops the constraints before adding the previous ones back."""
    statements = RebuildTable(_BEFORE, _AFTER).down_sql(_POSTGRES)

    assert len(statements) == 2, statements
    assert all("DROP CONSTRAINT" in statement for statement in statements)


def test_sqlite_gets_the_whole_rebuild_in_order() -> None:
    """Verifies SQLite gets the documented recipe, in the one order that works.

    The new table is CREATED first and renamed into place last: renaming the old one out of the way
    instead would need `PRAGMA foreign_keys=OFF` (a rename rewrites the `REFERENCES` clauses of the
    other tables while the keys are armed), and that pragma is a no-op inside the transaction the
    driver has already opened.
    """
    statements = RebuildTable(_BEFORE, _AFTER).up_sql(SQLiteDialect())

    assert statements[0] == "PRAGMA defer_foreign_keys = ON"
    assert statements[1].startswith('CREATE TABLE "__snakeorm_new_rbt_trucks"')
    assert statements[2].startswith('INSERT INTO "__snakeorm_new_rbt_trucks"')
    assert statements[3] == 'DROP TABLE "rbt_trucks"'
    assert statements[4] == (
        'ALTER TABLE "__snakeorm_new_rbt_trucks" RENAME TO "rbt_trucks"'
    )
    assert statements[5].startswith('CREATE INDEX "ix_rbt_trucks_maker"')
    assert len(statements) == 6, statements


def test_the_rebuilt_table_carries_the_constraints_of_after() -> None:
    """Verifies the CHECK and the FK travel INSIDE the `CREATE TABLE`, which is SQLite's only window."""
    created = RebuildTable(_BEFORE, _AFTER).up_sql(SQLiteDialect())[1]

    assert '"ck_rbt_trucks_axles"' in created
    assert '"fk_rbt_trucks_maker"' in created
    assert 'REFERENCES "rbt_makers"' in created


def test_the_constraint_names_come_from_the_real_table_not_the_temporary_one() -> None:
    """Verifies the temporary name never reaches a constraint's identifier.

    SQLite stores a constraint's name inside the table's own DDL, so a name derived from
    `__snakeorm_new_...` would survive the rename and stay there forever — findable by nothing that
    the metadata can name.
    """
    created = RebuildTable(_BEFORE, _AFTER).up_sql(SQLiteDialect())[1]

    assert "ck___snakeorm_new" not in created
    assert "fk___snakeorm_new" not in created


def test_the_copy_names_every_column_instead_of_selecting_a_star() -> None:
    """Verifies the row copy lists its columns: `SELECT *` depends on an order nothing guarantees."""
    copy = RebuildTable(_BEFORE, _AFTER).up_sql(SQLiteDialect())[2]

    assert '"id", "axles", "maker_id"' in copy
    assert "*" not in copy


def test_down_is_the_same_rebuild_with_the_two_snapshots_swapped() -> None:
    """Verifies the reverse rebuilds towards `before`, so the round trip really returns."""
    down = RebuildTable(_BEFORE, _AFTER).down_sql(SQLiteDialect())
    mirror = RebuildTable(_AFTER, _BEFORE).up_sql(SQLiteDialect())

    assert down == mirror


# --- The plan and the abstract state -------------------------------------------------------


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect(), SQLiteDialect()],
    ids=lambda dialect: type(dialect).__name__,
)
def test_no_engine_refuses_it_in_the_plan(dialect: SnakeDialect) -> None:
    """Verifies `realize` lets it through on the three: it is the way OUT of the refusal, not one."""
    operation = RebuildTable(_BEFORE, _AFTER)

    assert realize([operation], dialect) == [operation]


def test_apply_to_state_leaves_the_after_snapshot_in_the_state() -> None:
    """Verifies the replayed state ends up holding exactly what the rebuild built."""
    state = SchemaState([_BEFORE])

    RebuildTable(_BEFORE, _AFTER).apply_to_state(state)

    rebuilt = state.get_table(_TRUCKS)
    assert rebuilt is not None
    assert rebuilt.checks == _AFTER.checks
    assert rebuilt.relationships == _AFTER.relationships
    assert rebuilt.columns == _AFTER.columns


def test_apply_to_state_is_quiet_over_a_table_the_state_never_had() -> None:
    """Verifies an unknown table is a no-op, like every other operation's `apply_to_state`."""
    state = SchemaState([_MAKERS_TABLE])

    RebuildTable(_BEFORE, _AFTER).apply_to_state(state)

    assert state.get_table(_TRUCKS) is None


def test_it_clears_the_way_for_a_column_drop_the_key_was_holding() -> None:
    """Verifies a rebuild that REMOVES a key counts as having removed it, for the next operation.

    `_guard_dropped_fk_column` refuses a `DropColumn` while a foreign key still holds the column,
    and it learns about the keys already gone by walking the plan. A rebuild that drops one is as
    good as a `DropForeignKey` there; not registering it would refuse a plan that is correct.
    """
    from snakeorm.migration import DropColumn, SnakeMigrationOperation

    plan: list[SnakeMigrationOperation] = [
        RebuildTable(_AFTER, _BEFORE),
        DropColumn(_BEFORE, _MAKER_FK),
    ]

    assert realize(plan, MySQLDialect()) == plan


def test_it_writes_itself_into_a_migration_file_that_rebuilds_it() -> None:
    """Verifies point 2 of the 4-point contract: the renderer knows it and imports it.

    The import is the half that fails LATE — a rendered name with no import line is a `NameError`
    raised while applying the migration, which is the worst possible moment to find out.
    """
    source = render_migration("0001_rebuild", [RebuildTable(_BEFORE, _AFTER)])

    assert "    RebuildTable," in source

    namespace: dict[str, object] = {}
    exec(compile(source, "0001_rebuild.py", "exec"), namespace)  # noqa: S102
    rebuilt = namespace["operations"]

    written = rebuilt[0]  # type: ignore[index]
    assert isinstance(written, RebuildTable)
    assert written.before == _BEFORE
    # The `after` is compared field by field except the CHECKs: their condition is an AST whose
    # nodes declare `eq=False`, so two identical conditions are never `==` — the same reason
    # `_diff_checks` fingerprints them by the SQL they emit instead of comparing the objects.
    assert written.after.columns == _AFTER.columns
    assert written.after.indexes == _AFTER.indexes
    assert written.after.relationships == _AFTER.relationships
    assert [check.name for check in written.after.checks] == ["ck_rbt_trucks_axles"]
    assert written.up_sql(_POSTGRES) == RebuildTable(_BEFORE, _AFTER).up_sql(_POSTGRES)


# --- What the diff does with it ------------------------------------------------------------


def _kinds(before: list[SnakeTableInfo], after: list[SnakeTableInfo]) -> list[str]:
    """The operation names the diff produces, which is what these tests are about."""
    return [type(operation).__name__ for operation in diff_schema(before, after)]


def test_a_check_appearing_on_an_existing_table_becomes_a_rebuild() -> None:
    """Verifies the change is WRITTEN as a rebuild, which is the whole point of the operation.

    Before this, the file said `AddCheck` and SQLite refused it at plan time with a message that
    explained the rebuild instead of doing it. Now the file says what happens.
    """
    assert _kinds([_BEFORE], [_AFTER]) == ["RebuildTable"]


def test_the_rebuild_the_diff_emits_converges() -> None:
    """Verifies replaying it leaves a state the next `autodetect` finds nothing to say about.

    A diff that does not converge regenerates the same migration for ever, and this is the shape of
    bug that ships as an empty file nobody reads twice.
    """
    operations = diff_schema([_BEFORE], [_AFTER])
    state = SchemaState([_BEFORE])
    for operation in operations:
        operation.apply_to_state(state)

    assert diff_schema(state.tables(), [_AFTER]) == []


def test_a_table_that_also_changes_a_column_keeps_the_old_operations() -> None:
    """Verifies the collapse only happens when the constraint change is the table's ONLY change.

    A rebuild that swallowed the column operations would take `rename_suggestions` with it: the
    warning that stops a `DropColumn` + `AddColumn` pair from silently deleting a column's data
    reads exactly those two operations out of the diff. Going quiet there, on tables that have
    constraints, is a net that fails open — and this repository has already deleted three of those.
    """
    grown = SnakeTableInfo(
        name=_TRUCKS,
        columns=(*_AFTER.columns, SnakeColumnInfo(name="wheels", python_type=int)),
        primary_key=_AFTER.primary_key,
        indexes=_AFTER.indexes,
        checks=_AFTER.checks,
        relationships=_AFTER.relationships,
    )

    assert "RebuildTable" not in _kinds([_BEFORE], [grown])
    assert "AddCheck" in _kinds([_BEFORE], [grown])


def test_a_new_table_is_still_created_whole() -> None:
    """Verifies a table born in this migration is a `CreateTable`: there is nothing to rebuild."""
    assert _kinds([], [_AFTER]) == ["CreateTable"]


# --- The triggers the DROP TABLE would take with it ----------------------------------------


def test_it_refuses_a_trigger_that_hangs_off_another_table() -> None:
    """Verifies the payload can only carry triggers of the table being rebuilt.

    A trigger of another table is not the rebuild's to recreate — nothing dropped it — so emitting a
    `CREATE TRIGGER` for it would fail on a name that is still taken. This one the operation CAN see
    on its own, so it is refused at construction like the mismatched snapshots.
    """
    with pytest.raises(SnakeMigrationError) as error:
        RebuildTable(_BEFORE, _AFTER, triggers=(_FOREIGN_TRIGGER,))

    assert _FOREIGN_TRIGGER.name in str(error.value)
    assert _MAKERS in str(error.value)


def test_sqlite_recreates_the_triggers_after_the_table_is_back() -> None:
    """Verifies the `CREATE TRIGGER` goes LAST, for the same reason the indexes do.

    Until the `DROP TABLE` runs, the old trigger still holds its name; creating the new one earlier
    would collide with it. And it has to come after the RENAME too, since it names the final table.
    """
    statements = RebuildTable(_BEFORE, _AFTER, triggers=(_TRIGGER,)).up_sql(
        SQLiteDialect()
    )

    assert statements[5].startswith('CREATE INDEX "ix_rbt_trucks_maker"')
    assert statements[6].startswith('CREATE TRIGGER "tg_rbt_trucks_logged"')
    assert 'ON "rbt_trucks"' in statements[6], (
        "it names the scratch table, not the real one"
    )
    assert len(statements) == 7, statements


def test_an_engine_that_alters_in_place_does_not_touch_the_triggers() -> None:
    """Verifies Postgres and MySQL get no trigger statement: nothing dropped them.

    The payload travels in the file all the same, because the file is engine-agnostic — it says what
    the table carries, and each dialect decides how much of it it has to rewrite.
    """
    for dialect in (PostgresDialect(), MySQLDialect()):
        statements = RebuildTable(_BEFORE, _AFTER, triggers=(_TRIGGER,)).up_sql(dialect)

        assert not any("TRIGGER" in statement for statement in statements), statements


def test_the_reverse_rebuild_recreates_the_triggers_too() -> None:
    """Verifies the `down` does not lose them: it drops the same table the `up` does."""
    statements = RebuildTable(_BEFORE, _AFTER, triggers=(_TRIGGER,)).down_sql(
        SQLiteDialect()
    )

    assert any(
        statement.startswith('CREATE TRIGGER "tg_rbt_trucks_logged"')
        for statement in statements
    ), statements


def test_a_rebuild_that_would_eat_a_trigger_is_refused_when_the_history_is_replayed() -> (
    None
):
    """Verifies the guard fires where the state IS known, NAMING the trigger that would be lost.

    The operation cannot see the triggers on its own: `up_sql` gets a dialect and nothing else, and
    the file is built at import time with no state anywhere near it. `apply_to_state` is the one
    place a `RebuildTable` of ANY provenance — autodetected or written by hand — meets a
    `SchemaState`, and every `makemigrations` and every `squash` replays the whole history through
    it. So that is where the question can be asked at all, and it is asked there.
    """
    state = SchemaState([_BEFORE])
    state.add_trigger(_TRIGGER)

    with pytest.raises(SnakeMigrationError) as error:
        RebuildTable(_BEFORE, _AFTER).apply_to_state(state)

    message = str(error.value)
    assert _TRIGGER.name in message
    assert "triggers=" in message


def test_apply_to_state_keeps_the_triggers_the_rebuild_recreates() -> None:
    """Verifies the state after the rebuild still holds the trigger, so the next diff finds nothing.

    Before this, `apply_to_state` touched tables only: the trigger was gone from the database and
    still in the state, so the next `makemigrations` had nothing to say about a trigger that no
    longer existed.
    """
    state = SchemaState([_BEFORE])
    state.add_trigger(_TRIGGER)

    RebuildTable(_BEFORE, _AFTER, triggers=(_TRIGGER,)).apply_to_state(state)

    assert state.triggers() == (_TRIGGER,)


def test_a_rebuild_over_a_table_with_no_triggers_needs_no_payload() -> None:
    """Verifies the guard only asks for what the state actually holds: no triggers, nothing to pass."""
    state = SchemaState([_BEFORE])

    RebuildTable(_BEFORE, _AFTER).apply_to_state(state)

    assert state.triggers() == ()


def test_the_diff_puts_the_tables_triggers_into_the_rebuild_it_emits() -> None:
    """Verifies the caller with the triggers at hand hands them over: nobody has to remember.

    It is the half that makes the guard above never fire in the normal path. `diff_schema` receives
    the state's triggers in the SAME call that produces the operation, so an autodetected rebuild
    cannot come out headless.
    """
    operations = diff_schema([_BEFORE], [_AFTER], triggers=[_TRIGGER, _FOREIGN_TRIGGER])

    assert len(operations) == 1
    rebuild = operations[0]
    assert isinstance(rebuild, RebuildTable)
    assert rebuild.triggers == (_TRIGGER,), "only the triggers of the rebuilt table"


def test_autodetect_fills_the_rebuild_from_the_replayed_history() -> None:
    """Verifies the whole path: history with a trigger -> a rebuild that carries it.

    `autodetect` is the caller that has the replayed `SchemaState`, which is the only place in the
    system that knows a trigger exists at all — `SnakeTableInfo` has no field for one.
    """
    checked = dataclasses.replace(_BEFORE, checks=(_CHECK,))
    history = [
        Migration("0001_rbt", (CreateTable(_BEFORE), CreateTrigger(_TRIGGER))),
    ]

    operations = autodetect(history, [checked], routines=[], triggers=[_TRIGGER])

    assert [type(operation).__name__ for operation in operations] == ["RebuildTable"]
    rebuild = operations[0]
    assert isinstance(rebuild, RebuildTable)
    assert rebuild.triggers == (_TRIGGER,)


def test_the_rebuild_the_diff_emits_still_converges_with_a_trigger_on_the_table() -> (
    None
):
    """Verifies replaying the generated migration leaves a state the next `autodetect` accepts.

    A diff that does not converge regenerates the same migration for ever — and here the failure
    mode is worse, because the operation that does not converge is the one that raises.
    """
    state = SchemaState([_BEFORE])
    state.add_trigger(_TRIGGER)

    for operation in diff_schema([_BEFORE], [_AFTER], triggers=[_TRIGGER]):
        operation.apply_to_state(state)

    assert diff_schema(state.tables(), [_AFTER], triggers=list(state.triggers())) == []


def test_the_triggers_survive_the_round_trip_through_the_migration_file() -> None:
    """Verifies point 2 of the n: what the renderer cannot write does not exist.

    A field captured by the operation and dropped by the renderer is the exact failure `db_comment`
    already paid for: metadata that is collected, stored and never reaches the file.
    """
    source = render_migration(
        "0001_rebuild", [RebuildTable(_BEFORE, _AFTER, triggers=(_TRIGGER,))]
    )

    assert "SnakeTriggerInfo" in source

    namespace: dict[str, object] = {}
    exec(compile(source, "0001_rebuild.py", "exec"), namespace)  # noqa: S102
    written = namespace["operations"][0]  # type: ignore[index]

    assert isinstance(written, RebuildTable)
    assert written.triggers == (_TRIGGER,)


def test_a_rebuild_with_no_triggers_writes_no_empty_field() -> None:
    """Verifies the file stays as it was when there is nothing to carry: no `triggers=()` noise."""
    source = render_migration("0001_rebuild", [RebuildTable(_BEFORE, _AFTER)])

    assert "triggers=" not in source


# --- Applied against the real servers ------------------------------------------------------


def _ref(name: str, dialect: SnakeDialect) -> str:
    """The table as this engine spells it in a statement written by hand in this file."""
    if dialect.supports_schemas:
        return f"{dialect.quote_ident('public')}.{dialect.quote_ident(name)}"
    return dialect.quote_ident(name)


def _create(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Parent and child in their `before` shape, with two rows the rebuild has to keep."""
    driver.execute(emit_create_table(_MAKERS_TABLE, dialect), ())
    driver.execute(emit_create_table(_BEFORE, dialect), ())
    from snakeorm.migration import emit_create_index

    driver.execute(emit_create_index(_BEFORE, _INDEX, dialect), ())
    driver.execute(
        f"INSERT INTO {_ref(_MAKERS, dialect)} ({dialect.quote_ident('id')}) VALUES (1)",
        (),
    )
    columns = ", ".join(
        dialect.quote_ident(name) for name in ("id", "axles", "maker_id")
    )
    for row in ((1, 2, 1), (2, 3, 1)):
        driver.execute(
            f"INSERT INTO {_ref(_TRUCKS, dialect)} ({columns}) VALUES "
            f"({row[0]}, {row[1]}, {row[2]})",
            (),
        )
    driver.commit()


def _drop_probes(driver: SnakeDriver, template: str) -> None:
    """Child first, then the parent, plus the temporary name a failed rebuild could leave."""
    for table in ("__snakeorm_new_rbt_trucks", _TRUCKS, _MAKERS):
        driver.execute(template.format(table), ())
    driver.commit()


@pytest.fixture
def postgres() -> Iterator[PsycopgDriver]:
    """Real Postgres with the probe tables clean before and after."""
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    _drop_probes(connection, 'DROP TABLE IF EXISTS "{}" CASCADE')
    try:
        yield connection
    finally:
        _drop_probes(connection, 'DROP TABLE IF EXISTS "{}" CASCADE')
        connection.close()


@pytest.fixture
def mariadb() -> Iterator[PyMySQLDriver]:
    """Real MySQL/MariaDB with the probe tables clean before and after."""
    host = os.environ.get("MYSQL_HOST")
    if not host:
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    import pymysql

    try:
        connection = PyMySQLDriver.connect(
            host=host,
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DB", "snakeorm_db"),
        )
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")
    _drop_probes(connection, "DROP TABLE IF EXISTS `{}`")
    try:
        yield connection
    finally:
        _drop_probes(connection, "DROP TABLE IF EXISTS `{}`")
        connection.close()


def _postgres_constraints(driver: SnakeDriver) -> set[str]:
    """The CHECK and FOREIGN KEY constraints of the probe table, out of Postgres's catalogue."""
    rows = driver.fetch_all(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = %s::regclass AND contype IN ('c', 'f')",
        (_TRUCKS,),
    )
    return {str(row[0]) for row in rows}


def _mariadb_constraints(driver: SnakeDriver) -> set[str]:
    """The same answer out of MariaDB's `information_schema`."""
    rows = driver.fetch_all(
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_schema = DATABASE() AND table_name = %s "
        "AND constraint_type IN ('CHECK', 'FOREIGN KEY')",
        (_TRUCKS,),
    )
    return {str(row[0]) for row in rows}


def _sqlite_constraints(driver: SnakeDriver) -> set[str]:
    """SQLite keeps a constraint's name inside the table's DDL, so the DDL is the catalogue."""
    rows = driver.fetch_all(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (_TRUCKS,)
    )
    ddl = str(rows[0][0]) if rows else ""
    return {
        name for name in ("ck_rbt_trucks_axles", "fk_rbt_trucks_maker") if name in ddl
    }


def _rows(driver: SnakeDriver, dialect: SnakeDialect) -> list[tuple[object, ...]]:
    """The probe table's rows, ordered, which is what a rebuild must not lose."""
    return list(
        driver.fetch_all(
            f"SELECT {dialect.quote_ident('id')}, {dialect.quote_ident('axles')} "
            f"FROM {_ref(_TRUCKS, dialect)} ORDER BY {dialect.quote_ident('id')}",
            (),
        )
    )


def _round_trip(
    driver: SnakeDriver,
    dialect: SnakeDialect,
    read: Callable[[SnakeDriver], set[str]],
) -> None:
    """Create, rebuild, read the real catalogue, revert, read it again — rows counted throughout."""
    _create(driver, dialect)
    assert read(driver) == set()
    assert _rows(driver, dialect) == [(1, 2), (2, 3)]

    operation = RebuildTable(_BEFORE, _AFTER)
    for statement in operation.up_sql(dialect):
        driver.execute(statement, ())
    driver.commit()

    assert read(driver) == {"ck_rbt_trucks_axles", "fk_rbt_trucks_maker"}, (
        "the constraints the migration declares are not in the database"
    )
    assert _rows(driver, dialect) == [(1, 2), (2, 3)], "the rebuild lost rows"

    # The CHECK is ENFORCED, not merely present in a catalogue. The message is read because
    # `pytest.raises(Exception)` would also be satisfied by a typo in this file's own SQL.
    with pytest.raises(Exception) as error:  # noqa: B017 - one integrity error per engine
        columns = ", ".join(
            dialect.quote_ident(name) for name in ("id", "axles", "maker_id")
        )
        driver.execute(
            f"INSERT INTO {_ref(_TRUCKS, dialect)} ({columns}) VALUES (3, 0, 1)", ()
        )
        driver.commit()
    assert (
        "check" in str(error.value).lower() or "constraint" in str(error.value).lower()
    )
    driver.rollback()

    for statement in operation.down_sql(dialect):
        driver.execute(statement, ())
    driver.commit()

    assert read(driver) == set(), "the reverse left a constraint behind"
    assert _rows(driver, dialect) == [(1, 2), (2, 3)], "the reverse lost rows"


@pytest.mark.integration
def test_it_applies_and_reverts_on_a_real_postgres(postgres: PsycopgDriver) -> None:
    """Verifies the whole cycle on Postgres, with the constraints read from `pg_constraint`."""
    _round_trip(postgres, _POSTGRES, _postgres_constraints)


@pytest.mark.integration
def test_it_applies_and_reverts_on_a_real_mariadb(mariadb: PyMySQLDriver) -> None:
    """Verifies the same cycle on MariaDB, which names its constraints in `information_schema`."""
    _round_trip(mariadb, MySQLDialect(), _mariadb_constraints)


def _sqlite() -> SQLiteDriver:
    """A SQLite database with the foreign keys ARMED, which is where the rebuild has to survive."""
    driver = SQLiteDriver.connect(":memory:")
    driver.execute("PRAGMA foreign_keys = ON", ())
    return driver


def test_it_applies_and_reverts_on_sqlite() -> None:
    """Verifies the same cycle on the engine the operation exists for.

    No server and no `integration` mark: SQLite is a file, so this one runs everywhere.
    """
    driver = _sqlite()
    try:
        _round_trip(driver, SQLiteDialect(), _sqlite_constraints)
    finally:
        driver.close()


def test_the_declared_index_survives_the_rebuild_on_sqlite() -> None:
    """Verifies the index the model declares is back after the table it lived on was dropped.

    A `DROP TABLE` takes its indexes with it. An index the MODEL does not declare does not come
    back, and that is not written down as a limit: it is drift, and drift is caught by reading the
    database, which is what `drift` does.
    """
    driver = _sqlite()
    dialect = SQLiteDialect()
    try:
        _create(driver, dialect)
        for statement in RebuildTable(_BEFORE, _AFTER).up_sql(dialect):
            driver.execute(statement, ())
        driver.commit()

        rows = driver.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?",
            (_TRUCKS,),
        )
        assert "ix_rbt_trucks_maker" in {str(row[0]) for row in rows}
    finally:
        driver.close()


def _trigger_fired_times(driver: SnakeDriver) -> int:
    """How many rows the trigger has written into its log: whether it WORKS, not whether it exists."""
    rows = driver.fetch_all(f'SELECT count(*) FROM "{_LOG}"', ())
    return int(str(rows[0][0]))


def test_the_trigger_still_fires_after_the_rebuild_on_sqlite() -> None:
    """Verifies the trigger the `DROP TABLE` took with it is BACK AND WORKING, which is the point.

    Reading `sqlite_master` would only prove a row exists. What the operation promises is that the
    rule still holds, and a recreated trigger that does not fire is the same silence wearing a
    catalogue entry. So the count is taken before the rebuild, and again after inserting through the
    rebuilt table.

    The rebuild itself does not fire it: the rows are copied INTO the scratch table, and the trigger
    hangs off the real one.
    """
    driver = _sqlite()
    dialect = SQLiteDialect()
    try:
        _create(driver, dialect)
        driver.execute(
            f'CREATE TABLE "{_LOG}" ("truck_id" INTEGER NOT NULL)',
            (),
        )
        for statement in emit_create_trigger(_TRIGGER, dialect):
            driver.execute(statement, ())
        driver.execute(
            f'INSERT INTO {_ref(_TRUCKS, dialect)} ("id", "axles", "maker_id") '
            f"VALUES (7, 4, 1)",
            (),
        )
        driver.commit()
        assert _trigger_fired_times(driver) == 1, "the probe trigger never worked"

        for statement in RebuildTable(_BEFORE, _AFTER, triggers=(_TRIGGER,)).up_sql(
            dialect
        ):
            driver.execute(statement, ())
        driver.commit()

        assert _trigger_fired_times(driver) == 1, "the row copy fired the trigger"
        driver.execute(
            f'INSERT INTO {_ref(_TRUCKS, dialect)} ("id", "axles", "maker_id") '
            f"VALUES (8, 4, 1)",
            (),
        )
        driver.commit()

        assert _trigger_fired_times(driver) == 2, (
            "the rebuild dropped the trigger and it did not come back"
        )
    finally:
        driver.close()


def test_the_whole_chain_from_the_model_change_to_the_firing_trigger_on_sqlite() -> (
    None
):
    """Verifies the four points END TO END, with nobody handing the operation its triggers by hand.

    A CHECK appears on a table that has a trigger. `autodetect` replays the history, sees a pure
    constraint change and emits the rebuild; the renderer writes the file; the file is imported back;
    the SQL is applied to a real SQLite; and the trigger fires afterwards. Every one of those steps
    was a place the trigger could have been dropped, and only the last one can tell.
    """
    checked = dataclasses.replace(_BEFORE, checks=(_CHECK,))
    history = [Migration("0001_rbt", (CreateTable(_BEFORE), CreateTrigger(_TRIGGER)))]

    source = render_migration(
        "0002_rbt", autodetect(history, [checked], routines=[], triggers=[_TRIGGER])
    )
    namespace: dict[str, object] = {}
    exec(compile(source, "0002_rbt.py", "exec"), namespace)  # noqa: S102
    written = cast("list[SnakeOperation]", namespace["operations"])

    driver = _sqlite()
    dialect = SQLiteDialect()
    try:
        _create(driver, dialect)
        driver.execute(f'CREATE TABLE "{_LOG}" ("truck_id" INTEGER NOT NULL)', ())
        for statement in emit_create_trigger(_TRIGGER, dialect):
            driver.execute(statement, ())
        driver.commit()

        for operation in written:
            for statement in operation.up_sql(dialect):
                driver.execute(statement, ())
        driver.execute(
            f'INSERT INTO {_ref(_TRUCKS, dialect)} ("id", "axles", "maker_id") '
            f"VALUES (11, 4, 1)",
            (),
        )
        driver.commit()

        assert _trigger_fired_times(driver) == 1, (
            "the migration the ORM generated by itself lost the trigger"
        )
    finally:
        driver.close()


def test_without_the_payload_the_rebuild_would_have_lost_the_trigger_on_sqlite() -> (
    None
):
    """Verifies the loss this phase exists to stop is REAL, by letting it happen once.

    The guard lives in `apply_to_state`, so a rebuild built without its triggers still emits SQL —
    and this is what that SQL does to the database. Without this test the payload would be a field
    whose reason for existing is only asserted in prose.
    """
    driver = _sqlite()
    dialect = SQLiteDialect()
    try:
        _create(driver, dialect)
        driver.execute(f'CREATE TABLE "{_LOG}" ("truck_id" INTEGER NOT NULL)', ())
        for statement in emit_create_trigger(_TRIGGER, dialect):
            driver.execute(statement, ())
        driver.commit()

        for statement in RebuildTable(_BEFORE, _AFTER).up_sql(dialect):
            driver.execute(statement, ())
        driver.execute(
            f'INSERT INTO {_ref(_TRUCKS, dialect)} ("id", "axles", "maker_id") '
            f"VALUES (9, 4, 1)",
            (),
        )
        driver.commit()

        assert _trigger_fired_times(driver) == 0, (
            "the trigger survived a rebuild that never recreated it, so this file measures nothing"
        )
    finally:
        driver.close()


def test_a_key_from_another_table_stops_the_rebuild_instead_of_corrupting_it() -> None:
    """Verifies the case deferral cannot cover fails LOUDLY, and pins the two measurements.

    SQLite counts deferred violations rather than rechecking them. The `DROP TABLE` in the middle of
    the rebuild orphans every row of every table whose key names it, the counter goes up, and putting
    the table back three statements later does not bring it down: the COMMIT refuses, the whole
    migration rolls back, and `PRAGMA foreign_key_check` — the net the design asked for — reports the
    database CLEAN while that happens.

    Both halves are asserted here rather than described somewhere, because the day SQLite starts
    rechecking at COMMIT this test fails and says so.
    """
    driver = _sqlite()
    dialect = SQLiteDialect()
    try:
        _create(driver, dialect)
        driver.execute(
            'CREATE TABLE "rbt_trailers" ("id" INTEGER NOT NULL PRIMARY KEY, '
            '"truck_id" INTEGER REFERENCES "rbt_trucks" ("id"))',
            (),
        )
        driver.execute('INSERT INTO "rbt_trailers" VALUES (1, 1)', ())
        driver.commit()

        for statement in RebuildTable(_BEFORE, _AFTER).up_sql(dialect):
            driver.execute(statement, ())

        assert driver.fetch_all("PRAGMA foreign_key_check", ()) == [], (
            "the check the design asked for reports clean, which is why it is not the net"
        )
        with pytest.raises(Exception) as error:  # noqa: B017 - integrity error
            driver.commit()
        assert "foreign key" in str(error.value).lower()
    finally:
        driver.close()


def test_the_runner_explains_a_rebuild_the_deferred_keys_could_not_cover() -> None:
    """Verifies the migration that hits that wall gets a message and not just the engine's four words.

    `FOREIGN KEY constraint failed` on a `COMMIT` names nothing: not the table, not the rebuild, not
    the reason a check run one statement earlier said the database was fine. In a project whose
    doctrine is that the message IS the product, that is the half worth writing.
    """
    from snakeorm.migration import Migration, MigrationRunner

    driver = _sqlite()
    dialect = SQLiteDialect()
    try:
        _create(driver, dialect)
        driver.execute(
            'CREATE TABLE "rbt_trailers" ("id" INTEGER NOT NULL PRIMARY KEY, '
            '"truck_id" INTEGER REFERENCES "rbt_trucks" ("id"))',
            (),
        )
        driver.execute('INSERT INTO "rbt_trailers" VALUES (1, 1)', ())
        driver.commit()

        runner = MigrationRunner(driver, dialect)
        migration = Migration(
            version="0001_rebuild", operations=(RebuildTable(_BEFORE, _AFTER),)
        )
        with pytest.raises(SnakeMigrationError) as error:
            runner.apply([migration])

        message = str(error.value)
        assert _TRUCKS in message
        assert "foreign_keys" in message
        assert "foreign_key_check" in message
    finally:
        driver.close()


def test_a_broken_key_makes_the_rebuild_fail_instead_of_passing_quietly() -> None:
    """Verifies integrity is not sacrificed to get the rebuild through: the COMMIT refuses.

    The design asked for a `PRAGMA foreign_key_check` raised as an ERROR. Deferring the keys gets
    the same verdict from the engine itself and one statement earlier, which matters because
    `foreign_key_check` returns ROWS and a migration operation emits statements — a check whose
    answer nobody reads is the shape of net this repository keeps deleting.
    """
    driver = _sqlite()
    dialect = SQLiteDialect()
    try:
        _create(driver, dialect)
        # An orphan row put in while the keys are deferred: the parent it names does not exist.
        driver.execute("PRAGMA defer_foreign_keys = ON", ())
        driver.execute(
            'INSERT INTO "rbt_trucks" ("id", "axles", "maker_id") VALUES (9, 1, 404)',
            (),
        )
        for statement in RebuildTable(_BEFORE, _AFTER).up_sql(dialect):
            driver.execute(statement, ())

        with pytest.raises(Exception) as error:  # noqa: B017 - integrity error
            driver.commit()
        assert "foreign key" in str(error.value).lower()
    finally:
        driver.close()
