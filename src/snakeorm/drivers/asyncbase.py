"""`AsyncDriver`: the async mirror of `SnakeDriver` (same methods, `async`). The only piece
with "colour" on the execution side: SQL generation has none, so the compiler, the dialect,
the query, the expressions and the migrations are reused AS THEY ARE between sync and async.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol


class AsyncDriver(Protocol):
    """How the SQL is EXECUTED asynchronously. It cannot write it: that is the dialect."""

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        """Runs the query and returns every row as tuples."""
        ...

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Yields the rows WITHOUT materialising them all. Mirror of `SnakeDriver.fetch_iter`.

        It is NOT an `async def`: it returns the async iterator directly. An `async def` that
        were also a generator would force an `await` before the `async for`, and the contract
        would end up different from the synchronous one for no reason at all.
        """
        ...

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs a statement fetching no rows; returns how many it affected."""
        ...

    @property
    def last_insert_id(self) -> int:
        """The autoincrement id of the last INSERT. Exact mirror of `SnakeDriver.last_insert_id`.

        It was missing from this Protocol, and it bothered nobody because the only async driver
        was the Postgres one, where the PK comes back through RETURNING and this is irrelevant.
        It is on MySQL —where there is no RETURNING; MariaDB does have it— that the PK depends on this
        value: without the member in the contract, an async MySQL driver would have been born
        leaving the PK at `None` without saying a word.

        It is NOT `async`: it does not travel to the database, the cursor of the last write
        stored it.
        """
        ...

    async def commit(self) -> None:
        """Commits the transaction in progress."""
        ...

    async def rollback(self) -> None:
        """Rolls back the transaction in progress."""
        ...

    async def savepoint(self, name: str) -> None:
        """Opens a named savepoint."""
        ...

    async def release_savepoint(self, name: str) -> None:
        """Commits the savepoint."""
        ...

    async def rollback_to_savepoint(self, name: str) -> None:
        """Goes back to the savepoint, undoing what was done since it was opened."""
        ...

    async def close(self) -> None:
        """Closes the connection."""
        ...
