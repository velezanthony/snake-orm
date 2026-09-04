"""A connection handed back to the pool must not come back to the next borrower dirty.

This is a contract test and not a coverage one, and the difference is the whole reason it exists.
`SnakePool` is engine-agnostic: it takes `borrow` and `give_back` from whoever builds it, and the
only pool this project ships is the psycopg2 one — whose `putconn` rolls an open transaction back
all by itself. So the promise used to HOLD, and to hold because of a library the seam does not own.

These went red when they were written. A pool built for SQLite or MySQL, with a `give_back` that
just files the connection away, got no rollback from the ORM at all: the lent driver's `close()`
returned the connection and did nothing else, and the next borrower opened its work on top of
somebody else's half-finished transaction. `_PooledDriver.close()` now rolls back before handing
the connection over, so the guarantee is the seam's rather than borrowed.

The question is asked with a `give_back` that adds nothing — a plain list — because that is the
smallest pool anybody could write, and the only one that can tell whose guarantee it is.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import SQLiteDriver
from snakeorm.drivers.base import SnakeDriver
from snakeorm.drivers.pool import SnakePool

_TABLE = "pool_contract"


def _open_driver() -> SnakeDriver:
    """One SQLite connection in memory, with the table already there.

    Plain `:memory:` and not a shared-cache URI, and the reason has changed since this was written.
    The URI came first and was wrong twice over: the driver did not pass `uri=True`, so
    `file:...?mode=memory&cache=shared` was taken as a FILENAME and left a file by that literal name
    in the repository root, which reached a commit. THAT half is fixed — see
    `test_sqlite_uri.py` — so the URI would work now.

    It stays `:memory:` for the half that was never about the bug: this pool holds exactly ONE
    connection, so there is no second one to share a cache with. Asking for sharing nobody uses
    would put a feature in the fixture instead of the subject.
    """
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(f"CREATE TABLE IF NOT EXISTS {_TABLE} (n INTEGER)", ())
    driver.commit()
    return driver


@pytest.fixture
def pool() -> Iterator[SnakePool]:
    """A pool of exactly one connection, with the plainest `give_back` there is.

    One connection on purpose: the driver the second borrow receives is necessarily the one the
    first gave back, so what the second sees is what the first left behind.
    """
    kept: list[SnakeDriver] = [_open_driver()]

    def borrow() -> SnakeDriver:
        return kept.pop()

    def give_back(driver: SnakeDriver) -> None:
        kept.append(driver)

    def close_all() -> None:
        for driver in kept:
            driver.close()

    made = SnakePool(borrow, give_back, close_all)
    yield made
    with made.connection() as driver:
        driver.execute(f"DROP TABLE IF EXISTS {_TABLE}", ())
        driver.commit()


def _rows(driver: SnakeDriver) -> int:
    """How many rows the connection can see right now."""
    counted = driver.fetch_all(f"SELECT count(*) FROM {_TABLE}", ())[0][0]
    # The driver answers `object` because a row is untyped at this level; the cast is here and not
    # at every call site, and it is the only place that knows the column is a count.
    assert isinstance(counted, int)
    return counted


def test_work_left_uncommitted_does_not_reach_the_next_borrower(
    pool: SnakePool,
) -> None:
    """A loan that writes and never commits must leave the pool as it found it.

    The row is the whole assertion: if the second borrower can see it, the transaction survived the
    hand-back and the next caller is working inside a stranger's unit of work — able to commit it by
    accident, or to have its own rolled back with it.
    """
    with pool.connection() as first:
        first.execute(f"INSERT INTO {_TABLE} VALUES (1)", ())
        assert _rows(first) == 1, "the write did not happen at all"

    with pool.connection() as second:
        assert _rows(second) == 0, (
            "the uncommitted write survived the return to the pool: the seam does not clean up"
        )


def test_a_savepoint_does_not_outlive_the_loan(pool: SnakePool) -> None:
    """A savepoint left open must be gone by the next borrow, not waiting to be rolled back into.

    Rolling back to a savepoint somebody else marked is the sharpest version of the same failure:
    the name still resolves, so nothing raises, and the caller silently undoes work that was never
    theirs.
    """
    with pool.connection() as first:
        first.execute(f"INSERT INTO {_TABLE} VALUES (1)", ())
        first.savepoint("sp_contract")

    with pool.connection() as second:
        with pytest.raises(Exception, match="sp_contract"):
            second.rollback_to_savepoint("sp_contract")


def test_a_committed_loan_is_not_undone_by_the_cleanup(pool: SnakePool) -> None:
    """The counter-proof: cleaning up on the way back must not throw away work that WAS committed.

    Without this, a `rollback()` on every hand-back would pass the two tests above and quietly
    destroy every committed write — the cure being worse than what it cures.
    """
    with pool.connection() as first:
        first.execute(f"INSERT INTO {_TABLE} VALUES (7)", ())
        first.commit()

    with pool.connection() as second:
        assert _rows(second) == 1


class _RollbackExplodes:
    """A driver whose `rollback()` raises, which is what a dead socket looks like from here.

    The database restarted, or the firewall cut the idle connection, or there was a failover: the
    library notices when the ORM asks it to do something, and `rollback` is the first thing the pool
    asks on the way out.
    """

    def __init__(self) -> None:
        self.closed = False

    def rollback(self) -> None:
        raise ConnectionError("connection already closed")

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...

    def execute(self, sql: str, params: object) -> int:
        return 0

    def fetch_all(self, sql: str, params: object) -> list[tuple[object, ...]]:
        return []

    def fetch_iter(
        self, sql: str, params: object, *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from ()

    @property
    def last_insert_id(self) -> int:
        return 0


def test_a_connection_whose_rollback_fails_is_still_handed_back() -> None:
    """The clean-up may fail; the RETURN may not be skipped because of it.

    The order used to be `rollback()` then `give_back()`, with nothing in between to catch. So when
    the rollback raised, `give_back` never ran, the idempotency guard stopped any retry from fixing
    it, and the backing pool went on counting that connection as lent — for ever. Ten of those
    during a database restart leave a `maximum=10` pool PERMANENTLY dry: `SnakePoolTimeout` on every
    later request, with the process alive and the database long since recovered.

    `pre_ping` does not save it: that checks on the way OUT of the pool, not on the way back in.
    """
    returned: list[object] = []
    broken = _RollbackExplodes()
    pool = SnakePool(
        # a stand-in for a connection that died mid-loan
        lambda: broken,  # type: ignore[arg-type]
        returned.append,  # type: ignore[arg-type]
        lambda: None,
    )

    driver = pool.acquire()
    with pytest.raises(ConnectionError):
        driver.close()

    assert returned == [broken], (
        "the connection was lost: the pool will never lend it again"
    )


def test_a_failure_on_the_way_out_does_not_hide_the_callers_own_error() -> None:
    """A blow-up while cleaning up must not REPLACE the exception the caller was already raising.

    `SnakePool.connection()` closes in a `finally`, so an `InterfaceError` from the clean-up used to
    come out INSTEAD of the business error that ended the block — and that is the error somebody is
    trying to read at three in the morning. It rides along as a note instead of taking its place.
    """
    broken = _RollbackExplodes()
    pool = SnakePool(
        lambda: broken,  # type: ignore[arg-type]
        lambda driver: None,
        lambda: None,
    )

    with pytest.raises(ValueError, match="the caller's own problem") as caught:
        with pool.connection():
            raise ValueError("the caller's own problem")

    assert any(
        "rollback" in note or "clean" in note for note in caught.value.__notes__
    ), "the clean-up failure vanished entirely: it has to travel, just not in front"
