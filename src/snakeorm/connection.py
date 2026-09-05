"""CENTRALISED connection config: the object that crowns any framework's connection config.

Django feeds it by translating its `DATABASES` (`contrib.django`); Flask, FastAPI and anything else
without a convention build THIS directly and open it with `contrib.open_session`. The `backend`
picks driver AND dialect PAIRED — the user cannot put a `SQLiteDriver` together with a
`PostgresDialect` because they never pick the two pieces separately. Each engine's heavy deps
(`psycopg2`, `pymysql`) stay OPTIONAL: every driver imports them inside its `connect()`, not when the
class is defined, so importing the driver here does not drag them in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from snakeorm.dialects.matrix import flavour_of
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.registry import SnakeRegistry
from snakeorm.dialects.base import SnakeDialect
from snakeorm.drivers import PyMySQLDriver, SQLiteDriver
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.drivers.asyncpsycopg import AsyncPsycopgDriver
from snakeorm.drivers.asyncpymysql import AsyncPyMySQLDriver
from snakeorm.drivers.asyncsqlite import AsyncSQLiteDriver
from snakeorm.drivers.psycopg import PsycopgDriver, with_utc_timezone
from snakeorm.drivers.base import SnakeDriver
from snakeorm.session import AsyncSession, SnakeSession


class SnakeBackend(Enum):
    """The engine: it picks driver (how it EXECUTES) and dialect (how it WRITES SQL) at once."""

    POSTGRES = "postgres"
    SQLITE = "sqlite"
    MYSQL = "mysql"

    @property
    def db_system_name(self) -> str:
        """What OpenTelemetry calls this engine (`db.system.name`), for the `otel` debug channel.

        It answers HERE because this enum is the one place engine identity is written down. The
        alternatives are all second spellings of the same fact: the driver's class is hidden the
        moment a pool or a timeout decorator wraps it, and the SQL's placeholders say nothing about
        MariaDB.

        `mariadb` IS a value of its own in the convention and not an alias of `mysql`. SnakeORM
        reaches both through PyMySQL and cannot tell them apart without asking the server for its
        banner, so it reports `mysql` and leaves the correction to whoever knows: the capture driver
        takes the name as an argument.
        """
        return _DB_SYSTEM_NAMES[self]


# The engine's OpenTelemetry name, per member. A dict and not a second enum value so the member's
# own value (`postgres`, what a user writes in `ENGINE`) stays the public spelling: they are two
# different vocabularies for the same engine and merging them would break one of the two.
_DB_SYSTEM_NAMES: dict[SnakeBackend, str] = {
    SnakeBackend.POSTGRES: "postgresql",
    SnakeBackend.SQLITE: "sqlite",
    SnakeBackend.MYSQL: "mysql",
}


@dataclass(frozen=True, slots=True)
class SnakeConnectionConfig:
    """Everything defining ONE connection, in a typed object (frozen: not overwritten mid-request).

    `name` is the database (Postgres/MySQL) or, for SQLite, whatever it calls a database: a file
    path, `:memory:`, or a `file:` URI — the last being the only one that gives several connections
    ONE in-memory database. The remaining pieces only apply to the networked engines; SQLite ignores
    them.
    """

    backend: SnakeBackend
    name: str
    host: str = "localhost"
    port: str = ""
    user: str = ""
    password: str = ""
    dsn: str | None = None
    """An already-written DSN, for when the connection comes as one rather than in pieces.

    It exists so that ONE single piece pairs driver and dialect. `snake_session(name)` resolves the
    connection through its DSN — multi-DB by environment variable — and used to assemble the pair by
    hand, which left two places where somebody could join a driver to another engine's dialect. That
    path now comes through here, and the pairing goes on living in a single method.
    """

    @classmethod
    def from_dsn(cls, dsn: str, backend: SnakeBackend) -> SnakeConnectionConfig:
        """Takes a DSN apart into the pieces THAT engine's driver actually wants.

        Each one asks for the connection in its own shape and there is no common denominator:
        psycopg reads a DSN string, SQLite wants a filesystem PATH, and PyMySQL wants loose keyword
        arguments. So a DSN has to be translated, and it is translated HERE — beside
        `driver_and_dialect` — because this class exists so that pairing a driver with another
        engine's dialect is not expressible. A second place doing the same translation would be a
        second place to get it wrong.

        It was `snake_session` that needed it, and needed it badly: it handed the connection's ALIAS
        over as `name`, which Postgres ignores (its DSN wins) and SQLite reads as the path. So
        `snake_session("reports")` created a file literally called `reports` in the working
        directory instead of opening the one the DSN named — and a test that only checked the
        dialect passed over it.
        """
        if backend is SnakeBackend.POSTGRES:
            # psycopg parses its own DSN, in either form (URL or libpq keywords), so it travels whole.
            return cls(backend=backend, name="", dsn=dsn)

        parsed = urlsplit(dsn)
        if backend is SnakeBackend.SQLITE:
            # The THIRD slash is the URL's separator, so exactly one comes off: `sqlite:///tmp/x.db`
            # is the relative `tmp/x.db`, `sqlite:////tmp/x.db` is `/tmp/x.db`. SQLAlchemy's rule.
            # A relative path STAYS relative — resolving it here would be guessing (bug #38).
            # `:memory:` arrives in the authority, where no slash rule applies. The query string is
            # kept only for a `file:` URI, which is the half of #37 that survived fixing the driver.
            database = f"{parsed.netloc}{parsed.path}"
            if database.startswith("/"):
                database = database[1:]
            if database.startswith("file:") and parsed.query:
                database = f"{database}?{parsed.query}"
            return cls(backend=backend, name=database or ":memory:")
        return cls(
            backend=backend,
            name=parsed.path.lstrip("/"),
            host=parsed.hostname or "localhost",
            port=str(parsed.port) if parsed.port else "",
            user=parsed.username or "",
            password=parsed.password or "",
        )

    def driver_and_dialect(self) -> tuple[SnakeDriver, SnakeDialect]:
        """Builds driver and dialect PAIRED according to `backend` (impossible to unpair them)."""
        if self.backend is SnakeBackend.SQLITE:
            return SQLiteDriver.connect(self.name), SQLiteDialect()
        if self.backend is SnakeBackend.POSTGRES:
            return PsycopgDriver.connect(self.postgres_dsn()), PostgresDialect()
        driver = PyMySQLDriver.connect(**self._mysql_kwargs())
        return driver, MySQLDialect(flavour_of(driver.server_version()))

    def open(
        self,
        wrap: Callable[[SnakeDriver], SnakeDriver] | None = None,
        *,
        model_registry: SnakeRegistry | None = None,
    ) -> SnakeSession:
        """Assembles the whole session (driver + dialect paired) in a single call.

        `wrap` wraps the driver before the session is assembled: the seam for `CaptureDriver` (so the
        debug panel sees the SQL), pooling, logging or timeout. It is passed FROM outside — this
        module does not import it — so the central config stays uncoupled from the debug subsystem
        and from the decorators.
        """
        driver, dialect = self.driver_and_dialect()
        if wrap is not None:
            driver = wrap(driver)
        return SnakeSession(driver, dialect, model_registry=model_registry)

    async def async_driver_and_dialect(self) -> tuple[AsyncDriver, SnakeDialect]:
        """The async pair PAIRED according to `backend`, just like its synchronous sibling.

        It is `async` because opening can wait: `AsyncPsycopgDriver.connect` is. Reusing the
        synchronous method was no good, hence there are two: `driver_and_dialect` connects eagerly.
        """
        if self.backend is SnakeBackend.SQLITE:
            return await AsyncSQLiteDriver.connect(self.name), SQLiteDialect()
        if self.backend is SnakeBackend.POSTGRES:
            return await AsyncPsycopgDriver.connect(self.postgres_dsn()), (
                PostgresDialect()
            )
        driver = await AsyncPyMySQLDriver.connect(**self._mysql_kwargs())
        return driver, MySQLDialect(flavour_of(await driver.server_version()))

    async def open_async(
        self,
        wrap: Callable[[AsyncDriver], AsyncDriver] | None = None,
        *,
        model_registry: SnakeRegistry | None = None,
    ) -> AsyncSession:
        """Assembles the whole ASYNCHRONOUS session (driver + dialect paired) in one call.

        Without this, the async user picked driver and dialect separately — which is exactly what this
        module exists to prevent: nobody can put a `SQLiteDriver` together with a `PostgresDialect`
        because they never choose the two pieces.

        `wrap` wraps the driver before the session is assembled, as on the synchronous path.
        """
        driver, dialect = await self.async_driver_and_dialect()
        if wrap is not None:
            driver = wrap(driver)
        return AsyncSession(driver, dialect, model_registry=model_registry)

    def postgres_dsn(self) -> str:
        """psycopg's DSN: the declared one if there is one, or built from the pieces.

        It only includes what was declared (no empty pieces). The UTC zone is pinned the same way on
        both paths: that is what makes opening the database to look at a date show the instant that
        was stored, and not the server's local time.
        """
        if self.dsn is not None:
            return with_utc_timezone(self.dsn)
        parts = [f"host={self.host}", f"dbname={self.name}"]
        if self.port:
            parts.append(f"port={self.port}")
        if self.user:
            parts.append(f"user={self.user}")
        if self.password:
            parts.append(f"password={self.password}")
        # The session's zone, pinned in the DSN itself: `TIMESTAMPTZ` stores the instant but SHOWS
        # it in the session's zone, so without this, opening the database to check the dates shows
        # the server's local time and the look tells you nothing.
        return with_utc_timezone(" ".join(parts))

    def _mysql_kwargs(self) -> dict[str, object]:
        """Kwargs for `PyMySQLDriver.connect` (its signature is not a DSN string, but loose args)."""
        kwargs: dict[str, object] = {"host": self.host, "database": self.name}
        if self.port:
            kwargs["port"] = int(self.port)
        if self.user:
            kwargs["user"] = self.user
        if self.password:
            kwargs["password"] = self.password
        # The MySQL equivalent, which has no libpq `options`. Same guarantee by another mechanism:
        # what you see when querying is what was stored.
        kwargs["init_command"] = "SET time_zone = '+00:00'"
        return kwargs
