"""The FULL migration cycle against the second engine, for real and end to end.

This file was born of an uncomfortable discovery: migrations **did not work on SQLite**. Not one
bit. The very first statement —creating the tracking table— answered `unknown database "public"`
because `_table_ref()` built `"public"."snake_migrations"` by hand instead of going through
`qualified()`, which exists precisely for that and centralised twenty-five places. This one was
left out, and one was enough.

And nobody caught it because **every** migration test used a Postgres dialect. Having two engines
and testing the runner against a single one is having half a runner tested; which is, once again,
the "implemented in N-1 of N siblings" pattern this project keeps paying for.

The whole cycle is exercised —apply, be idempotent, undo— because an engine without transactional
DDL walks a DIFFERENT path through the runner (`_apply_stepwise`, not `_apply_atomic`), and no test
was exercising that path.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import SQLiteDialect, SQLiteDriver
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AddForeignKey,
    CreateTable,
    Migration,
    MigrationRunner,
)

_ID = SnakeColumnInfo(name="id", python_type=int)
_AUTHORS = SnakeTableInfo(
    name="mig_autores",
    columns=(_ID, SnakeColumnInfo(name="name", python_type=str)),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
)
_RELATION = SnakeRelationshipInfo(
    name="autor",
    target="Autor",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="Autor", pairs=(("autor_id", "id"),)),
    target_table="public.mig_autores",
)
_BOOKS = SnakeTableInfo(
    name="mig_libros",
    columns=(_ID, SnakeColumnInfo(name="autor_id", python_type=int)),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    relationships=(_RELATION,),
)
_MIGRATION = Migration(
    version="0001_inicial",
    operations=(
        CreateTable(_AUTHORS),
        CreateTable(_BOOKS),
        AddForeignKey(_BOOKS, _RELATION, _AUTHORS),
    ),
)


@pytest.fixture
def connected() -> Iterator[tuple[MigrationRunner, SQLiteDriver]]:
    """A runner and ITS driver: the base is `:memory:`, so asking it takes the SAME connection."""
    driver = SQLiteDriver.connect(":memory:")
    try:
        yield MigrationRunner(driver, SQLiteDialect()), driver
    finally:
        driver.close()


@pytest.fixture
def runner(connected: tuple[MigrationRunner, SQLiteDriver]) -> MigrationRunner:
    """The runner on its own, for the tests that need no look at the database themselves."""
    return connected[0]


def test_the_tracking_table_can_be_created_at_all(runner: MigrationRunner) -> None:
    """The bare minimum, and exactly what was broken: SQLite has no schema called `public`."""
    runner.ensure_tracking_table()

    assert runner.applied_versions() == set()


def test_a_full_migration_applies_against_sqlite(runner: MigrationRunner) -> None:
    """A migration with tables and a foreign key applies whole and gets recorded."""
    applied = runner.apply([_MIGRATION])

    assert applied == ["0001_inicial"]
    assert runner.applied_versions() == {"0001_inicial"}


def test_applying_twice_does_nothing_the_second_time(runner: MigrationRunner) -> None:
    """`apply` is IDEMPOTENT: the second pass does not re-run a `CREATE TABLE`, which would kill
    the deploy.

    On SQLite it matters twice over: with no transactional DDL, a failure halfway is NOT undone
    on its own.
    """
    runner.apply([_MIGRATION])

    assert runner.apply([_MIGRATION]) == []


def test_the_foreign_key_survived_the_migration(
    connected: tuple[MigrationRunner, SQLiteDriver],
) -> None:
    """The FK the plan asked for exists in the database: `realize` put it inside the `CREATE TABLE`.

    It closes the circle with `test_inline_foreign_keys.py`: there the emitter is checked, and here
    that the RUNNER —the one that lands the plan— gets to the same place.
    """
    runner, driver = connected
    runner.apply([_MIGRATION])

    keys = driver.fetch_all('PRAGMA foreign_key_list("mig_libros")', ())

    assert len(keys) == 1


def test_rolling_back_undoes_it_and_forgets_the_version(
    runner: MigrationRunner,
) -> None:
    """The reverse undoes it and forgets the version, so applying it again is possible."""
    runner.apply([_MIGRATION])

    runner.rollback(_MIGRATION)

    assert runner.applied_versions() == set()
    assert runner.apply([_MIGRATION]) == ["0001_inicial"], (
        "and it can be re-applied cleanly"
    )
