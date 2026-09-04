"""A trigger belongs to a table, and the replayed state has to say so when the table moves.

`SchemaState` keeps its triggers in their own dictionary, keyed by `(table, name)` — it has to, since
in PostgreSQL the name alone is not unique. What it did NOT do is tie that dictionary to the table
dictionary, so a table could leave the state and its triggers stayed behind, naming something that
was no longer there.

That is a bug on its own, with nothing to do with rebuilding a table:

- after a `DropTable`, `state.triggers()` still listed the trigger, and `squash` — which re-emits
  everything the state holds — put a `CreateTrigger` in the collapsed migration for a table the same
  migration never creates. A fresh install would die on it.
- after a `RenameTable`, the trigger stayed keyed under the OLD name while the desired metadata
  names the new one, so the next `autodetect` emitted `DropTrigger` on a table that no longer exists
  AND `CreateTrigger` for a trigger the engine had already carried across on its own. Two statements,
  both wrong, in opposite directions.

All three engines take the trigger with the table: PostgreSQL because it hangs off the table's OID,
MySQL because a rename inside one database moves them, and SQLite because it rewrites the trigger's
own reference. So the state follows the engines, which is what the last test here measures by
FIRING the trigger after the rename rather than by looking it up in a catalogue.
"""

from __future__ import annotations

import pytest

from snakeorm import SQLiteDialect, SQLiteDriver
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTriggerEvent,
    SnakeTriggerInfo,
    SnakeTriggerTiming,
)
from snakeorm.migration import (
    CreateTable,
    CreateTrigger,
    DropTable,
    Migration,
    RenameTable,
    SchemaState,
    emit_create_table,
    emit_create_trigger,
    squash,
)

_VISITS, _POSTS = "tft_visits", "tft_posts"

_VISIT_ID = SnakeColumnInfo(name="id", python_type=int)
_POST_ID = SnakeColumnInfo(name="post_id", python_type=int)
_VISITS_TABLE = SnakeTableInfo(
    name=_VISITS,
    columns=(_VISIT_ID, _POST_ID),
    primary_key=SnakePrimaryKeyInfo(columns=(_VISIT_ID,)),
)
_POSTS_TABLE = SnakeTableInfo(
    name=_POSTS,
    columns=(_VISIT_ID, SnakeColumnInfo(name="visit_count", python_type=int)),
    primary_key=SnakePrimaryKeyInfo(columns=(_VISIT_ID,)),
)

_BUMP = SnakeTriggerInfo(
    name="tg_tft_bump_visit_count",
    table=_VISITS,
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.INSERT,),
    # The trailing `;` belongs to the BODY: SQLite wraps it in `BEGIN ... END` and its grammar
    # demands the inner statement be terminated. The body is opaque to the ORM, so it is written
    # here the way the engine reads it.
    body=f'UPDATE "{_POSTS}" SET "visit_count" = "visit_count" + 1 '
    f'WHERE "id" = NEW."post_id";',
)
_OTHER = SnakeTriggerInfo(
    name="tg_tft_other",
    table=_POSTS,
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.UPDATE,),
    body="SELECT 1;",
)


def _state_with_the_trigger() -> SchemaState:
    """The replayed state of a history that created both tables and both triggers."""
    state = SchemaState()
    for operation in (
        CreateTable(_VISITS_TABLE),
        CreateTable(_POSTS_TABLE),
        CreateTrigger(_BUMP),
        CreateTrigger(_OTHER),
    ):
        operation.apply_to_state(state)
    return state


def test_dropping_a_table_takes_its_triggers_out_of_the_state() -> None:
    """Verifies `DropTable` leaves no trigger behind naming the table it just removed.

    The engine does this by itself — a `DROP TABLE` takes its triggers with it on all three — so a
    state that kept them is the only thing in the system still believing in the trigger.
    """
    state = _state_with_the_trigger()

    DropTable(_VISITS_TABLE).apply_to_state(state)

    assert [trigger.name for trigger in state.triggers()] == [_OTHER.name]


def test_dropping_a_table_leaves_the_triggers_of_the_others_alone() -> None:
    """Verifies the purge is by TABLE and not a sweep: the other table's trigger survives."""
    state = _state_with_the_trigger()

    DropTable(_VISITS_TABLE).apply_to_state(state)

    assert state.triggers() == (_OTHER,)


def test_the_squash_of_a_dropped_table_does_not_recreate_its_trigger() -> None:
    """Verifies the collapsed history does not carry a `CreateTrigger` for a table nobody creates.

    This is what the state bug COST. A squash is the replayed final state emitted from nothing, so a
    trigger the state still held came out as an operation in the collapsed file — and the table it
    names is not created there, because the same history dropped it. A fresh install dies on that
    statement.
    """
    history = [
        Migration("0001_tft", (CreateTable(_VISITS_TABLE), CreateTrigger(_BUMP))),
        Migration("0002_tft", (DropTable(_VISITS_TABLE),)),
    ]

    collapsed = squash(history, version="0003_tft_squash")

    assert [type(operation).__name__ for operation in collapsed.operations] == []


def test_renaming_a_table_takes_its_triggers_with_it_in_the_state() -> None:
    """Verifies the trigger is re-keyed to the new name instead of being dropped or left behind.

    A rename keeps the trigger on all three engines, so a state that lost it would make the next
    `autodetect` emit a `CreateTrigger` for something that is already there, and a state that kept
    the old key would emit a `DropTrigger` on a table that is gone. The state has to say what the
    engines do.
    """
    state = _state_with_the_trigger()

    RenameTable(_VISITS_TABLE, new_name="tft_hits").apply_to_state(state)

    moved = {(trigger.table, trigger.name) for trigger in state.triggers()}
    assert moved == {("tft_hits", _BUMP.name), (_POSTS, _OTHER.name)}


def test_the_renamed_table_keeps_firing_its_trigger_on_sqlite() -> None:
    """Verifies the claim the state now encodes, by FIRING the trigger after the rename.

    Reading `sqlite_master` would only prove a row survived. What the state asserts is that the
    trigger still WORKS on the renamed table, and a recreated trigger that does not fire is the same
    lie with a different face.
    """
    dialect = SQLiteDialect()
    driver = SQLiteDriver.connect(":memory:")
    try:
        driver.execute(emit_create_table(_POSTS_TABLE, dialect), ())
        driver.execute(emit_create_table(_VISITS_TABLE, dialect), ())
        for statement in emit_create_trigger(_BUMP, dialect):
            driver.execute(statement, ())
        driver.execute(f'INSERT INTO "{_POSTS}" VALUES (1, 0)', ())

        driver.execute(RenameTable(_VISITS_TABLE, "tft_hits").up_sql(dialect)[0], ())
        driver.execute('INSERT INTO "tft_hits" VALUES (1, 1)', ())
        driver.commit()

        counted = driver.fetch_all(f'SELECT "visit_count" FROM "{_POSTS}"', ())
        assert counted == [(1,)], "the trigger did not fire after the rename"
    finally:
        driver.close()


def test_a_trigger_of_another_table_is_not_dragged_by_a_rename() -> None:
    """Verifies the rename moves only the triggers of the table it renames."""
    state = _state_with_the_trigger()

    RenameTable(_POSTS_TABLE, new_name="tft_articles").apply_to_state(state)

    assert (_VISITS, _BUMP.name) in {
        (trigger.table, trigger.name) for trigger in state.triggers()
    }


@pytest.mark.parametrize("name", [_VISITS, "tft_absent"], ids=str)
def test_removing_a_table_from_the_state_is_idempotent(name: str) -> None:
    """Verifies the purge does not care whether the table (or its triggers) were ever there."""
    state = _state_with_the_trigger()

    state.remove_table(name)
    state.remove_table(name)

    assert all(trigger.table != name for trigger in state.triggers())
