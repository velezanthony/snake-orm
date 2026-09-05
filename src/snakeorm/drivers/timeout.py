"""A driver that caps how long a statement may take, by wrapping another one."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects.base import SnakeDialect
from snakeorm.drivers.base import SnakeDriver


class TimeoutDriver:
    """Wraps a `SnakeDriver` and sets a `statement_timeout` for the whole connection: one hung
    query drains the pool. The setting is emitted ONCE on wrapping (it is per CONNECTION, not per
    statement).
    """

    __slots__ = ("_inner",)

    def __init__(
        self, inner: SnakeDriver, dialect: SnakeDialect, *, statement_timeout_ms: int
    ) -> None:
        if statement_timeout_ms <= 0:
            # On Postgres `statement_timeout = 0` means NO LIMIT: accepting 0 would silently do the opposite.
            raise ValueError(
                "statement_timeout_ms has to be greater than zero: in Postgres 0 means NO limit, "
                "so asking for 0 would switch the timeout off instead of tightening it."
            )
        # The statement is ASKED of the dialect. It used to be written here as
        # `SET statement_timeout = <ms>`, which is Postgres and only Postgres, under a class name
        # that promises nothing about engines: MySQL answered `1193 Unknown system variable` and
        # SQLite a syntax error, so the knob that keeps one hung query from draining the pool
        # worked on one engine out of three.
        statement = dialect.statement_timeout_sql(statement_timeout_ms)
        if statement is None:
            raise SnakeDialectError(
                f"{type(dialect).__name__} has no server-side statement timeout, so this driver "
                f"cannot cap anything on it. Accepting the wrap would hand back a connection that "
                f"LOOKS capped and is not, which is the opposite of what asking for a timeout "
                f"means. (SQLite's `busy_timeout` waits for a lock; it does nothing about a slow "
                f"query.)"
            )
        self._inner = inner
        self._inner.execute(statement, ())

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Delegates the query; the limit is already set on the connection."""
        return self._inner.fetch_all(sql, params)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Delegates the streaming; the limit is already set on the connection."""
        return self._inner.fetch_iter(sql, params, chunk=chunk)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Delegates the statement; the limit is already set on the connection."""
        return self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT (see the Protocol). Forwarded to the wrapped driver."""
        return self._inner.last_insert_id

    def commit(self) -> None:
        """Commits the inner driver's transaction."""
        self._inner.commit()

    def rollback(self) -> None:
        """Rolls back the inner driver's transaction."""
        self._inner.rollback()

    def savepoint(self, name: str) -> None:
        """Marks a savepoint on the inner driver."""
        self._inner.savepoint(name)

    def release_savepoint(self, name: str) -> None:
        """Releases a savepoint on the inner driver."""
        self._inner.release_savepoint(name)

    def rollback_to_savepoint(self, name: str) -> None:
        """Rolls back to a savepoint on the inner driver."""
        self._inner.rollback_to_savepoint(name)

    def close(self) -> None:
        """Closes the inner driver."""
        self._inner.close()
