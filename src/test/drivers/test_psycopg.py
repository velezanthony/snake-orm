"""Tests of PsycopgDriver: a thin adapter over psycopg2.

It is tested with a FAKE connection/cursor (DBAPI) that record the calls: NO Postgres is needed.
They verify that the driver delegates correctly (execute/fetch/commit/rollback/close).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from snakeorm.drivers import PsycopgDriver, SnakeDriver


class _FakeCursor:
    """Fake DBAPI cursor: it records the executions and returns canned rows."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, Sequence[object] | None]] = []
        self.closed = False
        self.rowcount = 0
        # `itersize` is set by the driver when it opens a NAMED cursor (the server-side one); here
        # it is merely stored so that its arrival can be checked.
        self.itersize = 0
        self._served = 0

    def execute(self, sql: str, params: Sequence[object] | None) -> None:
        """`| None` because that is how psycopg spells NO PARAMETERS, and the driver now says it.

        Narrower than the real cursor, this double stopped satisfying the Protocol and mypy failed
        at every site that builds the driver — so widening it is not tidying, it is the half of the
        change that makes the other half type-check.
        """
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        """Serves the rows in chunks and then nothing, the way a real cursor would."""
        trozo = self.rows[self._served : self._served + size]
        self._served += len(trozo)
        return trozo

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    """Fake DBAPI connection: it hands out a cursor and counts commits/rollbacks."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.last_cursor = _FakeCursor(rows if rows is not None else [])
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self, name: str = "") -> _FakeCursor:
        return self.last_cursor

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        self.closed = True


def test_conforms_to_snake_driver_protocol() -> None:
    """Verifies that PsycopgDriver satisfies the SnakeDriver Protocol."""
    driver = PsycopgDriver(_FakeConnection())
    assert isinstance(driver, SnakeDriver)


def test_fetch_all_executes_and_returns_rows() -> None:
    """Verifies that fetch_all runs the SQL with its params and returns the cursor's rows."""
    conn = _FakeConnection(rows=[(1, "Ana"), (2, "Bob")])
    rows = PsycopgDriver(conn).fetch_all("SELECT ...", (5,))
    assert rows == [(1, "Ana"), (2, "Bob")]
    assert conn.last_cursor.executed == [("SELECT ...", (5,))]


def test_fetch_all_closes_the_cursor() -> None:
    """Verifies that the cursor is closed after the fetch (no cursors are leaked)."""
    conn = _FakeConnection(rows=[])
    PsycopgDriver(conn).fetch_all("SELECT ...", ())
    assert conn.last_cursor.closed is True


def test_execute_runs_without_fetch() -> None:
    """Verifies that execute fires the SQL without fetching any rows."""
    conn = _FakeConnection()
    PsycopgDriver(conn).execute("DELETE ...", (5,))
    assert conn.last_cursor.executed == [("DELETE ...", (5,))]


def test_execute_returns_cursor_rowcount() -> None:
    """Verifies that execute returns the cursor rowcount (affected rows), for the bulk write path."""
    conn = _FakeConnection()
    conn.last_cursor.rowcount = 3
    assert PsycopgDriver(conn).execute("UPDATE ...", ()) == 3


def test_commit_rollback_close_delegate_to_connection() -> None:
    """Verifies that commit/rollback/close delegate to the connection."""
    conn = _FakeConnection()
    driver = PsycopgDriver(conn)
    driver.commit()
    driver.rollback()
    driver.close()
    assert (conn.committed, conn.rolled_back, conn.closed) == (1, 1, True)


def test_connect_wraps_a_new_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that connect(dsn) opens a psycopg2 connection and wraps it (no real database)."""
    import psycopg2

    fake = _FakeConnection()
    monkeypatch.setattr(psycopg2, "connect", lambda dsn: fake)
    driver = PsycopgDriver.connect("postgresql://localhost/test")
    driver.commit()
    assert fake.committed == 1
