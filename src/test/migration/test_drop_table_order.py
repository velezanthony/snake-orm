"""Retiring several tables at once: the referenced one goes LAST, and that is not a MariaDB quirk.

MEASURED against the containers of this repo, with `t_child` holding a FOREIGN KEY into `t_parent`:

    DROP TABLE t_parent
      PostgreSQL 17  -> refused: other objects depend on it
      MariaDB 11.8.8 -> ERROR 1451, a row is referenced
      SQLite  3.50.4 -> accepted, and the foreign key is left dangling

TWO of three refuse, so this is not a dialect difference to translate: it is correct SQL, and the
fix is ORDER. The one that HOLDS the key goes first; the one it points at, after. It is the exact
mirror of what the plan already does to CREATE them, and of `_topological_order` for views, which
drops them in reverse of the order it creates them in.

`diff_schema` emitted the drops in ALPHABETICAL order, so `categories` came out before `posts` for
no better reason than the letter c. Whether a migration applied was decided by the names.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from snakeorm import PsycopgDriver, PyMySQLDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SnakeDialect
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
    DropTable,
    SnakeOperation,
    diff_schema,
    emit_create_table,
)
from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON
from test.scenarios.db import dsn


def _table(
    name: str,
    *,
    references: str | None = None,
    column: str = "parent_id",
) -> SnakeTableInfo:
    """A probe table, optionally holding a to-one FK into another one of this set."""
    identifier = SnakeColumnInfo(name="id", python_type=int)
    if references is None:
        return SnakeTableInfo(
            name=name,
            columns=(identifier,),
            primary_key=SnakePrimaryKeyInfo(columns=(identifier,)),
        )
    model = "".join(part.capitalize() for part in references.split("_"))
    return SnakeTableInfo(
        name=name,
        columns=(
            identifier,
            SnakeColumnInfo(name=column, python_type=int, nullable=True),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(identifier,)),
        relationships=(
            SnakeRelationshipInfo(
                name=references,
                target=model,
                kind=SnakeRelationshipKind.TO_ONE,
                foreign_key=SnakeForeignKeyInfo(target=model, pairs=((column, "id"),)),
                target_table=f"public.{references}",
            ),
        ),
    )


# `dorder_a` sorts BEFORE `dorder_z` and is the one that must be dropped LAST: alphabetical order
# and correct order are deliberately opposed here, so a test that passes by accident cannot.
_REFERENCED = _table("dorder_a")
_HOLDER = _table("dorder_z", references="dorder_a")


def _drop_everything() -> list[SnakeOperation]:
    """The plan that retires both tables in one change."""
    return diff_schema([_REFERENCED, _HOLDER], [], lambda target: None, None)


def _dropped_names(plan: list[SnakeOperation]) -> list[str]:
    """The names of the tables the plan drops, in the order it drops them."""
    return [op.table.name for op in plan if isinstance(op, DropTable)]


def test_the_table_holding_the_key_is_dropped_before_the_one_it_points_at() -> None:
    """Verifies the drop order follows the FK graph backwards, not the alphabet.

    This is the whole bug: `dorder_a` is referenced and sorts first, so it used to be dropped first
    and two engines out of three refused the migration.
    """
    assert _dropped_names(_drop_everything()) == ["dorder_z", "dorder_a"]


def test_a_table_nobody_references_keeps_a_stable_place() -> None:
    """Verifies the ordering is stable and by name where the FKs impose nothing.

    Without a fixed tie-break the same models would generate a different migration on each run,
    which is the phantom-diff problem `_diff_indexes` and `_topological_order` already avoid.
    """
    loose = _table("dorder_m")
    plan = diff_schema([_REFERENCED, _HOLDER, loose], [], lambda target: None, None)

    assert _dropped_names(plan) == ["dorder_z", "dorder_a", "dorder_m"]


def test_a_chain_is_unwound_from_the_far_end() -> None:
    """Verifies the order is transitive: a -> b -> c drops c, then b, then a."""
    first = _table("dorder_one")
    second = _table("dorder_two", references="dorder_one")
    third = _table("dorder_three", references="dorder_two")
    plan = diff_schema([first, second, third], [], lambda target: None, None)

    assert _dropped_names(plan) == ["dorder_three", "dorder_two", "dorder_one"]


def test_a_table_pointing_at_itself_imposes_no_order() -> None:
    """Verifies a self-referencing FK (a tree) is not read as a cycle.

    `parent_id` on the same table is the commonest to-one there is. Treating its own edge as a
    dependency would make every category tree in the world un-droppable.
    """
    tree = _table("dorder_tree", references="dorder_tree", column="parent_id")
    plan = diff_schema([tree], [], lambda target: None, None)

    assert _dropped_names(plan) == ["dorder_tree"]


def test_a_cycle_between_two_dropped_tables_is_named() -> None:
    """Verifies a genuine cycle stops with the tables named instead of picking an order.

    Two tables pointing at each other cannot be ordered, and emitting either order gives SQL two
    engines reject. So it says so, the same way `_topological_order` does for views — and the way
    out is written: drop one of the keys first, in its own operation.
    """
    left = _table("dorder_left", references="dorder_right", column="right_id")
    right = _table("dorder_right", references="dorder_left", column="left_id")

    with pytest.raises(SnakeMigrationError) as error:
        diff_schema([left, right], [], lambda target: None, None)

    assert "dorder_left" in str(error.value)
    assert "dorder_right" in str(error.value)
    assert "DropForeignKey" in str(error.value)


def test_a_reference_to_a_table_that_survives_imposes_no_order() -> None:
    """Verifies only the tables INSIDE the drop set count, as everywhere else in this module.

    A key into a table that is not being dropped cannot constrain the order of the ones that are.
    """
    survivor = _table("dorder_kept")
    holder = _table("dorder_going", references="dorder_kept", column="kept_id")
    plan = diff_schema([survivor, holder], [survivor], lambda target: None, None)

    assert _dropped_names(plan) == ["dorder_going"]


# --- Applied against the real servers ------------------------------------------------------

_PROBES = ("dorder_z", "dorder_a")


@pytest.fixture
def postgres() -> Iterator[PsycopgDriver]:
    """Real Postgres with both probe tables clean before and after."""
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    _clean(connection, 'DROP TABLE IF EXISTS "{}" CASCADE')
    try:
        yield connection
    finally:
        _clean(connection, 'DROP TABLE IF EXISTS "{}" CASCADE')
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
    _clean(connection, "DROP TABLE IF EXISTS `{}`")
    try:
        yield connection
    finally:
        _clean(connection, "DROP TABLE IF EXISTS `{}`")
        connection.close()


def _clean(driver: SnakeDriver, template: str) -> None:
    """Drops the probes holder-first, which is the order this module is about."""
    for table in _PROBES:
        driver.execute(template.format(table), ())
    driver.commit()


def _build(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Creates both tables with the FK in place, referenced one first."""
    quote = dialect.quote_ident
    driver.execute(emit_create_table(_REFERENCED, dialect), ())
    driver.execute(emit_create_table(_HOLDER, dialect), ())
    driver.execute(
        f"ALTER TABLE {quote('dorder_z')} "
        f"ADD CONSTRAINT {quote('fk_dorder_z_dorder_a')} "
        f"FOREIGN KEY ({quote('parent_id')}) "
        f"REFERENCES {quote('dorder_a')} ({quote('id')})",
        (),
    )
    driver.commit()


@pytest.mark.integration
def test_the_wrong_order_really_is_refused_by_postgres(postgres: PsycopgDriver) -> None:
    """The control on Postgres: dropping the referenced table first is refused, right now."""
    _build(postgres, PostgresDialect())

    with pytest.raises(Exception) as error:  # noqa: B017 - the server raises its own
        postgres.execute('DROP TABLE "public"."dorder_a"', ())

    assert "depend" in str(error.value).lower()
    postgres.rollback()


@pytest.mark.integration
def test_the_wrong_order_really_is_refused_by_mariadb(mariadb: PyMySQLDriver) -> None:
    """The control on MariaDB: the same drop answers error 1451."""
    _build(mariadb, MySQLDialect())

    with pytest.raises(Exception) as error:  # noqa: B017 - the server raises its own 1451
        mariadb.execute("DROP TABLE `dorder_a`", ())

    assert "1451" in str(error.value) or "foreign key" in str(error.value).lower()


@pytest.mark.integration
def test_the_ordered_plan_applies_on_a_real_postgres(postgres: PsycopgDriver) -> None:
    """Verifies the plan the diff produces runs, in its own order, against Postgres."""
    _apply(postgres, PostgresDialect())


@pytest.mark.integration
def test_the_ordered_plan_applies_on_a_real_mariadb(mariadb: PyMySQLDriver) -> None:
    """Verifies the same plan runs against MariaDB, which is the engine that pays for it."""
    _apply(mariadb, MySQLDialect())


def _apply(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Builds both tables, runs the drop plan as it comes, and checks both are gone."""
    _build(driver, dialect)

    for operation in _drop_everything():
        for sql in operation.up_sql(dialect):
            driver.execute(sql, ())
    driver.commit()

    for table in _PROBES:
        rows = driver.fetch_all(
            "SELECT 1 FROM information_schema.tables WHERE table_name = "
            f"{dialect.placeholder(1)}",
            (table,),
        )
        assert not rows
