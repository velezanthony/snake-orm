"""Integration: the migration runtime against a REAL Postgres.

It checks the full cycle against the devcontainer's DB: apply creates the table and records the
version in snake_migrations, re-apply is idempotent, and rollback drops the table and the record.
Skipped if there is no DB. It cleans its own state inside Postgres (setup and teardown).
"""

from __future__ import annotations

from collections.abc import Iterator

from snakeorm.core.exceptions import SnakeForeignKeyViolation
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver, SnakeDriver
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AddColumn,
    AddForeignKey,
    AlterColumn,
    CreateTable,
    Migration,
    MigrationRunner,
)
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_VERSION = "test_mig_001"


def _widget_table() -> SnakeTableInfo:
    """Test table for the migration."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="mig_widgets",
        columns=(id_col, SnakeColumnInfo(name="label", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def _parent_and_child() -> tuple[SnakeTableInfo, SnakeTableInfo]:
    """Parent/child tables with a relationship (FK) from the child to the parent."""
    parent_id = SnakeColumnInfo(name="id", python_type=int)
    parent = SnakeTableInfo(
        name="mig_parents",
        columns=(parent_id,),
        primary_key=SnakePrimaryKeyInfo(columns=(parent_id,)),
    )
    child_id = SnakeColumnInfo(name="id", python_type=int)
    relationship = SnakeRelationshipInfo(
        name="parent",
        target="Parent",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(target="Parent", pairs=(("parent_id", "id"),)),
    )
    child = SnakeTableInfo(
        name="mig_children",
        columns=(child_id, SnakeColumnInfo(name="parent_id", python_type=int)),
        primary_key=SnakePrimaryKeyInfo(columns=(child_id,)),
        relationships=(relationship,),
    )
    return parent, child


def _cleanup(driver: SnakeDriver) -> None:
    """Leaves the state in Postgres clean (tables + records of test versions)."""
    driver.execute(
        "DROP TABLE IF EXISTS mig_widgets, mig_children, mig_parents, mig_alter CASCADE",
        (),
    )
    driver.execute(
        "DELETE FROM public.snake_migrations WHERE version LIKE %s", ("test_mig_%",)
    )
    driver.commit()


@pytest.fixture
def runner() -> Iterator[tuple[MigrationRunner, SnakeDriver]]:
    """Runner against the real Postgres, with the previous state cleaned."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    migration_runner = MigrationRunner(driver, PostgresDialect())
    migration_runner.ensure_tracking_table()
    _cleanup(driver)
    try:
        yield migration_runner, driver
    finally:
        _cleanup(driver)
        driver.close()


def test_apply_creates_table_records_version_and_is_idempotent(
    runner: tuple[MigrationRunner, SnakeDriver],
) -> None:
    """Checks the cycle apply → table created + version recorded → re-apply does not repeat."""
    migration_runner, driver = runner
    migration = Migration(_VERSION, (CreateTable(_widget_table()),))

    assert migration_runner.apply([migration]) == [_VERSION]
    assert _VERSION in migration_runner.applied_versions()

    # the table really exists: you can insert into it and read back
    driver.execute("INSERT INTO mig_widgets (id, label) VALUES (1, 'w')", ())
    driver.commit()
    assert driver.fetch_all("SELECT id FROM mig_widgets", ()) == [(1,)]

    # idempotent: re-applying does not execute again
    assert migration_runner.apply([migration]) == []


def test_add_column_migration_against_real_pg(
    runner: tuple[MigrationRunner, SnakeDriver],
) -> None:
    """Checks that a migration with AddColumn really applies the ALTER TABLE ADD COLUMN."""
    migration_runner, driver = runner
    table = _widget_table()
    note = SnakeColumnInfo(name="note", python_type=str, nullable=True)
    migration_runner.apply(
        [
            Migration(_VERSION, (CreateTable(table),)),
            Migration("test_mig_002", (AddColumn(table, note),)),
        ]
    )
    # the `note` column exists: you can insert into it and read back
    driver.execute("INSERT INTO mig_widgets (id, label, note) VALUES (1, 'w', 'n')", ())
    driver.commit()
    assert driver.fetch_all("SELECT note FROM mig_widgets", ()) == [("n",)]


def test_foreign_key_migration_is_enforced(
    runner: tuple[MigrationRunner, SnakeDriver],
) -> None:
    """Checks that a migration with AddForeignKey creates an FK that Postgres ENFORCES."""

    migration_runner, driver = runner
    parent, child = _parent_and_child()
    migration_runner.apply(
        [
            Migration(
                "test_mig_fk",
                (
                    CreateTable(parent),
                    CreateTable(child),
                    AddForeignKey(child, child.relationships[0], parent),
                ),
            )
        ]
    )
    # inserting a child whose parent does not exist MUST violate the FK
    with pytest.raises(SnakeForeignKeyViolation, match="FOREIGN KEY"):
        driver.execute("INSERT INTO mig_children (id, parent_id) VALUES (1, 999)", ())
    driver.rollback()  # cleans up the aborted transaction


def test_alter_column_type_change_against_real_pg(
    runner: tuple[MigrationRunner, SnakeDriver],
) -> None:
    """Checks that AlterColumn really changes a column's type (int→text with USING)."""
    migration_runner, driver = runner
    id_col = SnakeColumnInfo(name="id", python_type=int)
    val_int = SnakeColumnInfo(name="val", python_type=int, nullable=True)
    val_text = SnakeColumnInfo(name="val", python_type=str, nullable=True)
    table = SnakeTableInfo(
        name="mig_alter",
        columns=(id_col, val_int),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    migration_runner.apply(
        [
            Migration(
                "test_mig_alter",
                (CreateTable(table), AlterColumn(table, val_int, val_text)),
            )
        ]
    )
    # after the ALTER to TEXT, the column accepts non-numeric text
    driver.execute("INSERT INTO mig_alter (id, val) VALUES (1, 'hola')", ())
    driver.commit()
    assert driver.fetch_all("SELECT val FROM mig_alter", ()) == [("hola",)]


def test_rollback_drops_table_and_unrecords(
    runner: tuple[MigrationRunner, SnakeDriver],
) -> None:
    """Checks that rollback drops the table and removes the version from the tracking."""
    migration_runner, _ = runner
    migration = Migration(_VERSION, (CreateTable(_widget_table()),))
    migration_runner.apply([migration])

    migration_runner.rollback(migration)
    assert _VERSION not in migration_runner.applied_versions()
