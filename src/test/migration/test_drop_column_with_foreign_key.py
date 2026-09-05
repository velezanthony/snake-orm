"""Dropping a column that a foreign key holds: the plan, and what three real servers accept.

MEASURED, not reasoned, against the containers of this repo:

    ALTER TABLE t_child DROP COLUMN pid          -- pid carries a FOREIGN KEY
      PostgreSQL 17  -> accepted; the constraint falls with the column
      MariaDB 11.8.8 -> ERROR 1553 "Cannot drop index 'fk_x': needed in a foreign key constraint"
      SQLite  3.50.4 -> "error in table t_child after drop column: unknown column \"pid\" in
                         foreign key definition"

So TWO of the three engines refuse it, and `_WORKS_EVERYWHERE` said `DropColumn` was universal.
It was not, and the reason it looked universal is that the ORM's own diff normally emits a
`DropForeignKey` first — normally, but not always.

THE HOLE. `_diff_foreign_keys` resolved a dropped relation's target through the REGISTRY, and a
model that has just been deleted from the code is not in the registry any more. `target is None`
made the `DropForeignKey` disappear IN SILENCE, and the migration was left with a bare `DropColumn`
that two engines refuse. That is exactly the shape of the retirement this ORM cannot write today:
delete a `Category` model AND the `Post.category` that points at it, in one change.

The information was never missing. The PREVIOUS state — the one the migration history replays —
still holds the target table, with its real schema and its real columns, which is what the reverse
(`AddForeignKey`) needs in order to put the constraint back. It was simply never consulted.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable, Iterator, Sequence

import pytest

from snakeorm import PsycopgDriver, PyMySQLDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SnakeDialect, SQLiteDialect
from snakeorm.drivers.base import SnakeDriver
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
    CreateTable,
    DropColumn,
    DropForeignKey,
    DropTable,
    Migration,
    SnakeOperation,
    diff_schema,
    emit_create_table,
    foreign_key_name,
    realize,
    replay,
)
from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON
from test.scenarios.db import dsn

_PARENT_ID = SnakeColumnInfo(name="id", python_type=int)
_PARENT = SnakeTableInfo(
    name="fkdrop_parents",
    columns=(_PARENT_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_PARENT_ID,)),
)

_CHILD_ID = SnakeColumnInfo(name="id", python_type=int)
_PARENT_FK = SnakeColumnInfo(name="parent_id", python_type=int, nullable=True)
_RELATION = SnakeRelationshipInfo(
    name="parent",
    target="FkdropParent",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(
        target="FkdropParent", pairs=(("parent_id", "id"),)
    ),
    target_table="public.fkdrop_parents",
)
_CHILD_BEFORE = SnakeTableInfo(
    name="fkdrop_children",
    columns=(_CHILD_ID, _PARENT_FK),
    primary_key=SnakePrimaryKeyInfo(columns=(_CHILD_ID,)),
    relationships=(_RELATION,),
)
_CHILD_AFTER = SnakeTableInfo(
    name="fkdrop_children",
    columns=(_CHILD_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_CHILD_ID,)),
)

_CONSTRAINT = "fk_fkdrop_children_parent"


def _model_is_gone(target: str) -> SnakeTableInfo | None:
    """The registry AFTER the target model was deleted from the code: it resolves nothing."""
    return None


def _model_still_there(target: str) -> SnakeTableInfo | None:
    """The registry while the target model is still declared."""
    return _PARENT if target == "FkdropParent" else None


def _retirement_plan() -> list[SnakeOperation]:
    """The change this ORM could not write: the target model AND the column that pointed at it."""
    return diff_schema([_PARENT, _CHILD_BEFORE], [_CHILD_AFTER], _model_is_gone, None)


def _statements(
    plan: Sequence[SnakeOperation], dialect: SnakeDialect, *, forward: bool = True
) -> list[str]:
    """The SQL a plan hands the driver, in order, in one direction or the other."""
    return [
        sql
        for operation in plan
        for sql in (
            operation.up_sql(dialect) if forward else operation.down_sql(dialect)
        )
    ]


def _schema_plan(
    plan: Sequence[SnakeOperation], dialect: SnakeDialect
) -> list[SnakeOperation]:
    """`realize` narrowed back to the SCHEMA operations, which is all this module ever builds.

    The runner dispatches by the same structural check (`up_sql` versus `run`); doing it here too
    keeps the helpers below typed without a cast over something nobody verified.
    """
    return [
        operation
        for operation in realize(plan, dialect)
        if isinstance(operation, SnakeOperation)
    ]


# --- The plan ------------------------------------------------------------------------------


def test_the_constraint_name_is_derivable_from_the_metadata() -> None:
    """Verifies the FK's name comes out of table + relationship, with no catalogue lookup.

    It is what makes the guard below able to NAME the constraint the user has to drop. The name is
    deterministic by construction — the same one `emit_add_foreign_key` writes.
    """
    assert foreign_key_name(_CHILD_BEFORE, _RELATION) == _CONSTRAINT


def test_the_diff_keeps_the_key_drop_when_the_target_model_is_gone() -> None:
    """Verifies the retirement emits a DropForeignKey even with the target out of the registry.

    This is the bug. The registry cannot resolve a model that no longer exists, and the diff read
    that `None` as "nothing to drop" instead of falling back to the previous state, which does have
    the table.
    """
    plan = _retirement_plan()

    assert [type(operation).__name__ for operation in plan] == [
        "DropForeignKey",
        "DropColumn",
        "DropTable",
    ]


def test_the_key_is_dropped_before_the_column_it_holds() -> None:
    """Verifies the order, which is the whole point: MariaDB refuses the reverse order."""
    plan = _retirement_plan()
    keys = [i for i, op in enumerate(plan) if isinstance(op, DropForeignKey)]
    columns = [i for i, op in enumerate(plan) if isinstance(op, DropColumn)]

    assert keys and columns
    assert max(keys) < min(columns)


def test_the_reverse_restores_the_key_against_the_real_previous_table() -> None:
    """Verifies the DropForeignKey carries the target from the PREVIOUS state, not a stub.

    Its `down_sql` is an `AddForeignKey`, and that needs the target's real schema and real columns.
    Had the fallback invented a placeholder table, the rollback would have written a constraint
    pointing nowhere — green on the way out and broken on the way back.
    """
    dropped = next(op for op in _retirement_plan() if isinstance(op, DropForeignKey))

    assert dropped.target is _PARENT
    assert dropped.down_sql(PostgresDialect()) == [
        f'ALTER TABLE "public"."fkdrop_children" ADD CONSTRAINT "{_CONSTRAINT}" '
        f'FOREIGN KEY ("parent_id") REFERENCES "public"."fkdrop_parents" ("id")'
    ]


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect()],
    ids=lambda dialect: type(dialect).__name__,
)
def test_the_realized_plan_drops_the_key_first_on_every_engine_that_can(
    dialect: SnakeDialect,
) -> None:
    """Verifies the SQL that reaches the driver names the constraint before it names the column.

    SQLite is not here: it has no `DROP CONSTRAINT` at all, so `realize` stops it with its own
    message (the test below), which is the honest answer and not this one.
    """
    statements = _statements(_schema_plan(_retirement_plan(), dialect), dialect)
    dropped_key = next(i for i, sql in enumerate(statements) if _CONSTRAINT in sql)
    dropped_column = next(i for i, sql in enumerate(statements) if "DROP COLUMN" in sql)

    assert dropped_key < dropped_column


# --- The guard: a plan that never dropped the key at all ------------------------------------


def _naked_drop() -> DropColumn:
    """A hand-written `DropColumn` over a column its own table still declares an FK on."""
    return DropColumn(_CHILD_BEFORE, _PARENT_FK)


@pytest.mark.parametrize(
    "dialect",
    [MySQLDialect(), SQLiteDialect()],
    ids=lambda dialect: type(dialect).__name__,
)
def test_the_plan_stops_naming_the_table_the_column_and_the_key(
    dialect: SnakeDialect,
) -> None:
    """Verifies the two engines that refuse it stop at PLAN time, saying what and what to do.

    The alternative is what happened until now: the ORM emits it, the server throws 1553 (or
    SQLite's "unknown column in foreign key definition"), and the shout comes from the driver
    naming neither the model nor the column.
    """
    with pytest.raises(SnakeMigrationError) as error:
        realize([_naked_drop()], dialect)

    message = str(error.value)
    assert "fkdrop_children" in message
    assert "parent_id" in message
    assert _CONSTRAINT in message
    assert "DropForeignKey" in message


def test_postgres_does_not_stop_because_it_really_does_cascade() -> None:
    """Verifies the guard is per ENGINE and not a blanket ban: Postgres takes the column as is.

    Stopping here too would forbid on Postgres something Postgres does, which is the same mistake
    the BIGSERIAL fix refused to make in the other direction.
    """
    assert realize([_naked_drop()], PostgresDialect()) == [_naked_drop()]


def test_the_guard_is_quiet_when_the_plan_already_drops_the_key() -> None:
    """Verifies a correct plan is not refused: the guard looks at the PLAN, not at the type.

    A guard that fired on every `DropColumn` carrying a relation would refuse the ORM's own output,
    which drops the constraint one operation earlier.
    """
    plan: list[SnakeOperation] = [
        DropForeignKey(_CHILD_BEFORE, _RELATION, _PARENT),
        _naked_drop(),
    ]

    assert len(realize(plan, MySQLDialect())) == 2


def test_dropping_another_column_of_the_same_table_is_not_guarded() -> None:
    """Verifies the guard keys on the COLUMN and not on the table having any FK at all."""
    unrelated = SnakeColumnInfo(name="id", python_type=int)

    assert realize([DropColumn(_CHILD_BEFORE, unrelated)], MySQLDialect()) == [
        DropColumn(_CHILD_BEFORE, unrelated)
    ]


# --- Applied against the real servers, which is where the two errors were measured ----------


def _create(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Creates parent and child with the FK already in place, as `CreateTable` + `AddForeignKey`."""
    driver.execute(emit_create_table(_PARENT, dialect), ())
    driver.execute(emit_create_table(_CHILD_BEFORE, dialect), ())
    driver.execute(
        DropForeignKey(_CHILD_BEFORE, _RELATION, _PARENT).down_sql(dialect)[0], ()
    )
    driver.commit()


@pytest.fixture
def postgres() -> Iterator[PsycopgDriver]:
    """Real Postgres with both probe tables clean before and after."""
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
    _drop_probes(connection, "DROP TABLE IF EXISTS `{}`")
    try:
        yield connection
    finally:
        _drop_probes(connection, "DROP TABLE IF EXISTS `{}`")
        connection.close()


def _drop_probes(driver: SnakeDriver, template: str) -> None:
    """Child first, then parent: the very order this module exists to get right."""
    for table in ("fkdrop_children", "fkdrop_parents"):
        driver.execute(template.format(table), ())
    driver.commit()


@pytest.mark.integration
def test_mariadb_really_refuses_the_bare_drop_column(mariadb: PyMySQLDriver) -> None:
    """The control: the SQL the ORM used to emit is refused by this server, right now.

    Without this half the whole change is an opinion. With it, error 1553 is a fact, and the day
    some MariaDB stops raising it this test goes red and `Cap.DROP_COLUMN_CASCADES_FK` has to be
    answered again.
    """
    _create(mariadb, MySQLDialect())

    with pytest.raises(Exception) as error:  # noqa: B017 - the server raises its own 1553
        mariadb.execute(
            "ALTER TABLE `fkdrop_children` DROP COLUMN `parent_id`",
            (),
        )

    assert "1553" in str(error.value)


@pytest.mark.integration
def test_the_retirement_applies_and_reverts_on_a_real_postgres(
    postgres: PsycopgDriver,
) -> None:
    """Verifies the whole cycle on Postgres: apply, read the catalogue, revert, read it again."""
    _run_round_trip(postgres, PostgresDialect(), _postgres_catalogue)


@pytest.mark.integration
def test_the_retirement_applies_and_reverts_on_a_real_mariadb(
    mariadb: PyMySQLDriver,
) -> None:
    """Verifies the same cycle on MariaDB, which is the engine that pays for the decision."""
    _run_round_trip(mariadb, MySQLDialect(), _mariadb_catalogue)


def _postgres_catalogue(driver: SnakeDriver) -> tuple[bool, bool]:
    """(the column is there, the constraint is there), read from Postgres's own catalogue."""
    columns = driver.fetch_all(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'fkdrop_children' "
        "AND column_name = 'parent_id'",
        (),
    )
    constraints = driver.fetch_all(
        "SELECT 1 FROM information_schema.table_constraints "
        "WHERE table_name = 'fkdrop_children' AND constraint_name = %s",
        (_CONSTRAINT,),
    )
    return bool(columns), bool(constraints)


def _mariadb_catalogue(driver: SnakeDriver) -> tuple[bool, bool]:
    """The same two answers, read from MariaDB's `information_schema`."""
    columns = driver.fetch_all(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() "
        "AND table_name = 'fkdrop_children' AND column_name = 'parent_id'",
        (),
    )
    constraints = driver.fetch_all(
        "SELECT 1 FROM information_schema.table_constraints WHERE table_schema = DATABASE() "
        "AND table_name = 'fkdrop_children' AND constraint_name = %s",
        (_CONSTRAINT,),
    )
    return bool(columns), bool(constraints)


def _run_round_trip(
    driver: SnakeDriver,
    dialect: SnakeDialect,
    catalogue: Callable[[SnakeDriver], tuple[bool, bool]],
) -> None:
    """Create, apply the retirement, check both are gone, revert, check both are back.

    The `DropTable` is left out of the applied part on purpose: it is the OTHER half of this change
    and has its own module. What is measured here is the column and its constraint.
    """
    _create(driver, dialect)
    assert catalogue(driver) == (True, True)

    plan = [
        operation
        for operation in _schema_plan(_retirement_plan(), dialect)
        if not isinstance(operation, DropTable)
    ]
    for sql in _statements(plan, dialect):
        driver.execute(sql, ())
    driver.commit()
    assert catalogue(driver) == (False, False)

    for sql in _statements(list(reversed(plan)), dialect, forward=False):
        driver.execute(sql, ())
    driver.commit()
    assert catalogue(driver) == (True, True)


# --- Through the real path: replay the history, diff it, render it ---------------------------


def test_the_replayed_history_still_names_the_target_it_is_losing() -> None:
    """Verifies the fix survives the path a real `makemigrations` takes, not just a hand-built diff.

    The previous state does not arrive as a list of tables: it is REPLAYED from the migration files,
    which is where `target_table` could have been lost. It is not — `render` writes it whenever it
    is resolved, precisely so the migration is self-contained — and this is what checks that the two
    halves meet.
    """
    history = [
        Migration(
            "0001",
            (
                CreateTable(_PARENT),
                CreateTable(_CHILD_BEFORE),
                AddForeignKey(_CHILD_BEFORE, _RELATION, _PARENT),
            ),
        )
    ]
    state = replay(history)

    plan = diff_schema(state.tables(), [_CHILD_AFTER], _model_is_gone, None)

    dropped = next(op for op in plan if isinstance(op, DropForeignKey))
    assert dropped.target.name == "fkdrop_parents"
    assert [type(operation).__name__ for operation in plan] == [
        "DropForeignKey",
        "DropColumn",
        "DropTable",
    ]


def test_a_history_that_recorded_no_target_table_is_the_documented_floor() -> None:
    """Verifies the honest boundary: with no `target_table` recorded, the key cannot be resolved.

    `target_table` is DERIVED — the linker fills it in and `render` writes it — so a migration
    written before it existed does not carry it. The previous state still holds the table and
    nothing says which one, so the fallback answers nothing rather than guessing. Written down as a
    test because a limit nobody measured is a limit that gets rediscovered as a bug.
    """
    ancient = dataclasses.replace(_RELATION, target_table="")
    child = dataclasses.replace(_CHILD_BEFORE, relationships=(ancient,))

    plan = diff_schema([_PARENT, child], [_CHILD_AFTER], _model_is_gone, None)

    assert not [op for op in plan if isinstance(op, DropForeignKey)]
