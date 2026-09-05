"""PsycopgDriver: runs SQL against PostgreSQL with psycopg2 (synchronous). A THIN adapter that
translates the SnakeDriver Protocol into cursor calls; it only runs the already-compiled
`(sql, params)`. The connection is typed with a minimal DBAPI Protocol (`_Connection`), not the
concrete type: that decouples and makes it testable.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol, cast
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from snakeorm.drivers.failures import translating
from snakeorm.drivers.savepoints import quote_savepoint

from snakeorm.sql.adapt import adapt_params

_QUOTE = '"'
"""The character THIS engine quotes an identifier with.

MySQL and MariaDB reject a double-quoted identifier unless `ANSI_QUOTES` is on, so a shared helper
that always wrote a double quote turned every `SAVEPOINT` into `ERROR 1064` here. The RULE about
what a valid name is, is shared; the quoting character is the engine's own grammar.
"""


class _Cursor(Protocol):
    """The minimal DBAPI cursor the driver needs."""

    @property
    def rowcount(self) -> int:
        """Rows affected by the last statement. A read-only property, like psycopg2's real `rowcount`."""
        ...

    itersize: int
    """Rows per round trip of a NAMED cursor. On an unnamed one it does nothing."""

    @translating
    # `| None` is how these two libraries spell NO PARAMETERS, and it is not the same as an
    # empty sequence: given `()` they re-read the SQL as a format template, so a literal `%` —
    # every DDL statement the migration runner emits — dies before reaching the server. The
    # Protocol has to admit it or the drivers cannot say it.
    def execute(self, sql: str, params: Sequence[object] | None) -> object: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def fetchmany(self, size: int) -> list[tuple[object, ...]]: ...
    def close(self) -> None: ...


class _Connection(Protocol):
    """The minimal DBAPI connection the driver needs."""

    def cursor(self, name: str = ...) -> _Cursor: ...
    @translating
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


_UTC_SETTING = "-c timezone=UTC"

_UTC_OPTION = f"options='{_UTC_SETTING}'"
"""Pins the SESSION's time zone as the connection starts, without running a single statement.

`TIMESTAMPTZ` stores the instant but DISPLAYS it in the session's zone: without this, opening the
database to check that the dates are right shows the server's local time and the glance tells you
nothing. It goes in the DSN and not in a `SET TIME ZONE` because a statement would open a
transaction, and `set_isolation()` demands being the first one in its own.
"""

# Quoted and appended after a space, `_UTC_OPTION` is the KEYWORD/VALUE grammar; a URI takes the
# option as a query parameter instead. `postgres://` is not a legacy alias: it is what
# `DATABASE_URL` holds on Heroku and Railway.
_URI_SCHEMES = ("postgresql://", "postgres://")


def with_utc_timezone(dsn: str) -> str:
    """Adds the UTC time zone request to the DSN, unless it already carries its own `options`.

    Respecting somebody else's `options=` is the escape hatch: whoever writes the startup options
    knows what they are doing, and stomping on them would be deciding for them.

    Appending the keyword/value form onto a URI does not fail, it lands INSIDE the database name:
    `database "mibase options='-c timezone=UTC'" does not exist`. Hence the two branches.

    The space goes as `%20`, never `+`: libpq percent-decodes and leaves a plus alone.
    """
    if "options=" in dsn:
        return dsn
    if not dsn.startswith(_URI_SCHEMES):
        return f"{dsn} {_UTC_OPTION}"
    parts = urlsplit(dsn)
    option = urlencode({"options": _UTC_SETTING}, quote_via=quote)
    query = f"{parts.query}&{option}" if parts.query else option
    return urlunsplit(parts._replace(query=query))


class PsycopgDriver:
    """Synchronous driver over psycopg2. Implements the SnakeDriver Protocol."""

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection
        # Named-cursor counter: two alive at once with the SAME name on one connection would
        # collide, and the streaming path opens one per query.
        self._cursor_seq = 0

    @classmethod
    def adopt(cls, connection: object) -> PsycopgDriver:
        """Wraps a RAW psycopg2 connection, adapting it to our minimal DBAPI.

        This is THE edge where psycopg2's concrete type enters our world (`connect()` and the pool
        both use it). The `cast` is legitimate: pyright does not narrow psycopg2's `cursor()` to
        `_Connection`; the parameter is `object` because the incoming type is foreign and cannot be
        narrowed.
        """
        return cls(cast("_Connection", connection))

    @classmethod
    def connect(cls, dsn: str) -> PsycopgDriver:
        """Opens a psycopg2 connection with the given DSN and wraps it (lazy import)."""
        import psycopg2

        return cls.adopt(psycopg2.connect(with_utc_timezone(dsn)))

    @translating
    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Runs a query and returns all of its rows, closing the cursor."""
        cursor = self._connection.cursor()
        try:
            cursor.execute(
                sql, adapt_params(params, native_arrays=True, percent_formatting=True)
            )
            return cursor.fetchall()
        finally:
            cursor.close()

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Yields the rows in chunks using a NAMED cursor (server-side).

        The name is not cosmetic: it is what turns psycopg2's cursor into a SERVER cursor. Without
        it, psycopg2 pulls the whole result into the client's memory even if you call `fetchmany`,
        and the streaming would be an illusion. With it, the result stays on Postgres and
        `itersize` decides how many rows travel per round trip.

        The name carries a counter because two named cursors alive at once on the same connection
        would collide.
        """
        self._cursor_seq += 1
        cursor = self._connection.cursor(name=f"snake_stream_{self._cursor_seq}")
        try:
            cursor.itersize = chunk
            cursor.execute(
                sql, adapt_params(params, native_arrays=True, percent_formatting=True)
            )
            while True:
                rows = cursor.fetchmany(chunk)
                if not rows:
                    return
                yield from rows
        finally:
            cursor.close()

    @translating
    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs a statement fetching no rows and returns the rowcount, closing the cursor.

        `cursor.rowcount` is how many rows the statement affected (bulk writes read it). It is
        captured BEFORE closing the cursor: after `close()` it is no longer available.
        """
        cursor = self._connection.cursor()
        try:
            cursor.execute(
                sql, adapt_params(params, native_arrays=True, percent_formatting=True)
            )
            return cursor.rowcount
        finally:
            cursor.close()

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT (see the Protocol). Unused: Postgres returns the PK through RETURNING."""
        return 0

    @translating
    def commit(self) -> None:
        """Commits the transaction in progress."""
        self._connection.commit()

    def rollback(self) -> None:
        """Rolls back the transaction in progress."""
        self._connection.rollback()

    def savepoint(self, name: str) -> None:
        """Emits `SAVEPOINT "n"`. The name is internal, but it is quoted for safety."""
        self.execute(f"SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ())

    def release_savepoint(self, name: str) -> None:
        """Emits `RELEASE SAVEPOINT "n"`: folds the savepoint into the transaction."""
        self.execute(f"RELEASE SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ())

    def rollback_to_savepoint(self, name: str) -> None:
        """Emits `ROLLBACK TO SAVEPOINT "n"`: discards what was done since the savepoint."""
        self.execute(f"ROLLBACK TO SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ())

    def close(self) -> None:
        """Closes the connection."""
        self._connection.close()
