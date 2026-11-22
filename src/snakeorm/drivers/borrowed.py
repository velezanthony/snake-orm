"""A driver over a connection SOMEBODY ELSE opened: it carries statements and owns no transaction.

Two things are taken from the lender — the connection and the engine version — and nothing else.
The SQL, the dialect, the placeholders and the hydration all stay on this side, so what crosses is
`(sql, params)` and what comes back are rows. A postman.

What a postman may not do is decide when the letter is final. `commit`, `rollback` and the
savepoints belong to whoever opened the transaction, and calling them here is refused rather than
ignored: a silent no-op reads as "it committed" to the caller.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.drivers.base import SnakeDriver


class SnakeBorrowedDriver:
    """Wraps a driver over a foreign connection. Statements cross; transaction control does not."""

    __slots__ = ("_inner",)

    def __init__(self, inner: SnakeDriver) -> None:
        self._inner = inner

    def _refuse(self, what: str) -> None:
        raise SnakeUnsupportedFeature(
            f"{what} is refused on a borrowed connection: the transaction belongs to whoever "
            f"opened it — Django, a test harness, an outer session — and it ends when they say so. "
            f"Let the owner commit, or open a session on a connection of your own."
        )

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Carried through: reading is the job."""
        return self._inner.fetch_all(sql, params)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Carried through, streamed."""
        return self._inner.fetch_iter(sql, params, chunk=chunk)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Carried through: on a borrowed connection a write lands in the LENDER's transaction,
        which is the entire point of borrowing rather than opening our own."""
        return self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        """Read off the connection; it decides nothing."""
        return self._inner.last_insert_id

    def commit(self) -> None:
        """Refused: ending the lender's transaction early is what borrowing exists to avoid."""
        self._refuse("A commit")

    def rollback(self) -> None:
        """Refused: it would undo the lender's work as well as ours."""
        self._refuse("A rollback")

    def savepoint(self, name: str) -> None:
        """Refused: a savepoint is transaction control, and this transaction is not ours."""
        self._refuse("A savepoint")

    def release_savepoint(self, name: str) -> None:
        """Refused, see `savepoint`."""
        self._refuse("Releasing a savepoint")

    def rollback_to_savepoint(self, name: str) -> None:
        """Refused, see `savepoint`."""
        self._refuse("Rolling back to a savepoint")

    def close(self) -> None:
        """A NO-OP, and the one place this differs from the refusals above.

        Every session calls `close()` on the way out, so refusing would turn ordinary use into an
        error. Closing would cut the lender off a connection it still needs. Doing nothing loses
        nothing: whoever opened it closes it.
        """
        return None
