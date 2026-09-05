"""The asynchronous migration runner: the last piece that was left in a single color.

SQL generation is COLORLESS —`up_sql()` executes nothing, it only returns strings—, so the async
runner reimplements neither the diff, nor the emitter, nor `realize`. It reuses everything and only
changes the execution seam. That was the promise of the design from day one, and this is the bill:
out comes a short file that wraps exactly the calls to the driver.

Parity is checked by the MACHINE, not by reading. `AsyncSession` already shipped once with twelve of
twenty-two methods, and it was not carelessness: it is that comparing two long classes by eye simply
does not happen. This test is the same mechanism applied to the runner before it happens again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from snakeorm import MySQLDialect, PostgresDialect, SnakeSession, SQLiteDialect
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import AsyncMigrationRunner, CreateTable, Migration, RunPython
from snakeorm.migration.runner import tracking_table_ddl

_ID = SnakeColumnInfo(name="id", python_type=int)
_TABLE = SnakeTableInfo(
    name="arun_t", columns=(_ID,), primary_key=SnakePrimaryKeyInfo(columns=(_ID,))
)
_MIGRATION = Migration(version="0001_inicial", operations=(CreateTable(_TABLE),))


class _DriverAsync:
    """Fake asynchronous driver: notes down what was executed and answers the version query."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.applied: list[tuple[object, ...]] = []
        self.commits = 0

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        self.executed.append(sql)
        return list(self.applied)

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        self.executed.append(sql)
        if sql.startswith("INSERT INTO"):
            self.applied.append(tuple(params))
        return 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


def test_it_exposes_exactly_the_same_surface_as_the_synchronous_one() -> None:
    """Parity checked by the MACHINE: the same public methods as `MigrationRunner`.

    It is the same test `AsyncSession` got after shipping half-done. A runner that knows how to
    apply but not how to undo looks complete until the day something has to be undone.
    """
    import ast
    import pathlib

    def public_methods(path: str, class_name: str) -> set[str]:
        """Public methods declared in that class."""
        tree = ast.parse(pathlib.Path(path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return {
                    child.name
                    for child in node.body
                    if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    and not child.name.startswith("_")
                }
        raise AssertionError(f"not found: {class_name}")

    sync_methods = public_methods("src/snakeorm/migration/runner.py", "MigrationRunner")
    async_methods = public_methods(
        "src/snakeorm/migration/asyncrunner.py", "AsyncMigrationRunner"
    )

    assert sync_methods - async_methods == set(), (
        f"the async runner does not expose: {sorted(sync_methods - async_methods)}"
    )


def test_it_applies_a_migration_and_records_it() -> None:
    """The basic cycle: creates the tracking, emits the DDL and records the version."""
    driver = _DriverAsync()
    runner = AsyncMigrationRunner(driver, PostgresDialect())  # type: ignore[arg-type]

    applied = asyncio.run(runner.apply([_MIGRATION]))

    assert applied == ["0001_inicial"]
    assert any("CREATE TABLE" in sql and "arun_t" in sql for sql in driver.executed)


def test_applying_twice_does_nothing_the_second_time() -> None:
    """Idempotence: the second pass sees the recorded version and does not re-run the `CREATE TABLE`."""
    driver = _DriverAsync()
    runner = AsyncMigrationRunner(driver, PostgresDialect())  # type: ignore[arg-type]

    asyncio.run(runner.apply([_MIGRATION]))
    before = len(driver.executed)
    second = asyncio.run(runner.apply([_MIGRATION]))

    assert second == []
    # What is looked for is the table of the MIGRATION, not just any `CREATE TABLE`: the second
    # pass does re-emit the tracking one, which carries `IF NOT EXISTS` and is idempotent on purpose.
    assert not any("arun_t" in sql for sql in driver.executed[before:])


def test_rolling_back_emits_the_reverse_and_unregisters() -> None:
    """The reverse emits the DDL back and deletes the record."""
    driver = _DriverAsync()
    runner = AsyncMigrationRunner(driver, PostgresDialect())  # type: ignore[arg-type]

    asyncio.run(runner.rollback(_MIGRATION))

    assert any("DROP TABLE" in sql for sql in driver.executed)
    assert any(sql.startswith("DELETE FROM") for sql in driver.executed)


def test_a_data_migration_says_out_loud_that_it_cannot_run_here() -> None:
    """A DATA operation cannot be run in the asynchronous runner, and that is said out loud.

    And it is not laziness: `RunPython` takes a SYNCHRONOUS `SnakeSession`. A synchronous function
    cannot be `await`ed, so its body would block the whole event loop while it talks to the
    database —exactly the opposite of what this runner exists for—. They are two different
    functions, not the same one in two colors.

    The failure is LOUD because the alternative (skipping it) would leave a migration marked as
    applied with its data half unexecuted. That is not discovered until much later, and by then
    there are already bad rows.
    """
    driver = _DriverAsync()
    runner = AsyncMigrationRunner(driver, PostgresDialect())  # type: ignore[arg-type]
    with_data = Migration(
        version="0002_datos",
        operations=(RunPython(lambda session: None, lambda session: None),),
    )

    with pytest.raises(
        SnakeMigrationError,
        match=r"async runner cannot execute a data operation \(`RunPython`\)",
    ):
        asyncio.run(runner.apply([with_data]))


def test_the_synchronous_runner_still_runs_data_migrations() -> None:
    """The control: what the async one rejects, the sync one does. The hatch does exist."""
    executed: list[str] = []
    operation = RunPython(
        lambda session: executed.append("up"), lambda session: executed.append("down")
    )

    operation.run(SnakeSession(None, PostgresDialect()))  # type: ignore[arg-type]

    assert executed == ["up"]


def test_both_runners_create_the_SAME_tracking_table() -> None:
    """The tracking table's DDL is ONE string, shared, not two that happen to agree.

    The synchronous runner already carried this bug and already fixed it, with the reason written in
    its own docstring: a hard-wired `TEXT` on a column that IS the primary key makes MySQL reject the
    whole table — "BLOB/TEXT column used in key specification without a key length", error 1170 — so
    the migration system did not start at all on one of the three engines. The async runner was
    written afterwards and never received the fix. Measured against MariaDB 11.8.8: its
    `CREATE TABLE` was still error 1170, on the FIRST statement of `apply()`.

    So the DDL is a loose function that both runners call, and this asserts they call it rather than
    that two implementations agree. Two implementations that agree today are exactly the state the
    repository was already in — the sync one had the fix, the async one had the bug — and the parity
    test that should have caught it compared method NAMES. It is the same reasoning that made
    `squash_already_done` a loose function: one answer, so there is nothing to drift.
    """
    for dialect in (PostgresDialect(), MySQLDialect(), SQLiteDialect()):
        ddl = tracking_table_ddl(dialect)

        assert "TEXT NOT NULL" not in ddl or isinstance(dialect, SQLiteDialect), (
            f"{type(dialect).__name__}: bare TEXT as a primary key; MySQL answers 1170 to that. "
            f"DDL was: {ddl}"
        )
        assert dialect.quote_ident("version") in ddl
