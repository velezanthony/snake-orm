"""ASYNCHRONOUS PostgreSQL driver over psycopg 3 (psycopg2 has no native async). An OPTIONAL
dependency (`snakeorm[async]`). The placeholder is still `%s`, so `PostgresDialect` works as it is.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from snakeorm.drivers.failures import async_translating
from snakeorm.drivers.savepoints import quote_savepoint

from snakeorm.sql.adapt import adapt_params

_QUOTE = '"'
"""The character THIS engine quotes an identifier with.

MySQL and MariaDB reject a double-quoted identifier unless `ANSI_QUOTES` is on, so a shared helper
that always wrote a double quote turned every `SAVEPOINT` into `ERROR 1064` here. The RULE about
what a valid name is, is shared; the quoting character is the engine's own grammar.
"""


class AsyncPsycopgDriver:
    """An asynchronous connection to PostgreSQL with psycopg 3."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        # Named-cursor counter: two alive at once with the same name would collide.
        self._cursor_seq = 0

    @classmethod
    async def connect(cls, dsn: str) -> AsyncPsycopgDriver:
        """Opens the connection. Requires `snakeorm[async]` (psycopg 3) to be installed."""
        try:
            import psycopg
        except (
            ModuleNotFoundError
        ) as error:  # pragma: no cover - depends on the environment
            raise ModuleNotFoundError(
                "The asynchronous driver needs psycopg 3: install `snakeorm[async]`. psycopg2 "
                "has no native async, so it is no use for this."
            ) from error

        # `autocommit=False`: the session drives the transactions, as in the synchronous driver.
        return cls(await psycopg.AsyncConnection.connect(dsn, autocommit=False))

    @async_translating
    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        """Runs the query and returns every row as tuples, closing the cursor."""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql, adapt_params(params, native_arrays=True, percent_formatting=True)
            )
            return [tuple(row) for row in await cursor.fetchall()]

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Yields the rows in chunks with a NAMED cursor (server-side).

        On psycopg3, just as on psycopg2, the name is what makes the result stay on Postgres
        instead of travelling to the client whole. Without it, `fetchmany` would be slicing
        something that is already in memory and the streaming would be decorative.
        """
        self._cursor_seq += 1
        async with self._connection.cursor(
            name=f"snake_stream_{self._cursor_seq}"
        ) as cursor:
            cursor.itersize = chunk
            await cursor.execute(
                sql, adapt_params(params, native_arrays=True, percent_formatting=True)
            )
            while True:
                rows = await cursor.fetchmany(chunk)
                if not rows:
                    return
                for row in rows:
                    yield tuple(row)

    @async_translating
    async def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs a statement fetching no rows and returns how many it affected."""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql, adapt_params(params, native_arrays=True, percent_formatting=True)
            )
            return int(cursor.rowcount)

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT (see the Protocol). Unused: Postgres returns the PK through RETURNING."""
        return 0  # Postgres returns the PK through RETURNING; this value is not used

    @async_translating
    async def commit(self) -> None:
        """Commits the transaction in progress."""
        await self._connection.commit()

    async def rollback(self) -> None:
        """Rolls back the transaction in progress."""
        await self._connection.rollback()

    async def savepoint(self, name: str) -> None:
        """Opens a named savepoint."""
        await self.execute(f"SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ())

    async def release_savepoint(self, name: str) -> None:
        """Commits the savepoint."""
        await self.execute(
            f"RELEASE SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ()
        )

    async def rollback_to_savepoint(self, name: str) -> None:
        """Goes back to the savepoint, undoing what was done since it was opened."""
        await self.execute(
            f"ROLLBACK TO SAVEPOINT {quote_savepoint(name, quote=_QUOTE)}", ()
        )

    async def close(self) -> None:
        """Closes the connection."""
        await self._connection.close()
