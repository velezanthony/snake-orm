"""SQLite driver over the stdlib's `sqlite3`. It mirrors `PsycopgDriver` (same Protocol) except for
two connector decisions that bite in silence:

1. `PRAGMA foreign_keys = ON`: SQLite ignores FKs by default; emitting FKs that are not enforced is
   exactly the silent failure this project hunts down.
2. `isolation_level = None` + a lazy `BEGIN` issued by the driver ITSELF. sqlite3's "magic" handling
   does not wrap DDL (it breaks migrations); with `None` it stays in autocommit and `rollback()`
   undoes nothing. The driver opens the transaction on the first statement and closes it on
   commit/rollback (like psycopg2), so the DDL goes inside the transaction, which is what
   `supports_transactional_ddl=True` promises.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from snakeorm.drivers.failures import translating
from snakeorm.drivers.savepoints import quote_savepoint

from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.sql.adapt import adapt_params

_QUOTE = '"'
"""The character THIS engine quotes an identifier with.

MySQL and MariaDB reject a double-quoted identifier unless `ANSI_QUOTES` is on, so a shared helper
that always wrote a double quote turned every `SAVEPOINT` into `ERROR 1064` here. The RULE about
what a valid name is, is shared; the quoting character is the engine's own grammar.
"""


class SQLiteDriver:
    """A connection to SQLite. A file, or `:memory:` for an ephemeral database (tests).
    `sqlite3` is imported INSIDE `connect` (like psycopg2), so it is not loaded on every `import snakeorm`.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._in_tx = False  # is there a transaction opened by our lazy BEGIN?

    def _ensure_tx(self) -> None:
        """Opens a transaction if there is none, before the first statement (like psycopg2), so the
        session sees a coherent snapshot and the rollback has something to undo.
        """
        if not self._in_tx:
            self._connection.execute("BEGIN")
            self._in_tx = True

    @classmethod
    def connect(cls, database: str) -> SQLiteDriver:
        """Opens the database and leaves the connector in a state with no surprises.

        `database` is a NAME, not a DSN: a path, `:memory:`, or a `file:` URI. A `sqlite:` scheme
        RAISES, because stripping it here would make this a SECOND place translating a DSN, and one
        string would name two databases, silently (bug #38).

        `uri=True` is passed unconditionally, and that is measured rather than assumed. SQLite reads
        a connection string as a URI only when it begins with `file:`; everything else is a literal
        filename, question marks included (`weird?name.db` is still that file). So there is no flag
        and no heuristic about what the caller meant.

        WITHOUT IT, `file:cache?mode=memory&cache=shared` — the standard spelling of a shared
        in-memory database — is taken as a FILENAME, and SQLite creates a file called exactly that.
        It does not fail; it opens the wrong database and carries on, and everything downstream
        works because it IS a real database. With it, a MALFORMED `file:` DSN raises instead of
        quietly creating a file named after the mistake.
        """
        import sqlite3

        # On the SCHEME, not a prefix match: `sqlite_backup.db` is an ordinary filename.
        if database.startswith("sqlite:"):
            raise SnakeConfigError(
                f"SQLiteDriver.connect() takes a database name, not a DSN, and got {database!r}. "
                "A DSN is translated in ONE place: "
                "SnakeConnectionConfig.from_dsn(dsn, SnakeBackend.SQLITE), whose `.name` is what "
                "belongs here. Two places translating is how one string ends up naming two "
                "different databases."
            )
        # `isolation_level=None`: the session drives the transactions, not the connector.
        connection = sqlite3.connect(
            database or ":memory:", isolation_level=None, uri=True
        )
        # Without this, SQLite accepts the FKs and does NOT enforce them. Unacceptable silence.
        connection.execute("PRAGMA foreign_keys = ON")
        return cls(connection)

    @translating
    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Runs the query and returns every row as tuples, closing the cursor."""
        self._ensure_tx()
        cursor = self._connection.execute(
            sql, adapt_params(params, native_arrays=False, percent_formatting=False)
        )
        try:
            return [tuple(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Yields the rows in chunks with `fetchmany`.

        SQLite has no server-side cursors —the database IS the process—, so there is nothing to
        leave over there. What this does avoid is building the whole result list in Python: the
        memory peak becomes the chunk, not the result. Less than on Postgres, but real, and the
        same contract for whoever calls it.
        """
        self._ensure_tx()
        cursor = self._connection.execute(
            sql, adapt_params(params, native_arrays=False, percent_formatting=False)
        )
        try:
            while True:
                rows = cursor.fetchmany(chunk)
                if not rows:
                    return
                for row in rows:
                    yield tuple(row)
        finally:
            cursor.close()

    @translating
    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs a statement fetching no rows and returns how many it affected."""
        self._ensure_tx()
        cursor = self._connection.execute(
            sql, adapt_params(params, native_arrays=False, percent_formatting=False)
        )
        try:
            return int(cursor.rowcount)
        finally:
            cursor.close()

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT (see the Protocol). Unused: this engine returns the PK through RETURNING."""
        return 0  # SQLite returns the PK through RETURNING; this value is not used

    @translating
    def commit(self) -> None:
        """Commits the transaction in progress (if any). The next statement opens another one."""
        if self._in_tx:
            self._connection.execute("COMMIT")
            self._in_tx = False

    def rollback(self) -> None:
        """Rolls back the transaction in progress (if any). A no-op if nothing was open."""
        if self._in_tx:
            self._connection.execute("ROLLBACK")
            self._in_tx = False

    def savepoint(self, name: str) -> None:
        """Opens a named savepoint. `execute` opens the transaction lazily, so a `SAVEPOINT` as the
        very first operation works too.
        """
        self.execute(f"SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ())

    def release_savepoint(self, name: str) -> None:
        """Commits the savepoint (you can no longer go back to it)."""
        self.execute(f"RELEASE SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ())

    def rollback_to_savepoint(self, name: str) -> None:
        """Goes back to the savepoint, undoing what was done since it was opened."""
        self.execute(f"ROLLBACK TO SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ())

    def close(self) -> None:
        """Closes the connection."""
        self._connection.close()
