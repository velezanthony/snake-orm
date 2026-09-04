"""One database per test RUN, so two runs on one server cannot rewrite each other's schema.

THE PROBLEM, MEASURED. Every working session in this repository points at the same server and, on
Postgres, at the same database. `src/test` alone leaves sixty tables in `snakeorm_db`, and about
fifty of its files open with `DROP TABLE IF EXISTS ... CASCADE` followed by `CREATE TABLE` — among
them `scenarios/schema.py` and `scenarios/deep_domain.py`, which build the seeded graph ONCE per
session and are then read by fifty-odd scenario files. Two runs at a time means one of them drops
and reseeds those tables while the other is halfway through reading them.

**And the seed is deterministic, which is what makes it dangerous.** The loud outcomes —
`DuplicateTable`, `DeadlockDetected` — are the kind version and are already on record. The quiet one
is a suite that goes GREEN over a schema somebody else rebuilt underneath it, because the rows it
finds happen to be the rows it expected.

THE RULE. A run that owns a session id appends it to the name of every database it provisions:
`snakeorm_db` becomes `snakeorm_db__s41287`. Nothing else in the repository changes — the fifty
files keep their hardcoded table names, and `snakeorm.core.config` keeps returning exactly what
`DB_NAME` says. What moves is the VALUE of `DB_NAME`, rewritten once before collection, so every
reader downstream (the DSN builder, the CLI, a subprocess) is right without knowing this file
exists. A mitigation that asks fifty authors to remember something is the mitigation that already
failed.

`.env` STAYS THE ONE SOURCE FOR THE NAME, the same way it is the one source for the port. It
declares the BASE (`DB_NAME=snakeorm_db`); the suffix is derived, never declared a second time. If
`SNAKEORM_SESSION_ID` is unset AND unclaimed, there is no suffix at all: a dev server, a manual
`python -m examples.tour` or a `psql` session sees precisely the database it saw before.

CLEANUP IS A SWEEP AT THE START, NOT A DROP AT THE END, and the choice is deliberate. Dropping at
the end would destroy the populated database `scenarios/conftest.py` deliberately leaves behind for
somebody to inspect — and it would not even be a guarantee, since a run killed with `-9` never
reaches its own teardown. Sweeping at the start is a guarantee: the id carries the PID that owns it,
and a PID that is no longer alive is a database nobody is coming back for. Steady state is ONE
leftover database per base — the run you just finished, still there to poke at, collected by the
next run that starts.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

SESSION_VARIABLE = "SNAKEORM_SESSION_ID"
"""The one variable that says which run this is. Unset means "no isolation", which is a valid answer.

Set it by hand to pin a database across several runs (`SNAKEORM_SESSION_ID=spike uv run pytest`) and
it will be honoured verbatim. What a hand-written id costs is the sweep: see `sweepable`.
"""

MARK = "__s"
"""What separates a base name from a session id. Two underscores, and that is not decoration.

A single one is a character every base name in this repository already contains
(`snakeorm_db`, `shared_operations`, `django_demo`), so `_s12` would be indistinguishable from a
name somebody meant. The sweeper below DROPS things; it may only drop what it can recognise beyond
argument.
"""

_ID_PATTERN = re.compile(r"\A[A-Za-z0-9]{1,32}\Z")
"""What an id may look like: letters and digits, no more than thirty-two of them.

Narrow ON PURPOSE. The id ends up inside a database name, and a database name ends up inside DDL. A
hyphen would force quoting, a dot would read as a schema, and anything longer risks the 63-character
identifier ceiling Postgres enforces and MySQL mirrors at 64. Refusing is the whole answer here: an
id this file cannot spell is an id it must not sanitise into something the user did not write.
"""

_SCOPED_PATTERN = re.compile(
    rf"\A(?P<base>.+){re.escape(MARK)}(?P<session>[A-Za-z0-9]{{1,32}})\Z"
)
"""The same rule read backwards, so a name can be asked which session it belongs to."""


class SessionIdError(ValueError):
    """An id that cannot become part of a database name. Raised rather than trimmed to fit."""


def validated(session: str) -> str:
    """The id, or a refusal that names it back. There is no repair, and that is the point.

    Silently stripping the character it did not like would hand back a database name the person
    never wrote, and they would then go looking for the one they DID write. The same call
    `_strict_mode` makes about a boolean: an unreadable value stops the run instead of being guessed.
    """
    if not _ID_PATTERN.match(session):
        raise SessionIdError(
            f"{SESSION_VARIABLE}={session!r} cannot go in a database name: use between 1 and 32 "
            f"letters or digits, and nothing else. It is not trimmed to fit — you would be handed a "
            f"database with a name you never wrote."
        )
    return session


def scoped(name: str, session: str | None) -> str:
    """`name` as this run sees it. With no session, the name itself: no session, no isolation.

    A pure function of two strings, which is what lets the demo side hold its own copy and a test
    prove the two agree. It never reads the environment: the caller decides which id applies, and
    the caller is the only one who knows whether it is naming a database, a schema or a file.

    IT IS IDEMPOTENT, AND IT WAS NOT, AND THAT IS THE MOST EXPENSIVE THING IN THIS FILE'S HISTORY.
    `open_session` writes the finished name back into `os.environ` so every reader downstream is
    right without knowing any of this exists — which means a CHILD process reads a name that is
    already marked. Applied twice, this used to answer `snakeorm_db__s41287__s41287`, so the child
    landed in a database of its own after all. The `setdefault` in `claim()` did its half perfectly
    and the other half undid it: children did not demolish their parent's database, they simply
    stopped sharing it.

    **The whole suite stayed green through it — 3095 passed, 24 skipped**, because nothing anywhere
    compared the two names. It is the exact failure this module was written to close, committed by
    the module written to close it, and it was found by looking at the SERVER and seeing a name with
    two suffixes. That is what the net in `integration/test_session_database_isolation.py` now
    compares, and it is why that net asks Postgres `current_database()` on both sides instead of
    trusting either process's own account of where it is.

    A MARK BELONGING TO ANOTHER SESSION IS A REFUSAL, not a second suffix, and the two cases only
    look alike. Meeting this run's own mark means the name has already been through here — nothing
    to do. Meeting somebody else's means this process is holding a name from an environment that is
    not its own, and the only two ways to carry on are both wrong: nesting the marks invents a third
    database nobody owns, and replacing it steals a name that belongs to a run that may well be
    alive. So it stops and says whose name it found.
    """
    if session is None:
        return name
    validated(session)
    carried = session_of(name)
    if carried == session:
        return name
    if carried is not None:
        raise SessionIdError(
            f"{name!r} already carries session {carried!r} and this run is {session!r}. That is an "
            f"inherited name from somebody else's environment, not a name to mark again: nesting "
            f"the marks would invent a third database nobody owns, and replacing it would steal "
            f"one that may still be in use. Find out where {name!r} came from."
        )
    return f"{name}{MARK}{session}"


def session_of(name: str) -> str | None:
    """The session id inside a scoped name, or `None` if the name belongs to nobody.

    The inverse of `scoped`, and the sweeper's only way of telling a run's database apart from a
    database somebody created on purpose.
    """
    match = _SCOPED_PATTERN.match(name)
    return match.group("session") if match else None


def sweepable(session: str) -> bool:
    """Can this id be proved dead? Only a numeric one can, because only a PID has a heartbeat.

    A hand-written id (`spike`, `ci`) is never swept, and the asymmetry is honest rather than lazy:
    there is nothing to ask about it. Whoever pins an id owns its database, which is usually the
    reason they pinned one. The default id is the PID precisely so that the common case IS
    collectable without anybody arranging it.
    """
    return session.isdigit()


def _process_is_alive(pid: int) -> bool:
    """Is a process with this PID running? Anything unclear counts as ALIVE.

    Signal 0 checks for existence without delivering anything. `PermissionError` means the process is
    there and belongs to somebody else; any other `OSError` means this platform will not answer. Both
    lean the same way on purpose: this function's answer authorises a `DROP DATABASE`, so the only
    acceptable mistake is refusing to collect something collectable.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def is_orphan(name: str) -> bool:
    """Does this name belong to a run that has finished? Everything unrecognised says no.

    Three ways to answer no, and each one is a thing this must never delete: a name with no session
    mark (somebody's real database), a session id nobody can prove dead (a pinned id), and a PID that
    is still running (a suite in flight — quite possibly the one asking).
    """
    session = session_of(name)
    if session is None or not sweepable(session):
        return False
    return not _process_is_alive(int(session))


# ---- Opening the session ------------------------------------------------------------------------

ANALYTICS_DSN_VARIABLE = "SNAKEORM_DSN_ANALYTICS"
"""The second named connection, whose database is spelled inside a DSN instead of in a variable.

It is rewritten too, and only when it is already set. Creating it out of nothing would change what
happens on a machine that never configured a second connection — where `dsn_for('analytics')` says
so — from one behaviour into another, on a run that has nothing to do with this. CI does set it:
without it the model block of `multi-connection.md` cannot run.
"""

REPO_ROOT = Path(__file__).resolve().parents[2]
"""The repository root: `src/test` -> `src` -> here. Where the orphan SQLite files are swept from."""

SCOPED_NAME_VARIABLES: tuple[tuple[str, str], ...] = (
    ("DB_NAME", "snakeorm_db"),
    ("MYSQL_DB", "snakeorm_db"),
)
"""The variables that NAME a database, with the fallback each one has when the `.env` is silent."""

REWRITTEN: tuple[str, ...] = (
    SESSION_VARIABLE,
    *(variable for variable, _fallback in SCOPED_NAME_VARIABLES),
    ANALYTICS_DSN_VARIABLE,
)
"""Everything `open_session` writes into the environment. Published, because undoing it is a thing.

A process that wants to look like a FRESH run — somebody opening another terminal — has to clear all
of them, and clearing only the session id is not the same thing: it leaves the names marked while
removing the id that explains them, which `scoped` now refuses by name. The first version of
`test_session_database_isolation` cleared only the id and called the result "another run"; the
refusal is what told it otherwise. Derived from the table above rather than written out, so the
variable added last is not the one somebody forgets to clear.
"""


def open_session() -> tuple[str, bool]:
    """Points this run at a database of its own, creates it, and collects what dead runs left.

    Returns the session id and whether this process OPENED it. Called by `pytest_configure` before a
    single test is collected — by then a fixture asking for a connection has already read the name.

    IT IS A FUNCTION AND NOT A HOOK BODY for one reason: the net that proves a subprocess joins this
    run instead of wandering off calls THIS, so what it exercises is the real path. It used to be a
    private helper in `conftest.py` and the net simulated it by hand, which is how the double-suffix
    bug lived: the simulation passed a clean base name where the real thing passes an
    already-marked one, so the two disagreed exactly where it mattered and the net said nothing.

    THE ORDER IS THE ARGUMENT. `load_env()` first, because the base names come from the `.env` and
    without it the suffix would be appended to the built-in defaults instead. Then the id, then the
    rewrite, then the server work — every reader downstream, `dsn_from_env` and the CLI subprocesses
    included, sees a finished environment and never learns any of this happened.

    AND THE REWRITE IS RE-ENTRANT, which is the whole reason `scoped` is idempotent. A child process
    inherits an environment whose `DB_NAME` is ALREADY marked, so this function runs a second time
    over its own output. Marking twice produced `snakeorm_db__s41287__s41287` and sent every child
    to a database of its own; `scoped` now recognises its own mark and hands the name back untouched.

    NOTHING TEACHES THE LIBRARY ABOUT ANY OF THIS. The names go into `os.environ` as VALUES, so
    `snakeorm.core.config` stays exactly what it was: the one place that turns the environment into a
    DSN, answering faithfully about a `DB_NAME` that now happens to end in a session id. Teaching it
    to append a suffix would have made `DB_NAME` say one thing and the connection do another, which
    is the class of surprise this ORM exists not to commit.

    A MISSING SERVER IS NOT AN ERROR HERE. `ensure_*` answers False and the run carries on into the
    ordinary skips, which `SNAKEORM_REQUIRE_POSTGRES` already knows how to turn into failures. Two
    gates for one condition would only disagree.
    """
    from snakeorm.core.config import load_env

    load_env()
    session, owned = claim()

    for variable, fallback in SCOPED_NAME_VARIABLES:
        os.environ[variable] = scoped(os.environ.get(variable, fallback), session)
    analytics = os.environ.get(ANALYTICS_DSN_VARIABLE)
    if analytics is not None:
        os.environ[ANALYTICS_DSN_VARIABLE] = scoped_dsn(analytics, session)

    ensure_postgres(os.environ["DB_NAME"], fresh=owned)
    ensure_mysql(os.environ["MYSQL_DB"], fresh=owned)
    if analytics is not None:
        ensure_postgres(database_in(os.environ[ANALYTICS_DSN_VARIABLE]), fresh=owned)

    if owned:
        sweep_postgres()
        sweep_mysql()
        sweep_sqlite(REPO_ROOT)
    return session, owned


# ---- Claiming the id --------------------------------------------------------------------------


def claim() -> tuple[str, bool]:
    """This run's session id, and whether this process is the one that OPENED the session.

    The second half of the pair is what keeps a child process from demolishing its parent. `pytest`
    is run as a subprocess from inside this suite —`test_ci_guard` does it eight times— and a
    subprocess inherits the environment, so it inherits the id too. If provisioning went by "do I
    have an id?", every one of those children would DROP AND RECREATE the database its parent was
    in the middle of using.

    So the question is not what the id IS but where it came from. Inherited: adopt it, make sure the
    database exists, touch nothing else. Absent: claim it, and with it the right to start from a
    clean database and to sweep what earlier runs left behind.
    """
    inherited = os.environ.get(SESSION_VARIABLE)
    if inherited is not None:
        return validated(inherited.strip()), False
    mine = str(os.getpid())
    os.environ[SESSION_VARIABLE] = mine
    return mine, True


# ---- Postgres ---------------------------------------------------------------------------------


def _postgres_params() -> dict[str, str]:
    """Host, port, user and password for the server — everything except WHICH database.

    Off `DB_*`, the same variables `snakeorm.core.config` builds its DSN from, so there is no second
    place where the connection is described. `DB_NAME` is deliberately absent: this connects to the
    maintenance database, and asking for the one being created would be circular.
    """
    return {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": os.environ.get("DB_PORT", "5432"),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASSWORD", "snakeorm_pass"),
    }


_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", ""})
"""The hosts this file is allowed to sweep. A server it cannot prove is this machine's is left alone.

The sweep decides a database is abandoned by asking the LOCAL kernel about a PID. That question only
means something when the process and the server share a machine, which the compose file guarantees
(`127.0.0.1:${DB_PORT}:5432`) and a shared staging server would not. Against a remote host the PID
`41287` could easily belong to somebody else's live run, and the answer would be a `DROP DATABASE`.
"""


def _sweeping_is_safe() -> bool:
    """Is the server on this machine? Only then does a local PID say anything about it."""
    return _postgres_params()["host"].strip().lower() in _LOOPBACK


def _postgres_dsn(name: str) -> str:
    """A libpq keyword DSN for one database, assembled the way the rest of the repository does it.

    A STRING and not `**params`, and that is not a style choice: psycopg2's stub declares one keyword
    per parameter, so a `dict[str, str]` splatted into it matches no overload and needs a `type:
    ignore` to compile. `frameworks/shared/config.py` carries exactly that ignore and explains it.
    Here the DSN is what psycopg2 wants anyway, so there is nothing to suppress.

    `connect_timeout` is short for the same reason the whole suite keeps it short: without a server,
    provisioning has to give up in a second rather than hang before a single test is collected.
    """
    params = _postgres_params()
    return (
        f"host={params['host']} port={params['port']} user={params['user']} "
        f"password={params['password']} dbname={name} connect_timeout=2"
    )


def _connected_to(name: str) -> Any | None:
    """An autocommit connection to `name`, or `None` when there is no server to talk to.

    `None` and not an exception: a laptop with no docker is a supported way to run this suite, and it
    is not this file's job to decide that a missing server matters. The tests that need one already
    skip with the repository's phrase, and `SNAKEORM_REQUIRE_POSTGRES` is what turns that skip into a
    failure. Provisioning has no opinion to add.

    Autocommit because `CREATE DATABASE` and `DROP DATABASE` refuse to run inside a transaction.
    """
    try:
        import psycopg2
    except ImportError:  # pragma: no cover - the driver is an installed dependency
        return None

    try:
        connection = psycopg2.connect(_postgres_dsn(name))
    except psycopg2.Error:
        return None
    connection.autocommit = True
    return connection


def _postgres_maintenance() -> Any | None:
    """The connection that creates and drops databases: `postgres`, the one that always exists.

    A database cannot be created from inside itself, so provisioning needs somewhere else to stand.
    """
    return _connected_to("postgres")


def postgres_connection(name: str) -> Any | None:
    """An autocommit connection to ONE database, or `None` when the server is not there.

    The same parameters everything else uses, with the database named by the caller. It exists so
    the net that proves two runs land in two different databases can say so in the only way that
    counts — by connecting to both — without rebuilding the connection parameters beside it.
    """
    return _connected_to(name)


def _postgres_names(connection: Any) -> list[str]:
    """Every non-template database on the server, by name."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT datname FROM pg_database WHERE NOT datistemplate")
        return [row[0] for row in cursor.fetchall()]


def _quoted(name: str) -> str:
    """A database name as an identifier. Doubling the quote is what makes it safe to interpolate.

    DDL cannot take a parameter for an identifier, so this is the one place in the repository where a
    value reaches SQL as text — and it is reached only through `validated()`, which has already
    refused anything that is not a letter or a digit.
    """
    return '"' + name.replace('"', '""') + '"'


def ensure_postgres(name: str, *, fresh: bool) -> bool:
    """Make sure `name` exists; with `fresh`, make sure it is EMPTY. False when there is no server.

    `fresh` is the difference between opening a session and joining one. The process that claimed the
    id starts from nothing — a database inherited from a run that crashed halfway is exactly the
    stale schema this whole file is about. A process that joined only needs the database to be there.

    `WITH (FORCE)` because a previous run may have left a connection behind, and a `DROP DATABASE`
    that waits for it would hang the suite before it collected a single test.
    """
    connection = _postgres_maintenance()
    if connection is None:
        return False
    try:
        with connection.cursor() as cursor:
            if fresh:
                cursor.execute(f"DROP DATABASE IF EXISTS {_quoted(name)} WITH (FORCE)")
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone() is None:
                cursor.execute(f"CREATE DATABASE {_quoted(name)}")
    finally:
        connection.close()
    return True


def drop_postgres(name: str) -> None:
    """Removes one database, connections and all. Silent when there is no server to remove it from.

    The sweep is what GUARANTEES cleanup; this is for the net that has to make a mess on purpose and
    would rather not leave it lying around until the next run collects it.
    """
    connection = _postgres_maintenance()
    if connection is None:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS {_quoted(name)} WITH (FORCE)")
    finally:
        connection.close()


def sweep_postgres() -> list[str]:
    """DROPs every database whose session id belongs to a process that is gone. Returns their names.

    It sweeps by SHAPE and not by a list of bases, which is the whole reason one sweeper is enough
    for a repository with five suites: `snakeorm_db__s41287`, `shared_operations__s41287` and
    `flask_demo__s41287` are all recognised by the same pattern, so a suite that never runs a sweep
    of its own still gets collected. A list of bases would need extending every time a suite is
    added, and the one that gets forgotten is always the newest.
    """
    if not _sweeping_is_safe():
        return []
    connection = _postgres_maintenance()
    if connection is None:
        return []
    dropped: list[str] = []
    try:
        for name in _postgres_names(connection):
            if not is_orphan(name):
                continue
            with connection.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS {_quoted(name)} WITH (FORCE)")
            dropped.append(name)
    finally:
        connection.close()
    return dropped


# ---- MySQL ------------------------------------------------------------------------------------


def _mysql_params() -> dict[str, str]:
    """The MySQL server, off the `MYSQL_*` names the e2e tests and the demos already read."""
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": os.environ.get("MYSQL_PORT", "3306"),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
    }


def _mysql_connection() -> Any | None:
    """A connection to the MySQL server with no database selected, or `None` if there is none.

    `MYSQL_HOST` unset means "this machine has no MySQL", which is how the SQLite leg of CI is
    configured on purpose. Nothing to provision, nothing to complain about.
    """
    if not os.environ.get("MYSQL_HOST"):
        return None
    try:
        import pymysql
    except ImportError:  # pragma: no cover - the driver is an optional extra
        return None

    params = _mysql_params()
    try:
        return pymysql.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            password=params["password"],
            connect_timeout=2,
        )
    except Exception:  # noqa: BLE001 - pymysql raises its own hierarchy; any of them means "no server"
        return None


def _backquoted(name: str) -> str:
    """A MySQL identifier. Same reasoning as `_quoted`, with the character MySQL uses."""
    return "`" + name.replace("`", "``") + "`"


def ensure_mysql(name: str, *, fresh: bool) -> bool:
    """The MySQL half of `ensure_postgres`. In MySQL a database IS what others call a schema."""
    connection = _mysql_connection()
    if connection is None:
        return False
    try:
        with connection.cursor() as cursor:
            if fresh:
                cursor.execute(f"DROP DATABASE IF EXISTS {_backquoted(name)}")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {_backquoted(name)}")
        connection.commit()
    finally:
        connection.close()
    return True


def sweep_mysql() -> list[str]:
    """The MySQL half of `sweep_postgres`, over `information_schema.schemata`."""
    if not _sweeping_is_safe():
        return []
    connection = _mysql_connection()
    if connection is None:
        return []
    dropped: list[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT schema_name FROM information_schema.schemata")
            names = [str(row[0]) for row in cursor.fetchall()]
            for name in names:
                if not is_orphan(name):
                    continue
                cursor.execute(f"DROP DATABASE IF EXISTS {_backquoted(name)}")
                dropped.append(name)
        connection.commit()
    finally:
        connection.close()
    return dropped


# ---- SQLite -----------------------------------------------------------------------------------

_SQLITE_SIDECARS = ("", "-wal", "-shm")
"""A SQLite database is up to three files, and leaving two of them behind is leaving a database."""


def sweep_sqlite(root: Path) -> list[str]:
    """Deletes every `*__s<pid>.sqlite` under `root` whose PID is gone. Returns their paths.

    It walks the tree ENTIRE and does not take a list of directories, which is a lesson this
    repository has already paid for: the language nets were written against a list of roots that left
    out `examples/` and `benchmarks/`, and nine files went through a whole migration unlooked-at.
    Whatever holds the demo databases tomorrow is covered today.
    """
    deleted: list[str] = []
    for path in sorted(root.rglob(f"*{MARK}*.sqlite")):
        if not is_orphan(path.stem):
            continue
        for suffix in _SQLITE_SIDECARS:
            companion = path.with_name(path.name + suffix)
            if companion.exists():
                companion.unlink()
        deleted.append(str(path))
    return deleted


# ---- The DSN of the named `analytics` connection ------------------------------------------------

_DBNAME_IN_DSN = re.compile(r"(?<=\bdbname=)(?P<name>\S+)")
"""`dbname=x` inside a libpq keyword DSN, which is the form the `.env` template ships."""

_DBNAME_IN_URL = re.compile(r"\A(?P<head>\w+://[^/]*/)(?P<name>[^/?#]+)(?P<tail>.*)\Z")
"""`postgresql://host/x`, the other form libpq accepts. Both are handled; a third is refused."""


def database_in(dsn: str) -> str:
    """The database a DSN names, in either accepted form. A DSN that names none RAISES.

    The reader half of `scoped_dsn`, so provisioning asks the DSN what it points at instead of
    recomputing the name beside it. Two computations of one name are two things to keep in step, and
    they only ever get out of step in the direction that leaves a run connected somewhere unexpected.
    """
    keyword = _DBNAME_IN_DSN.search(dsn)
    if keyword is not None:
        return keyword.group("name")
    url = _DBNAME_IN_URL.match(dsn)
    if url is not None:
        return url.group("name")
    raise SessionIdError(
        f"this DSN names no database that can be given a session of its own: {dsn!r}. Write it as "
        f"`... dbname=NAME ...` or as `postgresql://host/NAME`. It is not passed through untouched, "
        f"because that would leave one database shared between runs with nothing saying so."
    )


def scoped_dsn(dsn: str, session: str | None) -> str:
    """The same DSN pointing at this run's copy of its database. An unreadable DSN RAISES.

    This exists for `SNAKEORM_DSN_ANALYTICS`, the second named connection, which is the one surface
    the `DB_NAME` rewrite cannot reach: its database is spelled inside a full DSN rather than in a
    variable of its own. Leaving it alone would have left one shared table —`shop_visits`, dropped
    and recreated by `test_full_flow_e2e`— on a mechanism that claims to have closed the sharing.

    A DSN in neither form stops the run instead of being handed back untouched. Returning it
    unchanged is the failure this whole module exists to prevent, wearing a helpful face: the run
    would carry on, quietly sharing the one database nobody thought to check.
    """
    if session is None:
        return dsn
    wanted = scoped(database_in(dsn), session)
    keyword = _DBNAME_IN_DSN.search(dsn)
    if keyword is not None:
        return _DBNAME_IN_DSN.sub(wanted, dsn, count=1)
    url = _DBNAME_IN_URL.match(dsn)
    assert url is not None, f"database_in accepted a DSN this cannot rewrite: {dsn!r}"
    return f"{url.group('head')}{wanted}{url.group('tail')}"
