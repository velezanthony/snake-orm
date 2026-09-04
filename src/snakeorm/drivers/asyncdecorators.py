"""Decorators for the ASYNCHRONOUS driver: logging and timeout. Mirror of
`LoggingDriver`/`TimeoutDriver`.

There is no `AsyncPooledDriver` on purpose: in async, psycopg 3 ships its own
`AsyncConnectionPool`; reimplementing it would be competing to deliver less. Theirs is used and the
connection is handed to the driver.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager

from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects.base import SnakeDialect
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.drivers.logging import render_params

Writer = Callable[[str], None]
"""Where each line goes. It is injected: the ORM does not decide whether it is `print`, `logging` or a list."""


def _silent(_line: str) -> None:
    """Throws the line away: the default is to print nothing."""


@asynccontextmanager
async def _logged(write: Writer, head: str) -> AsyncIterator[list[str]]:
    """Writes ONE line for the statement, worked or not, with how long it took either way.

    Same reasoning as the synchronous twin, plus one of its own: the failing case is where the
    elapsed time is MOST interesting —a statement that took four seconds and then died— and it was
    the one case that never got written.
    """
    started = time.monotonic()
    outcome: list[str] = []
    try:
        yield outcome
    except BaseException as error:
        elapsed = (time.monotonic() - started) * 1000
        write(f"{head} -> FAILED: {type(error).__name__}: {error} in {elapsed:.1f} ms")
        raise
    if not outcome:
        # A transaction boundary counts no rows, so a duration would be noise on a line that is
        # already complete. `COMMIT` stays `COMMIT`, byte for byte, which is what the tests that
        # compare the log element by element are entitled to.
        write(head)
        return
    elapsed = (time.monotonic() - started) * 1000
    write(f"{head} -> {outcome[0]} in {elapsed:.1f} ms")


class AsyncLoggingDriver:
    """Wraps an `AsyncDriver` and logs every statement with its params and its duration.
    In async the order of the coroutines is not the order of the code, so the log is sometimes the only way to know it.
    """

    __slots__ = ("_inner", "_parameter_keys", "_write")

    def __init__(
        self,
        inner: AsyncDriver,
        write: Writer = _silent,
        *,
        parameter_keys: frozenset[str] = frozenset(),
    ) -> None:
        """The same contract as `LoggingDriver`: the VALUES are opt-in, named by 0-based index.

        Spelled out here rather than inherited because the two colours are separate classes, and
        this is the half the fix originally missed — the synchronous one stopped writing user
        values and this one carried on doing it, which is the drift the whole seam suffers from.
        """
        self._inner = inner
        self._write = write
        self._parameter_keys = parameter_keys

    def _params(self, params: Sequence[object]) -> str:
        """The parameters as its synchronous twin renders them: named ones shown, rest hidden."""
        return render_params(params, self._parameter_keys)

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        """Queries, logging how many rows came back and how long it took."""
        async with _logged(
            self._write, f"{sql} -- params={self._params(params)}"
        ) as outcome:
            rows = await self._inner.fetch_all(sql, params)
            outcome.append(f"{len(rows)} row(s)")
        return rows

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Yields the rows, logging how many were CONSUMED and how long it lasted.

        It is written down at the end, as in the synchronous logging: counting beforehand would
        require materialising, which is exactly what this path avoids, and in streaming what
        matters is what was really walked (a `break` at the tenth row out of a million counts ten).
        """
        started = time.monotonic()
        consumed = 0
        try:
            async for row in self._inner.fetch_iter(sql, params, chunk=chunk):
                consumed += 1
                yield row
        finally:
            elapsed = (time.monotonic() - started) * 1000
            self._write(
                f"{sql} -- params={tuple(params)!r} -> {consumed} row(s) streamed "
                f"in {elapsed:.1f} ms"
            )

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs the statement, logging how many rows it affected and how long it took."""
        async with _logged(
            self._write, f"{sql} -- params={self._params(params)}"
        ) as outcome:
            affected = await self._inner.execute(sql, params)
            outcome.append(f"{affected} row(s)")
        return affected

    @property
    def last_insert_id(self) -> int:
        """Delegates the id of the last INSERT: a decorator does not invent, it passes through."""
        return self._inner.last_insert_id

    async def commit(self) -> None:
        """Commits, leaving a record of it."""
        async with _logged(self._write, "COMMIT"):
            await self._inner.commit()

    async def rollback(self) -> None:
        """Rolls back, leaving a record of it."""
        async with _logged(self._write, "ROLLBACK"):
            await self._inner.rollback()

    async def savepoint(self, name: str) -> None:
        """Marks a savepoint and writes it down.

        It wrote NOTHING before. The class docstring of its synchronous twin says that without the
        transaction boundaries "the log lies by omission", and this colour omitted three of them.
        """
        async with _logged(self._write, f"SAVEPOINT {name}"):
            await self._inner.savepoint(name)

    async def release_savepoint(self, name: str) -> None:
        """Releases a savepoint and writes it down."""
        async with _logged(self._write, f"RELEASE SAVEPOINT {name}"):
            await self._inner.release_savepoint(name)

    async def rollback_to_savepoint(self, name: str) -> None:
        """Rolls back to a savepoint and writes it down."""
        async with _logged(self._write, f"ROLLBACK TO SAVEPOINT {name}"):
            await self._inner.rollback_to_savepoint(name)

    async def close(self) -> None:
        """Closes the driver inside."""
        await self._inner.close()


class AsyncTimeoutDriver:
    """Wraps an `AsyncDriver`, pinning the connection's `statement_timeout`.
    It is applied with `apply_to`, not in the constructor: in async you cannot await inside `__init__`.
    """

    __slots__ = ("_inner", "_timeout_ms")

    def __init__(self, inner: AsyncDriver, *, statement_timeout_ms: int) -> None:
        self._inner = inner
        self._timeout_ms = statement_timeout_ms

    @classmethod
    async def apply_to(
        cls, inner: AsyncDriver, dialect: SnakeDialect, *, statement_timeout_ms: int
    ) -> AsyncTimeoutDriver:
        """Creates the decorator and LEAVES the timeout APPLIED on the connection.

        Both halves of this came from copying the synchronous driver's SHAPE without its reasons.
        The `<= 0` guard was missing — on Postgres `statement_timeout = 0` means NO LIMIT, so
        accepting a zero does the exact opposite of what was asked — and the statement was written
        out as Postgres SQL, which MySQL and SQLite reject.
        """
        if statement_timeout_ms <= 0:
            raise ValueError(
                "statement_timeout_ms has to be greater than zero: in Postgres 0 means NO limit, "
                "so asking for 0 would switch the timeout off instead of tightening it."
            )
        statement = dialect.statement_timeout_sql(statement_timeout_ms)
        if statement is None:
            raise SnakeDialectError(
                f"{type(dialect).__name__} has no server-side statement timeout, so this driver "
                f"cannot cap anything on it."
            )
        driver = cls(inner, statement_timeout_ms=statement_timeout_ms)
        await inner.execute(statement, ())
        return driver

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        """Delegates the query; the limit is already set on the connection."""
        return await self._inner.fetch_all(sql, params)

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Delegates the streaming; the limit is already set on the connection."""
        async for row in self._inner.fetch_iter(sql, params, chunk=chunk):
            yield row

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        """Delegates the statement."""
        return await self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        """Delegates the id of the last INSERT: a decorator does not invent, it passes through."""
        return self._inner.last_insert_id

    async def commit(self) -> None:
        """Delegates the commit."""
        await self._inner.commit()

    async def rollback(self) -> None:
        """Delegates the rollback."""
        await self._inner.rollback()

    async def savepoint(self, name: str) -> None:
        """Delegates the savepoint."""
        await self._inner.savepoint(name)

    async def release_savepoint(self, name: str) -> None:
        """Delegates the release of the savepoint."""
        await self._inner.release_savepoint(name)

    async def rollback_to_savepoint(self, name: str) -> None:
        """Delegates the return to the savepoint."""
        await self._inner.rollback_to_savepoint(name)

    async def close(self) -> None:
        """Closes the driver inside."""
        await self._inner.close()
