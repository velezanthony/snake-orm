"""`AsyncPyMySQLDriver`: MySQL served as an `AsyncDriver`, on the adapter's own thread.

Unlike SQLite, here a native alternative DOES exist (`aiomysql`), and it would be better under
heavy concurrency: this path takes up one OS thread per connection, and the native one does not.
The adapter is chosen because it adds no per-engine dependency and because the concurrency it
gives is real —Python releases the GIL while the socket waits, so two queries from two tasks
really do overlap—.

Stated here so nobody has to work it out: the day the native one is wanted, it comes in as
another implementation of the same Protocol and nothing upstream changes. That is exactly the
seam this project has been defending from the start.
"""

from __future__ import annotations

from typing import Any

from snakeorm.drivers.pymysql import PyMySQLDriver
from snakeorm.drivers.threaded import ThreadedAsyncDriver


class AsyncPyMySQLDriver(ThreadedAsyncDriver):
    """The MySQL driver wearing the `AsyncDriver` surface.

    It is the engine where `last_insert_id` really matters: MySQL has no `RETURNING`, so an
    INSERT's autoincrement PK comes from there. The async Protocol not declaring it was a time
    bomb waiting for precisely this file.
    """

    @classmethod
    async def connect(cls, **kwargs: Any) -> AsyncPyMySQLDriver:
        """Opens the connection with PyMySQL's kwargs (host, user, password, database, port...).

        The connection is opened INSIDE the adapter's thread, just like on SQLite. PyMySQL does
        not demand it —it only asks that two threads do not use it at once—, but opening it where
        it is going to be used leaves ONE rule for both engines instead of an exception somebody
        will have to remember.

        And `connect` really does block (it opens a socket and negotiates): doing it on the thread
        avoids stalling the event loop right at startup, which is when the most tasks are waiting.
        """
        return await cls.open(lambda: PyMySQLDriver.connect(**kwargs))
