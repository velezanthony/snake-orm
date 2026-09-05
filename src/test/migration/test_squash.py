"""Squash: collapsing N migrations into one, with `replaces=[...]`.

A long history is paid for on every `makemigrations` (it has to be replayed whole) and on every
fresh deployment. Collapsing it is easy; the hard part is that the database where the originals were
ALREADY applied must not run them again.

Hence the `replaces`, which is the important half and the one the plan had left undesigned:

- if ALL the migrations it replaces are applied, the squash is marked as applied WITHOUT running
  anything (the database is already in that state),
- if NONE of them is, it runs as usual (a fresh installation),
- if SOME are and others are not, it STOPS. That in-between state cannot be resolved by guessing:
  neither running the squash (it would repeat what is done) nor marking it (it would skip what is
  missing).

The other sharp edge is the collapse itself: the DATA operations (`RunPython`, `RunSQL`) have a
no-op `apply_to_state`, so they cannot be merged without running them. Crossing one is refused, out
loud.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    AddColumn,
    CreateTable,
    DropColumn,
    Migration,
    RunSQL,
)
from snakeorm.migration.squash import squash

_ID = SnakeColumnInfo(name="id", python_type=int)
_EMAIL = SnakeColumnInfo(name="email", python_type=str)
_NICKNAME = SnakeColumnInfo(name="apodo", python_type=str, nullable=True)


def _table(*columns: SnakeColumnInfo) -> SnakeTableInfo:
    """The `users` table with the given columns."""
    return SnakeTableInfo(
        name="users",
        columns=(_ID, *columns),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


def _history() -> list[Migration]:
    """Three schema migrations: create, add a column, drop it."""
    return [
        Migration("0001_inicial", (CreateTable(_table(_EMAIL)),)),
        Migration("0002_apodo", (AddColumn(_table(_EMAIL, _NICKNAME), _NICKNAME),)),
        Migration("0003_sin_apodo", (DropColumn(_table(_EMAIL), _NICKNAME),)),
    ]


def test_it_collapses_to_the_final_state() -> None:
    """The squash emits the FINAL state, not the sum of the steps.

    The `apodo` column was added and then dropped, so it does not exist at the end and must not show
    up: a squash that replicated the steps would not be a squash, it would be a copy.
    """
    result = squash(_history(), version="0004_squash")

    creation = result.operations[0]
    assert [type(op).__name__ for op in result.operations] == ["CreateTable"]
    assert isinstance(creation, CreateTable)
    assert [column.name for column in creation.table.columns] == ["id", "email"]


def test_it_records_what_it_replaces() -> None:
    """The squash declares whom it replaces: that is what allows deciding at `migrate` time."""
    result = squash(_history(), version="0004_squash")

    assert result.replaces == ("0001_inicial", "0002_apodo", "0003_sin_apodo")


def test_it_refuses_to_cross_a_data_operation() -> None:
    """A DATA migration cannot be collapsed: its `apply_to_state` is a no-op.

    Merging it would require RUNNING it, and the squash is a desk operation that does not touch the
    database. It stops and says which one, instead of losing it along the way — which would leave an
    apparently correct squash and a set of unmigrated data.
    """
    history = [
        *_history(),
        Migration("0004_datos", (RunSQL(up=("UPDATE users SET email = ''",)),)),
    ]

    with pytest.raises(SnakeMigrationError, match="0004_datos"):
        squash(history, version="0005_squash")


def test_squashing_nothing_is_refused() -> None:
    """Collapsing an empty list makes no sense and is said, instead of emitting an empty migration."""
    with pytest.raises(
        SnakeMigrationError, match="squash needs at least one migration to collapse"
    ):
        squash([], version="0001_squash")


class _FakeDriver:
    """Driver that notes down the executed SQL and fakes the tracking table.

    A double is enough: what gets checked here is WHAT the runner decides to run, not what Postgres
    does with it. The E2E against the engine goes separately.
    """

    def __init__(self, applied: set[str]) -> None:
        self.applied = applied
        self.executed: list[str] = []

    def execute(self, sql: str, params: object = ()) -> int:
        """Records the SQL; if it is the tracking INSERT, notes the version down as applied."""
        self.executed.append(sql)
        if "INSERT INTO" in sql and "snake_migrations" in sql:
            self.applied.add(str(params[0]))  # type: ignore[index]
        return 1

    def fetch_all(self, sql: str, params: object = ()) -> list[tuple[object, ...]]:
        """Returns the applied versions when asked about the tracking."""
        return [(version,) for version in sorted(self.applied)]

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        """There is no transaction to commit in the double."""

    def rollback(self) -> None:
        """Nor one to undo."""


def _run(applied: set[str]) -> _FakeDriver:
    """Applies the history + its squash on a database with `aplicadas` already recorded."""
    from snakeorm import PostgresDialect
    from snakeorm.migration import MigrationRunner

    history = _history()
    plan = [*history, squash(history, version="0004_squash")]
    driver = _FakeDriver(set(applied))
    MigrationRunner(driver, PostgresDialect()).apply(plan)  # type: ignore[arg-type]
    return driver


def test_a_fresh_database_runs_the_squash_and_skips_the_originals() -> None:
    """FRESH installation: the squash runs and the originals are not even looked at.

    It is the cheap half: one table instead of three steps, which is exactly what collapsing is for.
    """
    driver = _run(applied=set())

    # It is filtered by the domain table: the runner also creates its own tracking one.
    creates = [sql for sql in driver.executed if 'CREATE TABLE "public"."users"' in sql]
    assert len(creates) == 1, "a single creation: that of the final state"
    assert "0004_squash" in driver.applied
    assert "0002_apodo" not in driver.applied, "the replaced ones are not applied"


def test_an_up_to_date_database_marks_the_squash_without_running_it() -> None:
    """UP-TO-DATE database: the squash is marked as applied and NOTHING is run.

    It is the whole reason `replaces` exists. Without it, the squash would attempt a `CREATE TABLE`
    on a table that already exists and the deployment would die with `DuplicateTable`.
    """
    driver = _run(applied={"0001_inicial", "0002_apodo", "0003_sin_apodo"})

    assert not [sql for sql in driver.executed if '"public"."users"' in sql], (
        "the DB is already in that state: the squash must run NOTHING"
    )
    assert "0004_squash" in driver.applied


def test_a_half_applied_history_stops_instead_of_guessing() -> None:
    """IN-BETWEEN state: it stops. There is no correct answer to be guessed.

    Running the squash would repeat what is already done; marking it would skip what is missing.
    Both options corrupt, so the tool says what it sees and lets the human decide.
    """
    from snakeorm import PostgresDialect
    from snakeorm.migration import MigrationRunner

    history = _history()
    plan = [*history, squash(history, version="0004_squash")]
    driver = _FakeDriver({"0001_inicial"})

    with pytest.raises(
        SnakeMigrationError, match="replaces a history that was applied HALF-WAY"
    ):
        MigrationRunner(driver, PostgresDialect()).apply(plan)  # type: ignore[arg-type]


def test_the_replaces_survives_the_round_trip(tmp_path: object) -> None:
    """The `replaces` has to reach THE FILE, or the squash is worth nothing.

    It is the piece the runner reads to decide whether to run it or mark it. A squash written
    without it is a loose `CREATE TABLE` that will kill the first deployment on a migrated database.
    """
    from snakeorm.migration.render import render_migration

    result = squash(_history(), version="0004_squash")
    source = render_migration(result.version, result.operations, result.replaces)

    namespace: dict[str, object] = {}
    exec(compile(source, "0004_squash.py", "exec"), namespace)  # noqa: S102
    rebuilt = namespace["migration"]

    assert rebuilt.replaces == result.replaces  # type: ignore[attr-defined]


def test_a_normal_migration_does_not_grow_a_replaces_block() -> None:
    """A normal migration is written EXACTLY as before: with no `replaces` block."""
    from snakeorm.migration.render import render_migration

    source = render_migration("0001_inicial", (CreateTable(_table(_EMAIL)),))

    assert "replaces" not in source


def test_it_keeps_the_functions_of_the_history() -> None:
    """A FUNCTION declared in the history has to survive the collapse.

    The replay rebuilds two things —tables and routines— and the first squash only looked at the
    tables. Result: a fresh installation ended up WITHOUT functions and nobody said a word. It is
    the same failure this whole branch is after, this time in the code that closes it: a schema
    object that vanishes in silence.
    """
    from snakeorm.metadata import SnakeRoutineInfo
    from snakeorm.migration import CreateFunction

    routine = SnakeRoutineInfo(
        name="sq_fn",
        body="CREATE FUNCTION sq_fn() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql",
    )
    history = [*_history(), Migration("0004_fn", (CreateFunction(routine),))]

    result = squash(history, version="0005_squash")

    kinds = [type(op).__name__ for op in result.operations]
    assert "CreateFunction" in kinds, f"the function was lost: {kinds}"


def test_functions_come_after_the_tables() -> None:
    """The order matters: a function may query a table, so it goes AFTERWARDS.

    It is the same criterion `autodetect` already uses (tables → FKs → views → functions). If the
    squash inverted it, a function referencing a table would fail on creation.
    """
    from snakeorm.metadata import SnakeRoutineInfo
    from snakeorm.migration import CreateFunction

    routine = SnakeRoutineInfo(
        name="sq_fn",
        body="CREATE FUNCTION sq_fn() RETURNS int AS $$ SELECT count(*) FROM users $$ LANGUAGE sql",
    )
    history = [*_history(), Migration("0004_fn", (CreateFunction(routine),))]

    kinds = [
        type(op).__name__ for op in squash(history, version="0005_squash").operations
    ]

    assert kinds.index("CreateTable") < kinds.index("CreateFunction")


def test_the_squash_carries_EVERY_collection_the_autodetect_diffs() -> None:
    """What a squash re-emits is derived from `SchemaState`, not from a list somebody maintains.

    A squash is the replayed final state emitted from nothing, so anything the state HOLDS and the
    squash does not RE-EMIT is silently dropped from the collapsed history — a fresh install ends up
    without it and nothing says a word.

    It had already happened once, with the routines, and the fix was to add a line. So the same bug
    was sitting one line further down for the triggers: `squash()` diffed tables and routines, and
    `SchemaState` also holds `triggers()`. `[CreateTable, CreateFunction, CreateTrigger]` collapsed
    into two operations.

    Which is why this compares the two CALLERS instead of asserting that a trigger survives. Both
    `autodetect` and `squash` turn a state into operations and must cover the same collections; the
    test that only checked the routines is the one that let the triggers through, because it was
    written the day the routines were fixed and knew only about them. Comparing the callers means
    the next collection added to `SchemaState` fails here on its own, without anyone remembering.
    """
    import inspect

    from snakeorm.migration import autodetect as autodetect_module
    from snakeorm.migration import squash as squash_module

    def diffs_called(module: object) -> set[str]:
        """The `diff_*` functions a module's source actually calls."""
        source = inspect.getsource(module)  # type: ignore[arg-type]
        return {
            name
            for name in ("diff_schema", "diff_routines", "diff_triggers")
            if f"{name}(" in source
        }

    del_autodetect = diffs_called(autodetect_module)
    del_squash = diffs_called(squash_module)

    assert del_squash == del_autodetect, (
        f"autodetect diffs {sorted(del_autodetect)} and squash diffs {sorted(del_squash)}. "
        f"Whatever the squash does not re-emit is dropped from the collapsed history in silence: "
        f"missing here are {sorted(del_autodetect - del_squash)}."
    )
