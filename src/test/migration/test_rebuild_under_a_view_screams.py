"""A rebuild under a VIEW: the ORM does not fix it, it SAYS it. Measured on SQLite.

WHAT BREAKS, AND IT IS NOT THE `DROP TABLE`. `_remake_table` finishes with
`ALTER TABLE ... RENAME TO`, and on SQLite a rename REPARSES THE WHOLE SCHEMA — every view included.
Between the `DROP TABLE` and the `RENAME` the old table is gone and the new one still wears its
scratch name, so a view whose SELECT names that table is unparseable at exactly that instant. The
statement that fails is the RENAME, and it fails with `error in view <v>: no such table: main.<t>`.
Measured on SQLite 3.50; there is no pragma that makes it go away inside a transaction.

ONLY THE VIEWS THAT READ THE REBUILT TABLE BREAK IT, and that is measured here too rather than
assumed: a view over ANOTHER table survives the same rename untouched. That measurement is what
draws the line this file exists to hold.

AND THE ORM CANNOT TELL WHICH ONES THOSE ARE. `SnakeTableInfo` has no field naming the tables a view
reads; `depends_on` is view->view only and is refused for tables on purpose (`decorators/view.py`);
and most views in this repository are declared with `sql=`, raw text. Pulling a `FROM` out of SQL
text would be a heuristic that fails open while its name claimed otherwise, which is the exact shape
of the three language tests this repository deleted.

SO THE PAYLOAD IS NOT THE ANSWER, AND THE MESSAGE IS. `RebuildTable` used to carry a `views=` tuple
with a guard demanding EVERY standing view, and the price of "every" was immediate: a rebuild of
`tags` in one app had to declare `low_stock`, a view of another app over another table that cannot
possibly break. The triggers stay in the payload because `SnakeTriggerInfo` HAS a `.table`, so "the
triggers of this table" is a fact the state answers; a view has no such field and it would be a
guess. The line is where the data ends.

What is left is this project's doctrine — the ORM screams, it does not repair on its own: the engine
refuses the rebuild, the migration rolls back whole, and `explain_rebuild_failure` turns the engine's
line into the two operations to write. The person puts their `DropView` before and their `CreateView`
after, which is what `frameworks/shared/migrations/inventory/0004_on_hand_and_available_view.py`
already does by hand.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterator
from typing import cast

import pytest

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import SQLiteDialect
from snakeorm.drivers import SQLiteDriver
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTableKind,
)
from snakeorm.migration import (
    CreateView,
    DropView,
    Migration,
    MigrationRunner,
    RebuildTable,
    SnakeOperation,
    diff_schema,
    realize,
)
from snakeorm.migration.runner import explain_rebuild_failure

_ID = SnakeColumnInfo(name="id", python_type=int, attr_name="id")
_QTY = SnakeColumnInfo(name="qty", python_type=int, attr_name="qty")

_BEFORE = SnakeTableInfo(
    name="rbv_stock",
    columns=(_ID, _QTY),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    checks=(
        SnakeCheckInfo(
            name="ck_rbv_stock_qty", condition=SnakeExpr[int](path=("qty",)) >= 0
        ),
    ),
)
_AFTER = dataclasses.replace(
    _BEFORE,
    checks=(
        SnakeCheckInfo(
            name="ck_rbv_stock_qty", condition=SnakeExpr[int](path=("qty",)) >= 1
        ),
    ),
)


def _view(name: str, definition: str) -> SnakeTableInfo:
    """A minimal raw-SQL view, which is the kind the ORM cannot read the `FROM` out of."""
    return SnakeTableInfo(
        name=name,
        columns=(_ID, _QTY),
        primary_key=SnakePrimaryKeyInfo(columns=()),
        kind=SnakeTableKind.VIEW,
        view_definition=definition,
    )


_LOW_STOCK = _view("rbv_low_stock", "SELECT id, qty FROM rbv_stock WHERE qty < 10")


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    """A real SQLite database holding the table, a row and the view standing over it."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        'CREATE TABLE "rbv_stock" ("id" INTEGER NOT NULL, "qty" INTEGER NOT NULL, '
        'PRIMARY KEY ("id"), CONSTRAINT "ck_rbv_stock_qty" CHECK ("qty" >= 0))'
    )
    conn.execute(
        'CREATE VIEW "rbv_low_stock" AS SELECT id, qty FROM rbv_stock WHERE qty < 10'
    )
    conn.execute('INSERT INTO "rbv_stock" ("id", "qty") VALUES (1, 5)')
    conn.commit()
    yield conn
    conn.close()


# --- The measurement the whole decision rests on ---------------------------------------------


def test_sqlite_refuses_the_rebuild_when_a_view_reads_the_table(
    connection: sqlite3.Connection,
) -> None:
    """Verifies the failure is REAL and lands on the RENAME, not on the `DROP TABLE`.

    Without this the rest of the file would be a rule nobody had seen break. The statements are
    exactly the ones the emitter writes for this engine.
    """
    statements = RebuildTable(_BEFORE, _AFTER).up_sql(SQLiteDialect())

    connection.execute("BEGIN")
    with pytest.raises(sqlite3.OperationalError) as error:
        for statement in statements:
            connection.execute(statement)

    assert "error in view rbv_low_stock" in str(error.value)


def test_a_view_over_another_table_survives_the_same_rename(
    connection: sqlite3.Connection,
) -> None:
    """Verifies only the views that READ the rebuilt table break it — the line, measured.

    This is why carrying every standing view in the payload was wrong: a view of another app over
    another table cannot fail here, and demanding it made an unrelated migration answer for it.
    """
    connection.execute(
        'CREATE TABLE "rbv_other" ("id" INTEGER NOT NULL, "qty" INTEGER NOT NULL)'
    )
    connection.execute('DROP VIEW "rbv_low_stock"')
    connection.execute(
        'CREATE VIEW "rbv_elsewhere" AS SELECT id, qty FROM rbv_other WHERE qty < 10'
    )
    connection.commit()

    connection.execute("BEGIN")
    for statement in RebuildTable(_BEFORE, _AFTER).up_sql(SQLiteDialect()):
        connection.execute(statement)
    connection.execute("COMMIT")

    assert connection.execute('SELECT "qty" FROM "rbv_stock"').fetchall() == [(5,)]


# --- What the generator writes, and what it deliberately does not ----------------------------


def test_the_generator_writes_the_rebuild_bare_under_a_standing_view() -> None:
    """Verifies the diff emits the rebuild alone, with no view operation wrapped around it.

    It is a decision and not a gap: sequencing a `DropView` here would mean knowing which view reads
    the table, and nothing in the metadata says that. The plan the generator writes is the plan the
    engine judges, and the ORM explains the verdict.
    """
    plan = diff_schema([_BEFORE, _LOW_STOCK], [_AFTER, _LOW_STOCK])

    assert [type(operation).__name__ for operation in plan] == ["RebuildTable"]


def test_the_rebuild_operation_has_no_view_payload_to_carry() -> None:
    """Verifies `RebuildTable` exposes triggers and NOT views, which is the fact/guess line.

    A `SnakeTriggerInfo` has a `.table`, so the state can answer "the triggers of this one". No
    field anywhere says which tables a view reads, so there is nothing honest to fill a `views=` in
    with — and a field that can only be filled by guessing should not exist.
    """
    operation = RebuildTable(_BEFORE, _AFTER)

    assert hasattr(operation, "triggers")
    assert not hasattr(operation, "views")


# --- The net: the engine's line becomes the two operations to write ---------------------------


def test_the_runner_translates_the_engines_line_into_the_operations_to_write() -> None:
    """Verifies a migration that hits this against REAL SQLite gets the ORM's sentence, not the engine's.

    The whole chain: a plan, a `MigrationRunner`, a database with the view standing. The raw line
    names a table the reader can see with their own eyes and a view nobody touched, which sends them
    to the wrong place. What comes out instead names the rebuilt table and the two operations.
    """
    driver = SQLiteDriver.connect(":memory:")
    try:
        driver.execute(
            'CREATE TABLE "rbv_stock" ("id" INTEGER NOT NULL, "qty" INTEGER NOT NULL, '
            'PRIMARY KEY ("id"), CONSTRAINT "ck_rbv_stock_qty" CHECK ("qty" >= 0))',
            (),
        )
        driver.execute(
            'CREATE VIEW "rbv_low_stock" AS SELECT id, qty FROM rbv_stock WHERE qty < 10',
            (),
        )
        driver.execute('INSERT INTO "rbv_stock" ("id", "qty") VALUES (1, 5)', ())
        driver.commit()

        runner = MigrationRunner(driver, SQLiteDialect())
        migration = Migration(
            version="0001_rebuild_under_a_view",
            operations=(RebuildTable(_BEFORE, _AFTER),),
        )
        with pytest.raises(SnakeMigrationError) as error:
            runner.apply([migration])

        message = str(error.value)
        assert "rbv_stock" in message
        assert "DropView" in message
        assert "CreateView" in message
        assert "views=" not in message
        assert "Nothing was applied" in message
    finally:
        driver.close()


def test_the_translation_says_the_generator_cannot_write_those_two_operations() -> None:
    """Verifies the message does not blame a hand-written file: an autodetected plan lands here too.

    It used to say "an autodetected migration is given them already, so this one was written by
    hand". That stopped being true the day the payload went away, and a message that misattributes
    the cause sends the reader looking for a file that does not exist.
    """
    plan = [RebuildTable(_BEFORE, _AFTER)]
    error = sqlite3.OperationalError(
        "error in view rbv_low_stock: no such table: main.rbv_stock"
    )

    explained = explain_rebuild_failure(plan, SQLiteDialect(), error)

    assert explained is not None
    assert "cannot" in str(explained)
    assert "sql=" in str(explained)


def test_a_failure_that_is_neither_a_key_nor_a_view_is_still_passed_through() -> None:
    """Verifies the translator stays silent on anything it cannot actually explain."""
    plan = [RebuildTable(_BEFORE, _AFTER)]

    assert (
        explain_rebuild_failure(
            plan, SQLiteDialect(), sqlite3.OperationalError("disk I/O error")
        )
        is None
    )


# --- And the shape the message prescribes DOES work -------------------------------------------


def test_the_bracket_the_message_prescribes_applies_against_sqlite(
    connection: sqlite3.Connection,
) -> None:
    """Verifies `DropView` -> rebuild -> `CreateView` applies, keeps the row and re-arms the CHECK.

    The advice has to be worth following, so it is run rather than described: this is the shape of
    `frameworks/shared/migrations/inventory/0004_on_hand_and_available_view.py`, written by hand
    because only the author knows the view reads the table.
    """
    # `realize` answers the wider union that also admits a data operation (`RunPython`), and none of
    # these three is one: the cast says so instead of guarding for a case that cannot arise.
    plan = cast(
        "list[SnakeOperation]",
        realize(
            [
                DropView(_LOW_STOCK),
                RebuildTable(_BEFORE, _AFTER),
                CreateView(_LOW_STOCK),
            ],
            SQLiteDialect(),
        ),
    )

    connection.execute("BEGIN")
    for operation in plan:
        for statement in operation.up_sql(SQLiteDialect()):
            connection.execute(statement)
    connection.execute("COMMIT")

    assert connection.execute('SELECT "qty" FROM "rbv_stock"').fetchall() == [(5,)]
    assert connection.execute("SELECT id FROM rbv_low_stock").fetchall() == [(1,)]
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute('INSERT INTO "rbv_stock" ("id", "qty") VALUES (2, 0)')
