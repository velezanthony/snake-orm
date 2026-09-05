"""Two runs at once do NOT step on each other. Proved with a real server and a second process.

THIS IS THE NET THE WHOLE MECHANISM EXISTS FOR, and it is here rather than beside the naming rules
because nothing smaller can prove it. `test_session_database.py` proves two ids produce two strings,
which is necessary and says nothing about databases: the strings could still be resolved into one
connection — or into three — by anything downstream, and every assertion there would pass.

WHAT THE FIRST VERSION OF THIS FILE GOT WRONG, because it is the reason for how this one is built.
It ran the experiment on a base name of its own and had the child call `scoped(base, session)` by
hand. That is a SIMULATION of `open_session`, and it differed from the real thing in exactly the
place that was broken: the real one re-marks a name it has already written into `os.environ`, and
`scoped` was not idempotent, so every child was landing in `snakeorm_db__s41287__s41287` — a database
of its own, not its parent's. The suite went green through all of it (3095 passed, 24 skipped) and
this file's `test_a_subprocess_of_THIS_run_joins_it` passed too, while joining nothing. It was found
by looking at the SERVER and seeing a name with two suffixes.

So there are two rules here now, and both are the lesson:

1. The child calls `session_db.open_session()` — the same function `pytest_configure` calls. A net
   that re-implements what it is checking checks its own copy.
2. Both sides answer with `SELECT current_database()`, asked of Postgres. Neither process's own
   account of where it thinks it is counts for anything; the server is the only witness.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from collections.abc import Iterator

import pytest

from test import session_db
from test.conftest import NO_SERVER_REASON

_SRC = str(pathlib.Path(__file__).resolve().parents[2])
"""`src/`, so the child can import `test.session_db` the way the suite's own `pythonpath` does."""

MARKER = "session_isolation_marker"
"""An empty table this run leaves in its own database, so the question can be asked of the server.

Empty because a marker has nothing to carry. It goes in the REAL database and not in one built for
the occasion: a database made for the test is a database the test can be right about while the suite
is somewhere else entirely, which is precisely how the first version of this file passed.
"""

_CHILD = """
import sys
sys.path.insert(0, {src!r})
from test import session_db

session_db.open_session()

import psycopg2
from snakeorm.core.config import dsn_from_env

connection = psycopg2.connect(dsn_from_env(connect_timeout=2))
with connection.cursor() as cursor:
    cursor.execute("SELECT current_database()")
    print(cursor.fetchone()[0])
    cursor.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        ({marker!r},),
    )
    print(cursor.fetchone()[0])
connection.close()
"""
"""What the other run does: open a session the REAL way, then ask the server where it ended up.

`open_session()` and not a hand-rolled copy of it, and `current_database()` and not the name the
child computed — the two corrections that turn this file from a description of the mechanism into a
question about it.
"""


def _another_run(*, inherit: bool) -> tuple[str, int]:
    """Runs the child; answers with the database Postgres says it is in, and whether it sees MARKER.

    `inherit=True` leaves the environment alone, which is this suite starting a subprocess of its
    own. `inherit=False` clears EVERYTHING `open_session` writes — `session_db.REWRITTEN` — so the
    child starts from the `.env` exactly as somebody opening another terminal would.

    ALL OF THEM AND NOT JUST THE SESSION ID, which this file learned the hard way about ten minutes
    after `scoped` grew its refusal. Clearing only the id leaves `DB_NAME` still carrying the
    parent's mark while removing the thing that explains it, so the child claimed a session of its
    own and then met somebody else's mark — a state no real run can be in, and one `scoped` now
    stops rather than papers over. The net was describing a situation that does not exist and calling
    it "another run".
    """
    environment = dict(os.environ)
    if not inherit:
        for variable in session_db.REWRITTEN:
            environment.pop(variable, None)
    result = subprocess.run(  # noqa: S603 - fixed command, no user input
        [sys.executable, "-c", _CHILD.format(src=_SRC, marker=MARKER)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, f"the other run failed:\n{result.stderr}"
    where, sees_marker = result.stdout.split()
    return where, int(sees_marker)


def _ask_the_server(query: str) -> object:
    """One value, straight from Postgres over this run's own configured connection."""
    import psycopg2

    from snakeorm.core.config import dsn_from_env

    connection = psycopg2.connect(dsn_from_env(connect_timeout=2))
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
    finally:
        connection.close()
    assert row is not None
    return row[0]


@pytest.fixture()
def marked() -> Iterator[str]:
    """Leaves MARKER in THIS run's database and answers with the database's name, per the server.

    The name is asked of Postgres rather than read out of `DB_NAME`, for the same reason the child
    is: what is under test is where the connection actually goes, and the environment is the thing
    suspected of being wrong.
    """
    import psycopg2

    try:
        where = str(_ask_the_server("SELECT current_database()"))
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - environment dependent
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    connection = session_db.postgres_connection(where)
    assert connection is not None
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE TABLE IF NOT EXISTS {MARKER} (id integer)")
    finally:
        connection.close()
    try:
        yield where
    finally:
        closing = session_db.postgres_connection(where)
        if closing is not None:
            with closing.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {MARKER}")
            closing.close()


def test_the_suite_really_is_talking_to_its_own_database(marked: str) -> None:
    """The live connection reports a database carrying THIS run's session id.

    It goes first because everything else is meaningless without it: if `pytest_configure` never
    rewrote anything, both processes below would agree perfectly about the one database every run on
    this server shares, and the comparison would call that a pass.
    """
    session, _owned = session_db.claim()

    assert session_db.session_of(marked) == session, (
        f"the suite is connected to {marked!r}, which does not carry this run's session id "
        f"({session}). Every run on this server is back to sharing one database."
    )


def test_another_run_lands_in_another_database_and_cannot_see_this_one(
    marked: str,
) -> None:
    """Two sessions, two databases, and the other one cannot see this one's tables.

    The failure this repository has already met in red — `DuplicateTable`, `DeadlockDetected` — is
    the kind version of what happens when this is false. The unkind version is a suite going GREEN
    over a schema another run rebuilt underneath it, which is possible precisely because the seeds
    are deterministic: the rows found are the rows expected, and nothing says whose they were.
    """
    try:
        where, sees_marker = _another_run(inherit=False)

        assert where != marked, (
            f"another run landed in {where}, the same database as this one. Two suites are about to "
            f"drop and recreate the same tables, and the quiet outcome of that is a green run over "
            f"somebody else's schema."
        )
        assert sees_marker == 0, (
            f"the other run can see this run's {MARKER} table, so {where} and {marked} are not "
            f"separate databases whatever their names say"
        )
    finally:
        session_db.sweep_postgres()


def test_a_subprocess_of_THIS_run_lands_in_the_SAME_database(marked: str) -> None:
    """A child inherits the session and must end up in its PARENT's database. Names compared.

    THIS IS THE TEST THE DOUBLE-SUFFIX BUG SLIPPED PAST, and how it slipped past is worth keeping:
    the version before this one asked whether the child had DEMOLISHED the parent's database, and it
    had not — it had gone somewhere else entirely, which the question could not tell apart from
    behaving. `claim()` was doing its half correctly and `scoped` undid it by marking a name that was
    already marked.

    So the assertion is an EQUALITY between two `current_database()` answers, which is the one shape
    that has no room for "close enough". Verified by mutation: with `scoped` non-idempotent again,
    this goes red naming `snakeorm_db__s<pid>__s<pid>`.

    It matters far beyond this file. `test_ci_guard` starts eight `pytest` subprocesses and the CLI
    tests start more; every one of them inherits `SNAKEORM_SESSION_ID`. A child in a database of its
    own is a child provisioning, seeding and dropping a whole extra database per invocation, and
    finding none of the state the parent set up.
    """
    where, sees_marker = _another_run(inherit=True)

    assert where == marked, (
        f"a subprocess of this run ended up in {where!r} instead of its parent's {marked!r}. It "
        f"inherited the session id and then landed somewhere else anyway — which is what marking an "
        f"already-marked name does, and what nothing in this suite noticed for a whole session."
    )
    assert sees_marker == 1, (
        f"the child is in {where!r} and cannot see {MARKER}, which its parent created there. Either "
        f"it wiped the database its parent is using, or `current_database()` is agreeing about a "
        f"name while the two connections are elsewhere."
    )
