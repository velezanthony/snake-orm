"""`.env` config: picks the engine and builds each framework's session.

A single place for the three demos. With `DB_BACKEND=sqlite|postgres|mysql` in the root `.env`, all
three run against any of the THREE engines — which is the whole demonstration: the same domain, the
same selectors and the same endpoints, changing one variable.

Each framework uses its OWN database (`<FRAMEWORK>_DB_NAME`), created on the fly if missing; on
SQLite, its own file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from snakeorm import (
    AsyncSession,
    AsyncSnakePool,
    MySQLDialect,
    PostgresDialect,
    PsycopgDriver,
    PyMySQLDriver,
    SnakeSession,
    SQLiteDialect,
    SQLiteDriver,
    snake_table,
)
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.contrib import open_session_async
from snakeorm.core.exceptions import SnakeConfigError, SnakePoolTimeout
from snakeorm.dialects import SnakeDialect
from snakeorm.debug import AsyncCaptureDriver, CaptureDriver
from snakeorm.drivers import AsyncDriver, SnakeDriver
from snakeorm.migration import emit_create_index, emit_create_table, emit_create_view

from shared.models import MODELS, VIEWS
from shared.session import current as current_session
from shared.session import scoped

_FRAMEWORKS_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _FRAMEWORKS_DIR.parent

# Loads the .env at the ROOT of the repo: a single one for the ORM and the three demos (without
# overriding variables already present in the real environment).
load_dotenv(_REPO_ROOT / ".env")


_BACKENDS = ("sqlite", "postgres", "mysql")


def backend() -> str:
    """The engine chosen in the `.env`: `sqlite` (default), `postgres` or `mysql`.

    An unknown name STOPS, instead of falling back to SQLite. Before, anything that was not
    "postgres" ended up on SQLite, so a `DB_BACKEND=postgress` with one extra s brought the demo up
    against a local file and everything looked like it worked — which is exactly the silent failure
    this ORM exists not to commit.
    """
    chosen = os.environ.get("DB_BACKEND", "sqlite").strip().lower()
    if chosen not in _BACKENDS:
        raise SnakeConfigError(
            f"DB_BACKEND='{chosen}' is not a known engine. The three are: "
            f"{', '.join(_BACKENDS)}."
        )
    return chosen


def make_dialect() -> SnakeDialect:
    """The dialect that matches the engine. Stateless value object: one per app is enough."""
    chosen = backend()
    if chosen == "postgres":
        return PostgresDialect()
    if chosen == "mysql":
        return MySQLDialect()
    return SQLiteDialect()


def db_system_name() -> str:
    """What OpenTelemetry calls the engine in use (`db.system.name`), for the `otel` channel.

    It comes off `SnakeBackend`, which is the ORM's single home for engine identity, so the demos do
    not invent a second spelling.
    """
    return _BACKENDS_BY_NAME[backend()].db_system_name


_BACKENDS_BY_NAME = {
    "sqlite": SnakeBackend.SQLITE,
    "postgres": SnakeBackend.POSTGRES,
    "mysql": SnakeBackend.MYSQL,
}


def _sqlite_path(framework: str) -> Path:
    """SQLite file per framework: frameworks/<framework>/<framework>.sqlite.

    Under a test session the file carries the session id too, so the three engines behave the same
    way rather than two of them being isolated and the third quietly shared. On SQLite a FILE is what
    the other two call a database, and leaving it out would have made "one database per run" a
    promise that held on two engines out of three.
    """
    name = scoped(framework, current_session())
    return _FRAMEWORKS_DIR / framework / f"{name}.sqlite"


def _pg_dbname(framework: str) -> str:
    """The framework's DB name: `<FRAMEWORK>_DB_NAME` or `<framework>_demo`, plus the session.

    The variable still declares the BASE and stays the only place the name is written down; the
    session id is derived from `SNAKEORM_SESSION_ID` and never declared a second time. With no
    session set — a dev server, a `make seed` — this returns exactly what it always returned.

    `config/settings.py` in the Django demo applies the SAME rule to the SAME variable rather than
    reading a name from here, because it runs before `django.setup()` and cannot afford this module's
    imports. Both go through `shared.session`, so there is one rule and two callers, not two rules.
    """
    return scoped(
        os.environ.get(f"{framework.upper()}_DB_NAME", f"{framework}_demo"),
        current_session(),
    )


def _pg_params() -> dict[str, str]:
    """Postgres connection using the SAME names the ORM uses (`DB_*`): a single set of variables
    serves the ORM and the three demos. The DB name comes from `_pg_dbname` per framework, so
    `DB_NAME` (the ORM's DB) does not apply here. Defaults = the project docker (published on `DB_PORT`)."""
    return {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": os.environ.get("DB_PORT", "5432"),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASSWORD", "snakeorm_pass"),
    }


def _ensure_pg_database(name: str) -> None:
    """Creates the framework database if it does not exist (CREATE DATABASE cannot run in a transaction)."""
    import psycopg2

    params = _pg_params()
    # `**params` is `dict[str, str]` and psycopg2's stub declares one keyword per parameter, so
    # it cannot match a mapping against its overloads. The call is correct; the stub cannot say so.
    conn = psycopg2.connect(dbname="postgres", **params)  # type: ignore[call-overload]
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{name}"')
    finally:
        conn.close()


def drop_pg_database(name: str) -> None:
    """Removes one Postgres database, connections and all. Silent when there is no server.

    `WITH (FORCE)` because a suite that has just finished may still have a connection in flight, and
    a `DROP DATABASE` that waits for it would hang the run at its very last step — the worst place
    for a teardown to hang, since everything it was protecting has already passed.
    """
    import psycopg2

    params = _pg_params()
    try:
        conn = psycopg2.connect(dbname="postgres", **params)  # type: ignore[call-overload]
    except psycopg2.OperationalError:
        return
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        conn.close()


def close_session(framework: str) -> None:
    """Removes the database this RUN created for `framework`, on whichever engine it was created.

    WHY A TEARDOWN AND NOT ONLY THE SWEEP. `src/test/session_db.py` collects abandoned databases at
    the start of every ORM run, by shape, which covers a suite that crashed and covers this side too.
    What it does NOT cover is somebody who only ever runs the demos: measured while building this,
    three runs of `frameworks-test-shared` left three `shared_operations__s<pid>` databases standing,
    because nothing between them ever swept. A run that finishes normally cleans up after itself; the
    sweep is what happens when it does not get the chance.

    NOTHING IS DROPPED OUTSIDE A SESSION, which is the guard that matters. With no session id the
    name is the demo's real database — the one `make flask-dev` serves and `make seed` filled — and
    dropping it because a test run ended would be a far worse bug than the leak this prevents.
    """
    if current_session() is None:
        return
    chosen = backend()
    if chosen == "sqlite":
        path = _sqlite_path(framework)
        for suffix in ("", "-wal", "-shm"):
            companion = path.with_name(path.name + suffix)
            if companion.exists():
                companion.unlink()
        return
    if chosen == "postgres":
        drop_pg_database(_pg_dbname(framework))
        return
    import pymysql

    params = _mysql_params()
    conn = pymysql.connect(
        host=params["host"],
        port=int(params["port"]),
        user=params["user"],
        password=params["password"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{_pg_dbname(framework)}`")
        conn.commit()
    finally:
        conn.close()


def postgres_dsn(name: str) -> str:
    """The DSN of ONE Postgres database, created if it is missing. Same `DB_*` variables as everything else.

    `raw_driver` cannot serve this and the difference is not cosmetic. It builds the driver the demos
    use, which means it follows `DB_BACKEND`: with the `.env` on SQLite it would hand back a file, and
    a concurrency test would run against an engine that answers `Nope` to row locking and go green
    having locked nothing. What the operations suite needs is TWO connections to a REAL Postgres,
    whatever the demos happen to be pointed at today.

    `connect_timeout` is short on purpose, the same way `src/test` does it: without a server the test
    has to skip in a second, not hang for the driver's default.
    """
    _ensure_pg_database(name)
    params = _pg_params()
    return (
        f"host={params['host']} port={params['port']} user={params['user']} "
        f"password={params['password']} dbname={name} connect_timeout=2"
    )


def _mysql_params() -> dict[str, str]:
    """MySQL connection using the same names the ORM e2e tests use (`MYSQL_*`)."""
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": os.environ.get("MYSQL_PORT", "3306"),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
    }


def _ensure_mysql_database(name: str) -> None:
    """Creates the framework database if missing. In MySQL, a database IS what others call a schema."""
    import pymysql

    params = _mysql_params()
    conn = pymysql.connect(
        host=params["host"],
        port=int(params["port"]),
        user=params["user"],
        password=params["password"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}`")
        conn.commit()
    finally:
        conn.close()


def raw_driver(framework: str) -> SnakeDriver:
    """A fresh driver for the framework, according to the `.env` engine. Unwrapped."""
    if backend() == "mysql":
        name = _pg_dbname(framework)
        _ensure_mysql_database(name)
        params = _mysql_params()
        return PyMySQLDriver.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            password=params["password"],
            database=name,
        )
    if backend() == "postgres":
        name = _pg_dbname(framework)
        _ensure_pg_database(name)
        params = _pg_params()
        dsn = (
            f"host={params['host']} port={params['port']} user={params['user']} "
            f"password={params['password']} dbname={name}"
        )
        return PsycopgDriver.connect(dsn)
    path = _sqlite_path(framework)
    path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteDriver.connect(str(path))


def make_session(framework: str) -> SnakeSession:
    """One session per request, with the driver wrapped in `CaptureDriver` for the ORM debug panel."""
    return SnakeSession(
        CaptureDriver(raw_driver(framework), system=db_system_name()), make_dialect()
    )


def init_schema(framework: str) -> None:
    """(Re)creates the schema from scratch: DROP + CREATE of every table AND its indexes, for a
    deterministic seed. Without the FK indexes, correlated aggregates crawl at scale."""
    dialect = make_dialect()
    driver = raw_driver(framework)
    try:
        # The views FIRST: a view reads from tables, so it goes before them — and `DROP TABLE`
        # is not what removes one (Postgres refuses it: "is not a table").
        for view in VIEWS:
            driver.execute(
                f"DROP VIEW IF EXISTS {dialect.quote_ident(snake_table(view).name)}", ()
            )
        for model in reversed(MODELS):
            table = snake_table(model)
            driver.execute(
                f"DROP TABLE IF EXISTS {dialect.quote_ident(table.name)}", ()
            )
        for model in MODELS:
            table = snake_table(model)
            driver.execute(emit_create_table(table, dialect), ())
            for index in table.indexes:
                driver.execute(emit_create_index(table, index, dialect), ())
        # And LAST the views, which read from the tables just created.
        for view in VIEWS:
            driver.execute(emit_create_view(snake_table(view), dialect), ())
        driver.commit()
    finally:
        driver.close()


def drop_all(framework: str) -> None:
    """DROPs EVERY table + the `snake_migrations` tracking: a deterministic reset BEFORE migrating.

    With the real migrations, boot runs `drop_all` + `SnakeOrmConfig.migrate()` (instead of
    `init_schema`): the schema is built by the migrations, not by a shortcut. The tracking is dropped
    so `migrate` re-applies from zero (otherwise it would believe it is migrated and create nothing)."""
    dialect = make_dialect()
    driver = raw_driver(framework)
    try:
        # The views FIRST: a view reads from tables, so it goes before them — and `DROP TABLE`
        # is not what removes one (Postgres refuses it: "is not a table").
        for view in VIEWS:
            driver.execute(
                f"DROP VIEW IF EXISTS {dialect.quote_ident(snake_table(view).name)}", ()
            )
        for model in reversed(MODELS):
            table = snake_table(model)
            driver.execute(
                f"DROP TABLE IF EXISTS {dialect.quote_ident(table.name)}", ()
            )
        driver.execute("DROP TABLE IF EXISTS snake_migrations", ())
        driver.commit()
    finally:
        driver.close()


def connection_config(framework: str) -> SnakeConnectionConfig:
    """The framework's `SnakeConnectionConfig`, for the engine chosen in the `.env`.

    A single place, and not a two-branch `if` copy-pasted into every demo. With the copy,
    `DB_BACKEND=mysql` fell into the `else` and built a SQLITE connection: the app talked to MySQL
    and the MIGRATIONS were applied to a local file. Each half worked, and together they did nothing
    — the schema never showed up in the real database and `migrate()` reported zero applied, without
    an error.

    It is exactly the failure `SnakeConnectionConfig` exists to prevent, sneaking in through the back
    door: not by mismatching driver and dialect, but by building the config twice.
    """
    chosen = backend()
    if chosen == "postgres":
        params = _pg_params()
        return SnakeConnectionConfig(
            backend=SnakeBackend.POSTGRES,
            name=_pg_dbname(framework),
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
        )
    if chosen == "mysql":
        params = _mysql_params()
        return SnakeConnectionConfig(
            backend=SnakeBackend.MYSQL,
            name=_pg_dbname(framework),
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
        )
    return SnakeConnectionConfig(
        backend=SnakeBackend.SQLITE, name=str(_sqlite_path(framework))
    )


# ---- The asynchronous half -----------------------------------------------------------------------
#
# Everything above builds a SYNCHRONOUS session, and that is what Django and Flask want. FastAPI is
# an ASGI application: its endpoints run on an event loop, so a blocking driver call does not slow
# one request down, it stops every other request sharing that loop. The pieces below are the async
# mirror of `raw_driver`/`make_session`, and they change nothing above them: the same
# `SnakeConnectionConfig`, the same engine chosen by the same `.env` variable.


async def open_async_session(framework: str) -> AsyncSession:
    """One ASYNCHRONOUS session for the framework, over its own connection, with the SQL captured.

    The single-connection path: it opens, it serves, it closes. Good for a script or a test, and
    wrong for a server — a hundred concurrent requests would open a hundred connections. For that,
    `make_async_pool` below.

    The dialect is NOT chosen here, and that is the whole point of going through
    `SnakeConnectionConfig`: driver and dialect come out PAIRED from the backend, so nobody can put
    an async SQLite driver together with a Postgres dialect.
    """
    return await open_session_async(connection_config(framework))


class _AsyncConnectionStore:
    """The connections an `AsyncSnakePool` hands out: a free list with a ceiling on how many exist.

    `AsyncSnakePool` deliberately does not open connections — it takes three callables and owns the
    POLICY (pre-ping, recycling, timeout, the discard fuse) while the caller owns the RESOURCE. This
    is the caller's half, and it is small enough to read in one go, which is the point of the demo:
    an app that wants pooling writes these three methods and nothing else.

    Running out raises rather than returning `None`, because that is the contract the pool is
    written against: it catches the failure, hands the loop back to the other tasks and asks again
    until `timeout_seconds` runs out. A `None` would look like a connection until somebody used it.
    """

    def __init__(self, config: SnakeConnectionConfig, size: int) -> None:
        self._config = config
        self._size = size
        self._free: list[AsyncDriver] = []
        self._live = 0

    async def borrow(self) -> AsyncDriver:
        """A free connection, or a brand new one while the ceiling allows it."""
        if self._free:
            return self._free.pop()
        if self._live >= self._size:
            raise SnakePoolTimeout(
                f"The pool of {self._size} connections is empty. Every one of them is in use."
            )
        driver, _dialect = await self._config.async_driver_and_dialect()
        self._live += 1
        return driver

    async def give_back(self, driver: AsyncDriver) -> None:
        """Back into the free list. The pool has already checked it is the same connection once."""
        self._free.append(driver)

    async def close_all(self) -> None:
        """Closes every connection that is not lent out. Called when the application shuts down."""
        while self._free:
            await self._free.pop().close()
        self._live = 0

    async def discard(self, driver: AsyncDriver) -> None:
        """Throws a dead connection away, freeing its slot so a healthy one can take it."""
        self._live = max(0, self._live - 1)
        await driver.close()


def make_async_pool(framework: str, *, size: int = 5) -> AsyncSnakePool:
    """The framework's async connection pool, for an application that serves concurrent requests.

    `pre_ping` is on because the demo's database is a docker container somebody restarts; without
    the pulse check the first request after a restart fails for something that is not its fault.
    `timeout_seconds` is what turns an exhausted pool from an instant error into a short WAIT, which
    is what an application under a burst actually wants.
    """
    store = _AsyncConnectionStore(connection_config(framework), size)
    return AsyncSnakePool(
        store.borrow,
        store.give_back,
        store.close_all,
        discard=store.discard,
        pre_ping=True,
        timeout_seconds=5.0,
    )


def async_session_over(driver: AsyncDriver) -> AsyncSession:
    """An `AsyncSession` over an already-borrowed driver, with the SQL captured for the panel.

    The pool hands out a driver, not a session, so this is the last inch: wrap it in
    `AsyncCaptureDriver` (or the debug panel goes blind on the async path, which is exactly how a
    demo ends up unable to show the thing it exists to show) and pair it with the engine's dialect.
    """
    return AsyncSession(
        AsyncCaptureDriver(driver, system=db_system_name()), make_dialect()
    )
