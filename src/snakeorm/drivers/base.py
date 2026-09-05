"""The Protocol that defines a driver: how the SQL is EXECUTED (synchronous)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class SnakeDriver(Protocol):
    """How the SQL is executed: wraps the DBAPI (connection, cursor, transaction).

    SYNCHRONOUS. The SQL arrives already compiled (colourless) from `sql/`; the driver only
    runs it. The day async is needed, an AsyncDriver is added WITHOUT touching the compiler,
    the dialect or the AST. Adding a new engine = one implementation of this Protocol, with
    no refactor.
    """

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Runs a query and returns every row (for SELECT / RETURNING)."""
        ...

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Runs a query and yields the rows WITHOUT materialising them all.

        This is the streaming seam, and that is why it lives in the Protocol and not in some
        loose method on one driver: with only `fetch_all`, a ten-million-row query built a
        Python list of ten million tuples before returning the first one, and there was no way
        to fix that without touching this contract.

        `chunk` is how many rows the engine brings back per round trip: the knob that decides
        the memory. Whoever can, uses a SERVER-SIDE CURSOR (the result stays over there);
        whoever cannot, a `fetchmany`, which at least bounds the peak.

        The cursor lives for as long as the iteration does, so the consumer must exhaust it or
        close it.
        """
        ...

    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs a statement fetching no rows and returns the rowcount (used by bulk writes)."""
        ...

    @property
    def last_insert_id(self) -> int:
        """The autoincrement id of the last INSERT. The session only uses it on engines WITHOUT
        `RETURNING` (MySQL); on Postgres/SQLite the PK comes back through RETURNING and this is
        irrelevant (it may be 0).
        """
        ...

    def commit(self) -> None:
        """Commits the transaction in progress."""
        ...

    def rollback(self) -> None:
        """Rolls back the transaction in progress."""
        ...

    def savepoint(self, name: str) -> None:
        """Marks a SAVEPOINT: lets you roll back ONLY a part (via `rollback_to_savepoint`) without aborting the transaction."""
        ...

    def release_savepoint(self, name: str) -> None:
        """Releases (RELEASE) a savepoint: its work is folded into the transaction in progress."""
        ...

    def rollback_to_savepoint(self, name: str) -> None:
        """Rolls back to a savepoint: discards what was done since it, without aborting the transaction."""
        ...

    def close(self) -> None:
        """Closes the connection."""
        ...
