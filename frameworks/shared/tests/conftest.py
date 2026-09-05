"""Harness for the shared-domain tests: an in-memory SQLite session, and a real Postgres when asked.

MOST of this suite runs against SQLite `:memory:` (no docker, no files): the schema, the seed and the
test's queries share ONE connection, so the in-memory DB does not evaporate between steps. The driver
is wrapped in `CaptureDriver` so the debug report (duplicates, timings) can be inspected from inside
the test.

SOME of it cannot, and that is the second half of this file. Row locking and savepoints are not
things one connection can demonstrate: a `FOR UPDATE` only means something when somebody else is
already holding the row, and SQLite has no row locks at all — it answers `Nope` and the emitter
raises rather than pretending. So the operations of the `orders` domain get TWO sessions over TWO
connections to a real Postgres, on a database of their own.

WHY A DATABASE OF ITS OWN. The three demos each have theirs and this suite now has a fourth,
`shared_operations`. Sharing one is how a run comes up green over a schema that belongs to somebody
else — the failure mode this repository has already met in red, and the red one is the kind version.

AND WHY THE SKIP IS NOT SILENT. Without a server these tests skip, which is right on the laptop of
somebody poking at the compiler and exactly wrong in CI, where a skip means the infrastructure failed
and the suite covered it up. `SNAKEORM_REQUIRE_POSTGRES` turns such a skip into a failure. The hook is
written out again here rather than imported: `src/test/conftest.py` owns the same net for the ORM's
own suite, but the two are separate pytest runs with separate roots and no importable module between
them. What is shared is the PHRASE, which is what makes both nets recognise a skip for want of a
server, and it is repeated verbatim for that reason.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Generator, Iterator
from typing import Any

import pytest
from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeSession,
    SQLiteDialect,
    SQLiteDriver,
    snake_table,
)
from snakeorm.debug import CaptureDriver
from snakeorm.drivers import SnakeDriver
from snakeorm.migration import emit_create_index, emit_create_table, emit_create_view

from shared.config import postgres_dsn
from shared.data import Scale, seed
from shared.models import MODELS, VIEWS
from shared.session import claim, scoped

# `SnakeWarning` IS NOT SILENCED HERE, and it used to be — by category, for the whole suite.
#
# The session announcing one caveat per thing the engine cannot do is this ORM's headline behaviour:
# what an engine does not give, it DECLARES. Ignoring the category left that behaviour verified
# NOWHERE across the four demo suites, while `shared/` genuinely branches on what the engine can do.
# What the silence bought, measured: nineteen lines in the WHOLE run — the warning fires once per
# (engine, caveat) per PROCESS, not per session and not per test.
#
# `test_the_session_says_what_the_engine_cannot_do.py` is what turned that silence into a tally.

SESSION = claim()
"""Opens this run's working session, before anything below reads a database name.

At module scope and not in a fixture, because `POSTGRES_DATABASE` two lines down is computed at
import time. `claim()` is `setdefault`, so a run started from another run — `make frameworks-test`,
CI — inherits the session it was started in instead of pointing somewhere else.
"""

# The database the two-connection tests own. Not one of the three demos': a suite that borrows
# another one's schema is a suite that can pass over a schema that has moved underneath it.
#
# AND NOT ANOTHER RUN OF ITSELF EITHER, which is what the session id closes. Owning a name was never
# the same as owning a database: two runs of THIS file, at once, both drop and recreate the same
# twenty-nine tables and then `TRUNCATE` them before every test — so one of them is emptying tables
# the other is mid-way through reading. The seed is deterministic, so the counts usually still add
# up, and that is the quiet version of the failure the paragraph above describes in its loud one.
POSTGRES_DATABASE = scoped(
    os.environ.get("SHARED_DB_NAME", "shared_operations"), SESSION
)

NO_SERVER_REASON = "Postgres is not reachable"
"""The phrase the WHOLE repository announces a skip for lack of a server with.

Verbatim from `src/test/conftest.py`, where `test_ci_guard` pins it for the ORM's suite. A file that
invents its own wording drops out of the net without saying so, and the net is the only thing
standing between "297 skipped" and somebody believing the run proved something.
"""

_STRICT_VARIABLE = "SNAKEORM_REQUIRE_POSTGRES"
_TRUE, _FALSE = "true", "false"
"""ONE spelling per side, the same contract `src/test/conftest.py` states for the ORM's suite.

THE PARSER IS DUPLICATED, and the copy now has a net over it. The docstring at the top of this file
explains that the HOOK is written out again —two pytest runs, two roots, nothing importable
between them— and says what is shared is the PHRASE. The parser was shared too, by copy, and it
drifted the way copies do: the ORM's side was fixed and this one still read `off` as ON.

SHARING THE SOURCE WAS LOOKED AT AND REFUSED, on the layout. `test` is importable in the ORM's run
only because `[tool.pytest.ini_options] pythonpath = ["src"]` puts it there, and hatchling keeps it
out of the wheel on purpose. Importing it from here would mean pointing this suite's `pythonpath` at
the ORM's test tree — the demos, which exist to show what somebody gets from the PUBLISHED package,
would stop building on the published package alone.

So the copy stays and `test_both_strict_gates_read_the_same_switch.py` proves the two say the same
thing: same variable name, same accepted values, same treatment of `off`/`0`/`no`, and the same
sentence back. It reaches the ORM's parser by PATH, which is a thing a test may do and the layout
may not. Drift stops being a matter of somebody remembering.
"""


def _fresh_session() -> SnakeSession:
    """Creates the whole demo schema on an in-memory SQLite and returns the session (captured).

    THE SHAPE IS `MODELS` + `VIEWS` AND IT IS NOT COUNTED HERE. This line said "26-table" while the
    docstring twelve lines up said "the same twenty-nine tables" and `postgres_schema` below said
    "29 tables per test" — three figures for one schema, in one file, and the domain has grown
    since. The number that matters is `len(MODELS)`, which the loop below walks; writing it down
    again only creates a second place for it to be wrong.

    THE INDEXES COME TOO, and they used to not. This builder emitted tables and views while
    `postgres_schema` twelve lines below emitted tables, INDEXES and views — two schemas from one
    metadata graph, differing in the half that enforces things. Most of this suite runs here, so
    "most of this suite" ran against a schema with no unique constraint anywhere in it: a test
    asserting that the database refuses a duplicate would have gone green without the database
    having any opinion at all.
    """
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    for model in MODELS:
        table = snake_table(model)
        driver.execute(emit_create_table(table, dialect), ())
        for index in table.indexes:
            driver.execute(emit_create_index(table, index, dialect), ())
    # The views LAST: they read from the tables, so the tables have to be there first.
    for view in VIEWS:
        driver.execute(emit_create_view(snake_table(view), dialect), ())
    driver.commit()
    return SnakeSession(CaptureDriver(driver), dialect)


@pytest.fixture()
def make_session() -> Callable[[], SnakeSession]:
    """Factory of fresh sessions (schema created, no data): for tests that need TWO DBs."""
    return _fresh_session


@pytest.fixture()
def session() -> Iterator[SnakeSession]:
    """A session with the schema created but WITHOUT data (for tests that seed to taste)."""
    db = _fresh_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def seeded() -> Iterator[SnakeSession]:
    """A session with the schema created and seeded at MINIMAL scale (the common one in the tests)."""
    db = _fresh_session()
    seed(db, Scale.MINIMAL)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session")
def postgres_schema() -> str:
    """A real Postgres carrying the demo schema, built ONCE for the run. Returns its DSN.

    Dropping and recreating 29 tables per test would cost more than the tests do; per RUN it is
    invisible, and each test starts from an empty database anyway because `postgres_pair` truncates.

    It is also the only place the skip happens. If there is no server, every test that asks for two
    sessions skips with the repository's phrase and the rest of the suite carries on — which is the
    behaviour that lets somebody without docker still run the domain half.
    """
    import psycopg2

    try:
        dsn = postgres_dsn(POSTGRES_DATABASE)
        driver = PsycopgDriver.connect(dsn)
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - environment dependent
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    dialect = PostgresDialect()
    try:
        # The views FIRST: a view reads from tables, and Postgres refuses to DROP TABLE one.
        for view in VIEWS:
            driver.execute(
                f"DROP VIEW IF EXISTS {dialect.quote_ident(snake_table(view).name)}", ()
            )
        for model in reversed(MODELS):
            driver.execute(
                f"DROP TABLE IF EXISTS {dialect.quote_ident(snake_table(model).name)}",
                (),
            )
        for model in MODELS:
            table = snake_table(model)
            driver.execute(emit_create_table(table, dialect), ())
            for index in table.indexes:
                driver.execute(emit_create_index(table, index, dialect), ())
        for view in VIEWS:
            driver.execute(emit_create_view(snake_table(view), dialect), ())
        driver.commit()
    finally:
        driver.close()
    return dsn


def _truncate_everything() -> str:
    """One `TRUNCATE` over every table, sequences reset, so each test starts from nothing.

    One statement and not twenty-nine: `TRUNCATE a, b, c` is atomic and takes its locks together,
    while a loop of deletes leaves the database half-empty for as long as it runs — which is visible
    to the other connection these tests hold open.

    `RESTART IDENTITY` because the ids are what the assertions compare, and a test that passes only
    while it runs first is a test that will fail the day somebody adds one above it.
    """
    dialect = PostgresDialect()
    names = ", ".join(dialect.quote_ident(snake_table(model).name) for model in MODELS)
    return f"TRUNCATE {names} RESTART IDENTITY CASCADE"


@pytest.fixture()
def postgres_drivers(postgres_schema: str) -> Iterator[tuple[SnakeDriver, SnakeDriver]]:
    """TWO connections to the same real Postgres, on an empty schema. The raw drivers.

    Two CONNECTIONS, which is the whole reason this fixture exists: a lock only means something when
    somebody else holds it, and two sessions over one connection are the same transaction wearing two
    names. It is the same shape `src/test/integration/test_concurrency_e2e.py` uses, for the same
    reason.

    The drivers are handed out and not only the sessions because a test that wants to prove a lock
    has to be able to say `SET statement_timeout` — an instrument of the test on the test's own
    connection, not something the operations under test know about. Without it, proving that a
    reservation WAITS means waiting for ever.
    """
    first = PsycopgDriver.connect(postgres_schema)
    second = PsycopgDriver.connect(postgres_schema)
    first.execute(_truncate_everything(), ())
    first.commit()
    try:
        yield (first, second)
    finally:
        for driver in (second, first):
            driver.rollback()
            driver.close()


@pytest.fixture()
def postgres_pair(
    postgres_drivers: tuple[SnakeDriver, SnakeDriver],
) -> tuple[SnakeSession, SnakeSession]:
    """The two connections above as two sessions, both with NO transaction in flight.

    That last part is a precondition and not an accident: the operations under test declare their
    isolation level as their first statement, and Postgres refuses `SET TRANSACTION` once a
    connection has been touched.
    """
    first, second = postgres_drivers
    return (
        SnakeSession(first, PostgresDialect()),
        SnakeSession(second, PostgresDialect()),
    )


def _strict_from_value(raw: str | None) -> bool:
    """The PARSER, over a value somebody hands it. Unset is off, `true`/`false` decide, rest RAISES.

    There is no default for a typo on purpose: reading an unknown value as on hides a switch
    somebody meant to turn off, and reading it as off hides the very skips this net exists to make
    loud. Neither is safe, so neither is chosen.

    IT TAKES THE VALUE INSTEAD OF GOING TO GET IT, which is the whole reason it is a function of its
    own. This is a duplicated parser (see `_STRICT_VARIABLE`), so it has a test comparing it against
    the ORM's — and while reading the environment was part of it, that test could only ask a question
    by WRITING the live switch. It did, with the invalid values it is supposed to check, and the hook
    below read one of them mid-test: `ValueError`, INTERNALERROR, the whole session dead, whatever
    the database was doing. Split, the parser answers about a string and nobody has to poison a
    process to interrogate it.

    THE SENTENCE IS THE ORM'S, WORD FOR WORD, with only the variable name interpolated. It was not:
    this copy said "It is not guessed either way — " where the ORM says "It is not guessed either
    way, and that is deliberate — ", the same complaint in two wordings. This project already paid
    for that on the sync/async seam and answered it with a test that compares the MESSAGE and not
    only the behaviour; the gate parser had the identical crack and no such test.
    """
    value = (raw or "").strip().lower()
    if value == "":
        return False
    if value in (_TRUE, _FALSE):
        return value == _TRUE
    raise ValueError(
        f"{_STRICT_VARIABLE}={value!r} is not a boolean: write {_TRUE!r} or {_FALSE!r}, or leave it "
        f"unset. It is not guessed either way, and that is deliberate — reading it as on would hide "
        f"a switch you meant to turn off, and reading it as off would hide the very skips this net "
        f"exists to make loud."
    )


def _strict_mode() -> bool:
    """Is this an environment where a skip for lack of a database is a FAILURE?

    Reads the switch and hands it to the parser above; the whole decision lives there. Kept as its
    own name because the hook below reads better for it, and because the two halves fail for
    different reasons: this one can only be wrong about WHICH variable, and that one about what a
    value means.
    """
    return _strict_from_value(os.environ.get(_STRICT_VARIABLE))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: Any
) -> Generator[None, None, None]:
    """Turns a skip for want of a database into a FAILURE where the database had to be there.

    It acts on the REPORT and not on the execution, deliberately: the test has already skipped and
    there is nothing left to re-run. What has to be fixed is the verdict, which is the only part
    anybody reads. And it triggers on the REASON rather than on the file, so a two-connection test
    written tomorrow in another file is covered without its author knowing this exists.
    """
    result = yield
    if not _strict_mode():
        return
    report = result.get_result()  # type: ignore[attr-defined]
    if not (report.skipped and NO_SERVER_REASON in str(report.longrepr)):
        return
    report.outcome = "failed"
    report.longrepr = (
        f"{item.nodeid} was SKIPPED for want of a database, and with {_STRICT_VARIABLE} "
        f"active that is a failure.\n\nOriginal reason: {report.longrepr}\n\n"
        f"A skip here does not mean the operations are right: it means Postgres was not there and "
        f"the suite covered for it. Check the DB service and DB_HOST / DB_PORT / DB_USER / "
        f"DB_PASSWORD in the repository's .env."
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Removes the database this run created. The ORM suite's sweep is for the runs that crash.

    A run that ends normally cleans up after itself. Relying only on the sweep — which lives in
    `src/test/session_db.py` and collects abandoned databases by shape at the start of every ORM
    run — means anybody working only on this layer accumulates one database per run until they
    happen to type `uv run pytest`. Measured while this was being built: three runs of
    `make frameworks-test-shared` left three `shared_operations__s<pid>` databases standing.

    It drops `POSTGRES_DATABASE` and nothing else, and that name always carries this run's session
    id — `claim()` above guarantees there is one — so the shared `shared_operations` of somebody who
    predates this mechanism is not what gets dropped.

    A missing server is silent: `drop_pg_database` returns rather than raising, because a teardown
    complaining that there was no database is a teardown reporting the situation the whole suite
    already skipped for.
    """
    from shared.config import drop_pg_database

    drop_pg_database(POSTGRES_DATABASE)
