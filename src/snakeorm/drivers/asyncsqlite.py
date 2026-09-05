"""`AsyncSQLiteDriver`: SQLite served as an `AsyncDriver`, on the adapter's own thread.

SQLite has no network protocol and its standard library is synchronous, so a "native asyncio"
driver does not exist: `aiosqlite`, which is the usual option, does exactly this on the inside —
serve the same old `sqlite3` from a thread. It is implemented here instead of depending on it
because the adapter was already needed for MySQL and this is five lines.
"""

from __future__ import annotations

from snakeorm.drivers.sqlite import SQLiteDriver
from snakeorm.drivers.threaded import ThreadedAsyncDriver


class AsyncSQLiteDriver(ThreadedAsyncDriver):
    """The SQLite driver wearing the `AsyncDriver` surface."""

    @classmethod
    async def connect(cls, path: str) -> AsyncSQLiteDriver:
        """Opens the database (a file or `:memory:`) and wraps it.

        It is `async` even though opening a file waits for nobody: the opening contract has to be
        the same as the one for networked engines, or `SnakeConnectionConfig.open_async()` would
        need a path per engine and we would be back to two ways of doing the same thing.

        The connection is opened INSIDE the adapter's thread: `sqlite3` ties every connection to
        its creating thread, so opening it here and using it over there blew up on the first
        `close()`.
        """
        return await cls.open(lambda: SQLiteDriver.connect(path))
