"""`RenameTable`: the operation the catalogue did not have, and the hole was real on its own.

Twenty-seven operations and none of them renamed a table, so a rename could not be EXPRESSED: the
diff sees it as `DropTable` + `CreateTable`, which is correct SQL and wipes every row. It is the same
trap `RenameColumn` exists to get out of, one level up.

MEASURED on the three servers before the shape was decided, because "they all have RENAME TO" is not
the same as "they all take the same statement":

    PostgreSQL 17     ALTER TABLE "public"."old" RENAME TO "new"     accepted
                      ALTER TABLE "public"."old" RENAME TO "public"."new"   SYNTAX ERROR
    MariaDB 11.8.8    ALTER TABLE `old` RENAME TO `new`             accepted
    SQLite 3.50.4     ALTER TABLE "old" RENAME TO "new"             accepted

So the old name is qualified and the new one is NOT, and that is not a style choice: Postgres
refuses the qualified form outright. A rename moves a table WITHIN its schema; moving it between
schemas is `SET SCHEMA`, a different statement and not this operation.

AND THE FOREIGN KEYS SURVIVE, measured the same way on the same three: a key pointing AT the renamed
table keeps pointing at it and keeps rejecting the orphan row. Each engine gets there differently —
Postgres tracks the table by OID, MariaDB rewrites `information_schema`, SQLite rewrites the
`REFERENCES` clause in the other table's own DDL — but the answer is the same, which is why
`apply_to_state` follows the rename in the relations that point at the table too. A state that kept
the old name would be the only place in the system still believing it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

from snakeorm import PsycopgDriver, PyMySQLDriver, SQLiteDriver
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
    RenameTable,
    SchemaState,
    diff_schema,
    emit_create_table,
    emit_rename_table,
    realize,
    render_migration,
)
from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON
from test.scenarios.db import dsn

_OLD, _NEW = "rnt_parents", "rnt_ancestors"

_PARENT_ID = SnakeColumnInfo(name="id", python_type=int)
_PARENT = SnakeTableInfo(
    name=_OLD,
    columns=(_PARENT_ID, SnakeColumnInfo(name="label", python_type=str, nullable=True)),
    primary_key=SnakePrimaryKeyInfo(columns=(_PARENT_ID,)),
)

_CHILD_ID = SnakeColumnInfo(name="id", python_type=int)
_PARENT_FK = SnakeColumnInfo(name="parent_id", python_type=int, nullable=True)
_RELATION = SnakeRelationshipInfo(
    name="parent",
    target="RntParent",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="RntParent", pairs=(("parent_id", "id"),)),
    target_table=f"public.{_OLD}",
)
_CHILD = SnakeTableInfo(
    name="rnt_children",
    columns=(_CHILD_ID, _PARENT_FK),
    primary_key=SnakePrimaryKeyInfo(columns=(_CHILD_ID,)),
    relationships=(_RELATION,),
)

_POSTGRES = PostgresDialect()


# --- The statement -------------------------------------------------------------------------


def test_up_renames_and_down_puts_it_back() -> None:
    """Verifies the rename is genuinely reversible, and that neither half touches a row."""
    operation = RenameTable(_PARENT, new_name=_NEW)

    assert operation.up_sql(_POSTGRES) == [
        f'ALTER TABLE "public"."{_OLD}" RENAME TO "{_NEW}"'
    ]
    assert operation.down_sql(_POSTGRES) == [
        f'ALTER TABLE "public"."{_NEW}" RENAME TO "{_OLD}"'
    ]


def test_the_new_name_is_never_qualified_by_the_schema() -> None:
    """Verifies the target of the RENAME is a bare identifier, which is what Postgres accepts.

    `ALTER TABLE "public"."a" RENAME TO "public"."b"` is a syntax error on the reference engine —
    measured, and it is the reason this is asserted instead of assumed. Qualifying both sides reads
    natural and does not parse.
    """
    statement = RenameTable(_PARENT, new_name=_NEW).up_sql(_POSTGRES)[0]

    assert statement.endswith(f'RENAME TO "{_NEW}"')
    assert f'RENAME TO "public"."{_NEW}"' not in statement


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        (PostgresDialect(), f'ALTER TABLE "public"."{_OLD}" RENAME TO "{_NEW}"'),
        (MySQLDialect(), f"ALTER TABLE `{_OLD}` RENAME TO `{_NEW}`"),
        (SQLiteDialect(), f'ALTER TABLE "{_OLD}" RENAME TO "{_NEW}"'),
    ],
    ids=lambda value: (
        type(value).__name__ if isinstance(value, SnakeDialect) else "sql"
    ),
)
def test_each_engine_gets_the_statement_it_takes(
    dialect: SnakeDialect, expected: str
) -> None:
    """Verifies ONE grammar written in three quotings, and the schema only where there are schemas."""
    assert emit_rename_table(_PARENT, _NEW, dialect) == expected


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect(), SQLiteDialect()],
    ids=lambda dialect: type(dialect).__name__,
)
def test_no_engine_refuses_it_in_the_plan(dialect: SnakeDialect) -> None:
    """Verifies `realize` lets it through everywhere: it is in `_WORKS_EVERYWHERE` for a reason.

    Declaring a capability it does not need would refuse on SQLite the one thing SQLite has always
    been able to do — and it is precisely the last step the table rebuild is going to need there.
    """
    operation = RenameTable(_PARENT, new_name=_NEW)

    assert realize([operation], dialect) == [operation]


# --- The abstract state --------------------------------------------------------------------


def test_apply_to_state_renames_the_table_keeping_its_definition() -> None:
    """Verifies the state knows the table by its new name, with the same columns and PK."""
    state = SchemaState([_PARENT])

    RenameTable(_PARENT, new_name=_NEW).apply_to_state(state)

    assert state.get_table(_OLD) is None
    renamed = state.get_table(_NEW)
    assert renamed is not None
    assert renamed.columns == _PARENT.columns
    assert renamed.primary_key == _PARENT.primary_key


def test_apply_to_state_follows_the_rename_in_the_keys_that_point_at_it() -> None:
    """Verifies a relation aimed at the table is re-aimed, because the three engines re-aim it too.

    Measured: after the rename Postgres still resolves the constraint to the new table, MariaDB
    reports the new name in `information_schema`, and SQLite has rewritten the `REFERENCES` clause
    inside the child's own DDL. Leaving `target_table` on the old name would make the replayed state
    the only thing in the system still naming a table that no longer exists — and `drop_order` and
    the planner both read that field to work out what has to go first.
    """
    state = SchemaState([_PARENT, _CHILD])

    RenameTable(_PARENT, new_name=_NEW).apply_to_state(state)

    child = state.get_table("rnt_children")
    assert child is not None
    assert child.relationships[0].target_table == f"public.{_NEW}"
    assert child.relationships[0].foreign_key == _RELATION.foreign_key, (
        "the columns of the key do not move; only the table they point at is renamed"
    )


def test_apply_to_state_is_quiet_over_a_table_the_state_never_had() -> None:
    """Verifies an unknown table is a no-op, like every other operation's `apply_to_state`."""
    state = SchemaState([_CHILD])

    RenameTable(_PARENT, new_name=_NEW).apply_to_state(state)

    assert state.get_table(_NEW) is None
    assert state.get_table("rnt_children") is not None


def test_the_diff_still_refuses_to_guess_a_rename() -> None:
    """Verifies the diff does NOT invent one: it keeps emitting create + drop, as with columns.

    A heuristic that reads "a table dropped and a table added, same columns" as a rename is right
    almost every time, and the time it is wrong it keeps a table somebody asked to destroy with
    another table's rows in it. The diff suggests nothing here; the human writes the operation.
    """
    renamed = SnakeTableInfo(
        name=_NEW, columns=_PARENT.columns, primary_key=_PARENT.primary_key
    )

    kinds = [
        type(operation).__name__ for operation in diff_schema([_PARENT], [renamed])
    ]
    assert kinds == ["CreateTable", "DropTable"]


def test_it_writes_itself_into_a_migration_file_that_rebuilds_it() -> None:
    """Verifies point 2 of the 4-point contract: the renderer knows it and imports it.

    `test_render_completeness` covers every operation at once; this one is here because the import
    is the half that fails LATE — a rendered name with no import line is a `NameError` raised while
    applying the migration, which is the worst moment to find out.
    """
    source = render_migration("0001_rename", [RenameTable(_PARENT, new_name=_NEW)])

    assert "from snakeorm.migration import (" in source
    assert "    RenameTable," in source

    namespace: dict[str, object] = {}
    exec(compile(source, "0001_rename.py", "exec"), namespace)  # noqa: S102
    rebuilt = namespace["operations"]

    assert rebuilt == [RenameTable(_PARENT, new_name=_NEW)]  # type: ignore[comparison-overlap]


# --- Applied against the real servers, which is where "they all have RENAME TO" was checked --


def _ref(name: str, dialect: SnakeDialect) -> str:
    """The table as this engine spells it in a statement written by hand in this file."""
    if dialect.supports_schemas:
        return f"{dialect.quote_ident('public')}.{dialect.quote_ident(name)}"
    return dialect.quote_ident(name)


def _create(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Parent and child with the key already standing, the way a first migration leaves them.

    On SQLite the key travelled INSIDE the `CREATE TABLE` — that is what `emit_create_table` does
    where there is no `ADD CONSTRAINT` — so there is no second statement to run there.
    """
    driver.execute(emit_create_table(_PARENT, dialect), ())
    driver.execute(emit_create_table(_CHILD, dialect), ())
    if dialect.supports_add_constraint:
        driver.execute(AddForeignKey(_CHILD, _RELATION, _PARENT).up_sql(dialect)[0], ())
    driver.execute(
        f"INSERT INTO {_ref(_OLD, dialect)} ({dialect.quote_ident('id')}) VALUES (1)",
        (),
    )
    driver.commit()


def _drop_probes(driver: SnakeDriver, template: str) -> None:
    """Child first, then both possible names of the parent: the rename may have landed."""
    for table in ("rnt_children", _OLD, _NEW):
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


def _postgres_tables(driver: SnakeDriver) -> set[str]:
    """The probe tables that exist right now, read from Postgres's own catalogue."""
    rows = driver.fetch_all(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name IN (%s, %s)",
        (_OLD, _NEW),
    )
    return {str(row[0]) for row in rows}


def _mariadb_tables(driver: SnakeDriver) -> set[str]:
    """The same answer out of MariaDB's `information_schema`."""
    rows = driver.fetch_all(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name IN (%s, %s)",
        (_OLD, _NEW),
    )
    return {str(row[0]) for row in rows}


def _sqlite_tables(driver: SnakeDriver) -> set[str]:
    """The same answer out of `sqlite_master`, which is SQLite's whole catalogue."""
    rows = driver.fetch_all(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
        (_OLD, _NEW),
    )
    return {str(row[0]) for row in rows}


def _round_trip(
    driver: SnakeDriver,
    dialect: SnakeDialect,
    read: Callable[[SnakeDriver], set[str]],
) -> None:
    """Create, rename, look, revert, look — plus the orphan row the key still has to refuse."""
    _create(driver, dialect)
    assert read(driver) == {_OLD}

    operation = RenameTable(_PARENT, new_name=_NEW)
    for statement in operation.up_sql(dialect):
        driver.execute(statement, ())
    driver.commit()

    assert read(driver) == {_NEW}, "the rename left the old name behind"

    # The key that pointed at the old name still refuses an orphan, on all three engines. The
    # message is READ and not just the type: `pytest.raises(Exception)` on an INSERT would be
    # satisfied by "no such table" too, which is the opposite of what this is measuring.
    with pytest.raises(Exception) as error:  # noqa: B017 - one integrity error per engine
        driver.execute(
            f"INSERT INTO {_ref('rnt_children', dialect)} "
            f"({dialect.quote_ident('id')}, {dialect.quote_ident('parent_id')}) "
            f"VALUES (1, 99)",
            (),
        )
    assert "foreign key" in str(error.value).lower(), (
        "the row was refused for some other reason, so this proves nothing about the key"
    )
    driver.rollback()

    for statement in operation.down_sql(dialect):
        driver.execute(statement, ())
    driver.commit()

    assert read(driver) == {_OLD}, "the reverse did not put the old name back"


@pytest.mark.integration
def test_it_applies_and_reverts_on_a_real_postgres(postgres: PsycopgDriver) -> None:
    """Verifies the whole cycle on Postgres, catalogue included, with the key still standing."""
    _round_trip(postgres, _POSTGRES, _postgres_tables)


@pytest.mark.integration
def test_it_applies_and_reverts_on_a_real_mariadb(mariadb: PyMySQLDriver) -> None:
    """Verifies the same cycle on MariaDB, which spells the statement in backticks."""
    _round_trip(mariadb, MySQLDialect(), _mariadb_tables)


def test_it_applies_and_reverts_on_sqlite() -> None:
    """Verifies the same cycle on SQLite, where the rebuild is eventually going to need it.

    No server and no `integration` mark: SQLite is a file, so this one runs everywhere. It is also
    the engine whose foreign keys are OFF by default, hence the pragma — without it the orphan row
    would be accepted and this test would prove nothing about the key.
    """
    driver = SQLiteDriver.connect(":memory:")
    try:
        driver.execute("PRAGMA foreign_keys = ON", ())
        _round_trip(driver, SQLiteDialect(), _sqlite_tables)
    finally:
        driver.close()
