"""The whole migration cycle on the THREE engines: apply, record, run data, revert.

The migrations were exercised end to end on each engine in a DIFFERENT file — Postgres in
`test_full_flow_e2e.py`, MySQL in `test_mysql_e2e.py`, SQLite in `test_sqlite_migrations.py` — and
three files that answer the same question separately is how one of them quietly stops asking it.
That is not hypothetical here: `test_sqlite_migrations.py` exists because migrations did not work on
SQLite AT ALL, and the first statement of the cycle was the one that failed.

So the cycle is one file now, parametrised, and it asks the four things a runner has to get right on
every engine: the tracking table exists, a migration applies ONCE, a `RunPython` runs the ORM inside
the same transaction as the schema change, and going back really goes back.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.migration import CreateTable, Migration, MigrationRunner, RunPython
from test.scenarios.engines import DIALECTS, three_drivers

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="mcyc_notes")
class Note(SnakeModel):
    """The table the migration creates, and the model its data half writes through."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    body: SnakeColumn[str] = snake_str(max_length=50)


_TABLE = snake_table(Note)
_SCHEMA = Migration(version="0001_schema", operations=(CreateTable(_TABLE),))


def _seed(session: SnakeSession) -> None:
    """The forward half, written through the ORM — which is the whole point of `RunPython`.

    Module level and not a lambda: the renderer writes these BY REFERENCE, so a closure could never
    be written back out into a migration file.
    """
    session.add(Note(id=1, body="seeded"))


def _unseed(session: SnakeSession) -> None:
    """The backward half. Without it the migration is not reversible and `unrun` says so plainly."""
    session.delete_where(SnakeQuery(Note).filter(Note.id == 1))


Stand = dict[str, tuple[MigrationRunner, SnakeSession]]


@pytest.fixture
def runners(tmp_path: pathlib.Path) -> Iterator[Stand]:
    """A runner per engine over a driver with NO tables: the migration is what creates them.

    The session comes back alongside it, built over the SAME driver, so a test can read the rows the
    data half wrote without reaching into the runner's private one.

    SQLite gets a file rather than `:memory:` so the runner and that session share one database.
    """
    with three_drivers([], sqlite_path=str(tmp_path / "cycle.db")) as drivers:
        made = {
            name: (
                MigrationRunner(driver, DIALECTS[name]),
                SnakeSession(driver, DIALECTS[name]),
            )
            for name, driver in drivers.items()
        }
        try:
            yield made
        finally:
            for driver in drivers.values():
                driver.execute(f"DROP TABLE IF EXISTS {_TABLE.name}", ())
                driver.execute("DROP TABLE IF EXISTS snake_migrations", ())
                driver.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_tracking_table_is_created_on_every_engine(
    engine: str, runners: Stand
) -> None:
    """The bare minimum, and exactly what was once broken on one engine of three.

    `_table_ref()` used to build `"public"."snake_migrations"` by hand instead of going through
    `qualified()`, so the very first statement answered `unknown database "public"` on SQLite. One
    place left out of twenty-five was enough.
    """
    runner, session = runners[engine]

    runner.ensure_tracking_table()

    assert runner.applied_versions() == set()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_migration_applies_once_and_is_recorded(engine: str, runners: Stand) -> None:
    """Applied the first time, a no-op the second. Idempotence is the runner's whole contract."""
    runner, session = runners[engine]

    assert runner.apply([_SCHEMA]) == ["0001_schema"]
    assert runner.applied_versions() == {"0001_schema"}
    assert runner.apply([_SCHEMA]) == [], "the second run applied it again"


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_data_migration_runs_the_orm_inside_the_same_transaction(
    engine: str, runners: Stand
) -> None:
    """A `RunPython` gets a session over the SAME driver, so its writes are atomic with the schema.

    That is the point of handing it a session rather than a connection: the data lands or the whole
    migration does not, and a half-migrated table is worse than an unmigrated one.
    """
    runner, session = runners[engine]
    data = Migration(
        version="0002_data",
        operations=(RunPython(forward=_seed, backward=_unseed),),
    )

    runner.apply([_SCHEMA, data])

    assert runner.applied_versions() == {"0001_schema", "0002_data"}


@pytest.mark.parametrize("engine", _ENGINES)
def test_reverting_a_data_migration_puts_it_back(engine: str, runners: Stand) -> None:
    """Going back really goes back, and the record goes with it.

    Checking only that the version disappeared would pass on a runner that forgot the `backward`
    entirely — so the ROWS are read, which is the half that says the code ran.
    """
    runner, session = runners[engine]
    data = Migration(
        version="0002_data",
        operations=(RunPython(forward=_seed, backward=_unseed),),
    )
    runner.apply([_SCHEMA, data])

    runner.rollback(data)

    assert runner.applied_versions() == {"0001_schema"}
    assert session.count(SnakeQuery(Note)) == 0, (
        "the backward half did not run: the seeded row survived the rollback"
    )
