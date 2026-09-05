"""A refusal names a way out, and the way out has to OPEN on the engine that is refusing.

The doctrine of this repository is that the message is the product, and a refusal spends its whole
value on one sentence: what to do instead. Two ways of ruining that sentence had both happened here
at once, and neither shows up as a red test on its own.

THE FIRST IS PRESCRIBING A CLOSED DOOR. `_guard_dropped_fk_column` used to end, on every engine,
with "Put a `DropForeignKey` for X BEFORE this `DropColumn`". Measured:

    ALTER TABLE c DROP COLUMN parent_id       -- parent_id carries a FOREIGN KEY
      MariaDB 11.8.8 -> ERROR 1553; DROP CONSTRAINT first, then the column -> both accepted
      SQLite  3.50   -> "unknown column ... in foreign key definition"; and a `DropForeignKey`
                        in front is refused by `realize` ITSELF, because SQLite has no
                        `ALTER TABLE ... DROP CONSTRAINT`

So on SQLite the advice sent the reader to an operation the very next `realize` call rejects — the
plan refused in BOTH of its halves — while the capability reason quoted one clause earlier said the
opposite, that the table has to be remade. One message, two engines, and on one of them it
contradicted itself.

THE SECOND IS DESCRIBING AN ORM THAT NO LONGER EXISTS. The `AddForeignKey`/`DropForeignKey` branch
and the `AddCheck` requirement both said remaking the table "is the user's call, not the ORM's: do
it with a `RunSQL`". `RebuildTable` has existed for a while, `realize` imports it, and the
autodetected diff collapses a pure constraint change into one. The ORM does it itself now.

What this module pins is the property that covers both: WHAT A REFUSAL PRESCRIBES IS ACCEPTED BY
`realize` ON THE SAME ENGINE THAT REFUSED. A message cannot be checked for being true, but a plan
can be built out of what it says and run back through the gate, and that is a mechanical question
with a mechanical answer.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import re
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from snakeorm import PyMySQLDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SnakeDialect, SQLiteDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AddForeignKey,
    CreateSchema,
    DropColumn,
    DropSchema,
    DropForeignKey,
    RebuildTable,
    SnakeMigrationOperation,
    SnakeOperation,
    emit_create_table,
    realize,
)
from test.conftest import NO_MYSQL_REASON

_PARENT_ID = SnakeColumnInfo(name="id", python_type=int)
_PARENT = SnakeTableInfo(
    name="doors_parents",
    columns=(_PARENT_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_PARENT_ID,)),
)

_CHILD_ID = SnakeColumnInfo(name="id", python_type=int)
_PARENT_FK = SnakeColumnInfo(name="parent_id", python_type=int, nullable=True)
_RELATION = SnakeRelationshipInfo(
    name="parent",
    target="DoorsParent",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="DoorsParent", pairs=(("parent_id", "id"),)),
    target_table="doors_parents",
)
_CHILD = SnakeTableInfo(
    name="doors_children",
    columns=(_CHILD_ID, _PARENT_FK),
    primary_key=SnakePrimaryKeyInfo(columns=(_CHILD_ID,)),
    relationships=(_RELATION,),
)
_CHILD_WITHOUT_KEY = dataclasses.replace(_CHILD, relationships=())

_CONSTRAINT = "fk_doors_children_parent"


def _naked_drop() -> DropColumn:
    """A hand-written `DropColumn` over a column its own table still declares a foreign key on."""
    return DropColumn(_CHILD, _PARENT_FK)


def _refusal(operation: SnakeMigrationOperation, dialect: SnakeDialect) -> str:
    """What `realize` SAYS when it refuses this operation on this engine."""
    with pytest.raises(SnakeMigrationError) as error:
        realize([operation], dialect)
    return str(error.value)


def _statements(
    plan: Sequence[SnakeMigrationOperation], dialect: SnakeDialect
) -> list[str]:
    """The SQL a realized plan hands the driver, in order.

    Narrowed to the SCHEMA operations, which is all this module ever builds: `realize` returns the
    wider union that also carries `RunPython`, and the runner tells them apart by the same
    structural check. Doing it here too keeps the loop typed without a cast over something nobody
    verified.
    """
    return [
        sql
        for operation in plan
        if isinstance(operation, SnakeOperation)
        for sql in operation.up_sql(dialect)
    ]


# --- The guard over a column a key still holds: one gap, two engines, two doors -------------


def test_the_sqlite_refusal_does_not_point_at_the_door_it_also_shuts() -> None:
    """Verifies SQLite is NOT told to put a `DropForeignKey` first, which the next call refuses.

    The prescription and the shutting are two lines of the same file: `realize` rejects a
    `DropForeignKey` on an existing table wherever `Cap.ADD_CONSTRAINT` is missing, and that is
    exactly the engine this guard fires on. The old wording asked for it anyway.
    """
    message = _refusal(_naked_drop(), SQLiteDialect())

    assert "Put a `DropForeignKey`" not in message
    assert "RebuildTable" in message


def test_the_sqlite_refusal_says_out_loud_that_the_obvious_move_is_shut() -> None:
    """Verifies it NAMES `DropForeignKey` as closed, instead of leaving the reader to find out.

    Staying silent about it would be honest and still expensive: `DropForeignKey` is the move
    anyone who knows the other two engines reaches for first, and finding the door walled up costs
    a second migration run to learn. The message says it in the same breath as the way out.
    """
    message = _refusal(_naked_drop(), SQLiteDialect())

    assert "DropForeignKey" in message
    assert "DROP CONSTRAINT" in message


def test_the_mysql_refusal_still_prescribes_the_key_drop_that_really_works() -> None:
    """Verifies the fix did not flatten the two engines into one vaguer message.

    MariaDB DOES take `DROP CONSTRAINT` and then `DROP COLUMN` — measured below against the real
    server — so telling it to rebuild the table would be prescribing surgery for a scratch. One gap
    in the catalogue, two ways out, because the engines really do differ.
    """
    message = _refusal(_naked_drop(), MySQLDialect())

    assert "Put a `DropForeignKey`" in message
    assert "RebuildTable" not in message


def test_both_engine_variants_of_the_guard_name_the_same_three_things() -> None:
    """Verifies the two messages agree on the FACTS and differ only in the way out.

    Table, column and constraint name are what the reader searches their code for; those cannot
    drift between engines because they do not depend on the engine. Asserting one message against
    the other is what `format_narrowing_hint` and `format_rename_hint` already do for their pair.
    """
    messages = [
        _refusal(_naked_drop(), dialect)
        for dialect in (MySQLDialect(), SQLiteDialect())
    ]

    for message in messages:
        assert "doors_children" in message
        assert "parent_id" in message
        assert _CONSTRAINT in message
        assert "cannot be dropped" in message


def test_postgres_is_not_guarded_at_all_because_it_really_cascades() -> None:
    """Verifies the branch stayed per ENGINE: Postgres takes the column with the key on it."""
    assert realize([_naked_drop()], PostgresDialect()) == [_naked_drop()]


# --- The property that covers all of them: the prescription goes back through the gate ------


def _sqlite_prescription() -> list[SnakeMigrationOperation]:
    """What the SQLite refusal asks for: the rebuild that leaves the key out, then the column."""
    return [
        RebuildTable(_CHILD, _CHILD_WITHOUT_KEY),
        DropColumn(_CHILD_WITHOUT_KEY, _PARENT_FK),
    ]


def _mysql_prescription() -> list[SnakeMigrationOperation]:
    """What the MySQL refusal asks for: the key dropped in its own operation, then the column."""
    return [DropForeignKey(_CHILD, _RELATION, _PARENT), _naked_drop()]


def test_what_the_sqlite_refusal_prescribes_is_accepted_by_sqlite() -> None:
    """Verifies the prescribed plan passes the same gate that refused the original one.

    This is the mechanical half of "the message is true". `realize` cannot be asked whether a
    sentence is honest, but it can be handed the plan that sentence describes.
    """
    assert len(realize(_sqlite_prescription(), SQLiteDialect())) == 2


def test_what_the_old_message_prescribed_is_still_refused_by_sqlite() -> None:
    """Verifies the control: the door the old advice pointed at is shut, and this is why.

    Without this half the test above only proves that some plan works. What made the old wording a
    bug is that ITS plan does not, and it fails on the operation the advice named.
    """
    with pytest.raises(
        SnakeMigrationError, match="does not know how to add constraints"
    ):
        realize(_mysql_prescription(), SQLiteDialect())


def test_what_the_mysql_refusal_prescribes_is_accepted_by_mysql() -> None:
    """Verifies the other engine's prescription passes its own gate, for the same reason."""
    assert len(realize(_mysql_prescription(), MySQLDialect())) == 2


def test_the_refusals_over_an_existing_table_name_the_rebuild_the_orm_owns() -> None:
    """Verifies the constraint refusals point at `RebuildTable` and not at hand-written SQL.

    They used to end with "that is the user's call, not the ORM's: do it with a `RunSQL`", written
    when the ORM had no rebuild. It has one — `realize` imports it, and a pure constraint change
    collapses into it — so the sentence described a previous version of this project.
    """
    for operation in (
        AddForeignKey(_CHILD, _RELATION, _PARENT),
        DropForeignKey(_CHILD, _RELATION, _PARENT),
    ):
        message = _refusal(operation, SQLiteDialect())
        assert "RebuildTable" in message
        assert "the user's call, not the ORM's" not in message


def _emitted_text() -> str:
    """Everything `realize.py` can put in front of a user: its raises and its reasons table.

    The MESSAGES and not the file. Reading the whole source would sweep up the comments and the
    docstrings, which talk about `Cap` and `SnakeTableInfo` — real names, but names for the people
    editing this module, not doors offered to somebody whose migration just stopped.
    """
    from snakeorm import migration

    source = Path(migration.__file__ or "").with_name("realize.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    carriers: list[ast.AST] = [
        node for node in ast.walk(tree) if isinstance(node, ast.Raise)
    ]
    carriers.extend(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign | ast.Assign)
        and node.value is not None
        and "_REQUIREMENTS"
        in ast.unparse(
            node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
        )
    )
    return " ".join(
        node.value
        for carrier in carriers
        for node in ast.walk(carrier)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_every_operation_a_refusal_names_is_an_operation_that_exists() -> None:
    """Verifies each `Backticked` class name a message carries is really exported by the package.

    A refusal spends its value on naming the way out, and a name nobody can import is worse than no
    name: the reader goes looking for an operation that was never there. This reads the module's own
    messages rather than a hand-kept list, so a sentence written tomorrow is covered too.

    Backticked CamelCase and nothing else: `ALTER TABLE ... ADD CONSTRAINT` is SQL the engine
    speaks and `target_table` is a field, and neither is something anybody imports.
    """
    from snakeorm import migration

    named = set(re.findall(r"`([A-Z][a-z]+[A-Za-z]*)`", _emitted_text()))

    assert named, "no operation is named in any message, so this net measures nothing"
    unknown = sorted(name for name in named if not hasattr(migration, name))
    assert unknown == [], f"refusals name operations that do not exist: {unknown}"


def test_the_refusals_do_name_the_rebuild_so_the_net_above_has_something_to_check() -> (
    None
):
    """Verifies `RebuildTable` really reaches the messages, not only the imports of the module.

    `realize` has imported it all along — it counts the keys a rebuild removes — while no sentence
    mentioned it. An import is not an answer to anybody; this pins the difference.
    """
    assert "RebuildTable" in _emitted_text()


# --- The other prescription that did not unblock anything -----------------------------------


def test_the_schema_refusal_names_the_migration_and_not_only_the_models() -> None:
    """Verifies it says the already-written file has to be regenerated, not just the models edited.

    "Drop the `schema=` from the models of this connection" was the whole advice, and it does not
    unblock what is being refused: the `CreateSchema` being realized lives in a migration file that
    is on disk right now. Editing the models stops the NEXT autodetect from emitting one; the file
    in front of the runner is untouched, so the same refusal comes back.
    """
    message = _refusal(CreateSchema("analytics"), SQLiteDialect())

    assert "this engine has no named schemas" in message
    assert "schema=" in message
    assert "migration" in message


def test_both_halves_of_the_schema_gap_send_the_reader_to_the_same_two_edits() -> None:
    """Verifies `CreateSchema` and `DropSchema` answer one gap with one instruction, as the CHECKs do.

    `DropSchema` said only "there is none to drop", which is a fact about the engine and not an
    answer to the person whose migration just stopped: their file still carries the operation. A
    reader who meets the pair — the plan that moves a model out of a schema carries both — would
    otherwise get the way out from one half and a shrug from the other, which is how the `AddCheck`
    and `DropCheck` twins drifted apart in the first place.
    """
    messages = [
        _refusal(operation, SQLiteDialect())
        for operation in (CreateSchema("analytics"), DropSchema("analytics"))
    ]

    for message in messages:
        assert "this engine has no named schemas" in message
        assert "schema=" in message
        assert "regenerate the migration" in message


# --- Measured against the real engines, which is where every sentence above came from -------


def test_the_sqlite_prescription_really_applies_on_a_real_sqlite() -> None:
    """Applies the prescribed plan on a live SQLite: the column goes and the rows stay.

    SQLite needs no container, so this runs everywhere and never skips — which is the point. The
    advice claims the rebuild frees the column; here the engine answers.
    """
    dialect = SQLiteDialect()
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(emit_create_table(_PARENT, dialect))
    connection.execute(emit_create_table(_CHILD, dialect))
    connection.execute("INSERT INTO doors_parents (id) VALUES (1)")
    connection.execute("INSERT INTO doors_children (id, parent_id) VALUES (10, 1)")

    with pytest.raises(sqlite3.OperationalError, match="in foreign key definition"):
        connection.execute("ALTER TABLE doors_children DROP COLUMN parent_id")

    for statement in _statements(realize(_sqlite_prescription(), dialect), dialect):
        connection.execute(statement)
    connection.commit()

    assert connection.execute("SELECT * FROM doors_children").fetchall() == [(10,)]
    connection.close()


@pytest.fixture
def mariadb() -> Iterator[PyMySQLDriver]:
    """Real MySQL/MariaDB with both probe tables clean before and after."""
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
    _drop_probes(connection)
    try:
        yield connection
    finally:
        _drop_probes(connection)
        connection.close()


def _drop_probes(driver: PyMySQLDriver) -> None:
    """Child first, then parent: the order this whole module is about."""
    for table in ("doors_children", "doors_parents"):
        driver.execute(f"DROP TABLE IF EXISTS `{table}`", ())
    driver.commit()


@pytest.mark.integration
def test_the_mysql_prescription_really_applies_on_a_real_mariadb(
    mariadb: PyMySQLDriver,
) -> None:
    """Applies the prescribed plan on a live MariaDB: the key drop in front DOES free the column.

    The control comes first — the bare `DROP COLUMN` answering 1553 — because without it the second
    half only proves that two statements ran. With it, the difference between the two engines is a
    fact of this server and not an opinion about it, which is what keeps the two messages different.
    """
    dialect = MySQLDialect()
    mariadb.execute(emit_create_table(_PARENT, dialect), ())
    mariadb.execute(emit_create_table(_CHILD, dialect), ())
    mariadb.execute(DropForeignKey(_CHILD, _RELATION, _PARENT).down_sql(dialect)[0], ())
    mariadb.execute("INSERT INTO `doors_parents` (id) VALUES (1)", ())
    mariadb.execute("INSERT INTO `doors_children` (id, parent_id) VALUES (10, 1)", ())
    mariadb.commit()

    with pytest.raises(Exception, match="1553"):
        mariadb.execute("ALTER TABLE `doors_children` DROP COLUMN `parent_id`", ())
    mariadb.commit()

    for statement in _statements(realize(_mysql_prescription(), dialect), dialect):
        mariadb.execute(statement, ())
    mariadb.commit()

    # A LIST, and it used to say a tuple. That expectation was not a style choice: PyMySQL hands
    # back a tuple of tuples and the driver returned it untouched, so this test had quietly pinned
    # bug #40 — the Protocol promises `list[tuple]` and one engine of three did not keep it.
    assert mariadb.fetch_all("SELECT * FROM `doors_children`", ()) == [(10,)]
