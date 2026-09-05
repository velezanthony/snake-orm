"""INTEGRATION: the pool against a real Postgres, with connections that are really dead.

`test/drivers/test_pool_production.py` already covers the LOGIC of the pool: it discards what is no
good, waits until the deadline, gives up after three dead ones. And it does so with doubles, which
is the right thing for testing a state machine — but it leaves two assumptions unchecked, and both
of them are about psycopg2, not about us:

1. That a `SELECT 1` over a REALLY dead connection raises. The double raises because we told it to.
   If psycopg2 returned a silent error, or hung, `pre_ping` would be useless and every unit test
   would still be green.
2. That an exhausted `ThreadedConnectionPool` raises something `acquire()` recognises. The waiting
   loop catches `Exception` from the `borrow()`; if psycopg2 hung instead of raising, the
   `timeout_seconds` would never apply and nobody would find out until production.

Killing the connection is done with `pg_terminate_backend` from ANOTHER connection, which is exactly
what happens on a restart, a failover or an `idle_session_timeout`: the client does not find out
until it tries to use it.

It skips gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.core.exceptions import SnakePoolTimeout
from snakeorm.drivers import PsycopgDriver, SnakePool, psycopg_pool
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@pytest.fixture
def killer() -> Iterator[PsycopgDriver]:
    """A SEPARATE connection, the only one able to kill the ones in the pool.

    It has to be another one: a connection cannot terminate itself and still report what happened.
    """
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    try:
        yield driver
    finally:
        driver.close()


def _lend_and_kill(pool: SnakePool, killer: PsycopgDriver) -> None:
    """Takes a connection out of the pool, returns it to the queue and KILLS it on the server.

    ONLY that backend is killed, by its PID, and not every connection of the database. The first
    version did the latter and passed —out of sheer ordering luck—: any fixture from another module
    holding a live connection would have been taken down with it, and the failure would have shown
    up in a test that has nothing to do with this one. A landmine, basically.

    Returning it BEFORE killing it is what reproduces the real case: the pool keeps a connection in
    its queue believing it healthy, and the client does not find out until someone tries to use it.
    """
    lent = pool.acquire()
    pid = lent.fetch_all("SELECT pg_backend_pid()", ())[0][0]
    lent.close()
    killer.execute("SELECT pg_terminate_backend(%s)", (pid,))


def _pool(**options: object) -> SnakePool:
    """A small pool against the real Postgres. Small so it can be exhausted on purpose."""
    return psycopg_pool(dsn(), minimum=1, maximum=2, **options)  # type: ignore[arg-type]


def test_pre_ping_replaces_a_connection_the_server_really_killed(
    killer: PsycopgDriver,
) -> None:
    """Checks that with `pre_ping` a REALLY dead connection is discarded and a live one arrives.

    This is the scenario that justifies the whole option: the database restarts, the pool keeps its
    queue of connections and hands them out as if nothing had happened. A double can simulate the
    failure; only a server can confirm that psycopg2 signals it in a way `_usable()` can recognise.
    """
    pool = _pool(pre_ping=True)
    _lend_and_kill(pool, killer)

    revived = pool.acquire()
    try:
        assert revived.fetch_all("SELECT 1", ()) == [(1,)]
    finally:
        revived.close()
        pool.close()


def test_without_pre_ping_the_dead_connection_is_handed_out(
    killer: PsycopgDriver,
) -> None:
    """Checks that WITHOUT `pre_ping` the dead connection is handed out all the same, and blows up.

    It is the half that gives meaning to the previous one: if the pool recovered on its own,
    `pre_ping` would not be needed and its cost —one round trip per loan— would not be justified.
    The option ships off by default precisely because that cost is decided by whoever knows their
    own deployment.
    """
    import psycopg2

    pool = _pool()
    _lend_and_kill(pool, killer)

    dead = pool.acquire()
    try:
        with pytest.raises(psycopg2.Error):
            dead.fetch_all("SELECT 1", ())
    finally:
        pool.close()


def test_an_exhausted_pool_gives_up_after_its_timeout(killer: PsycopgDriver) -> None:
    """Checks that with the pool exhausted `acquire()` waits out its deadline and RAISES, not hangs.

    Hanging indefinitely was the behaviour the plan wanted ruled out, and it is the worst of the
    three possible ones: a live process, with no errors and making no progress. Here the pool is
    really exhausted —maximum=2, two loaned out— and the deadline is checked from both sides: that
    it raises, and that it waited FIRST. Without the second one, a pool that gave up instantly
    would pass just the same, and the `timeout_seconds` would be decorative.
    """
    from time import monotonic

    pool = _pool(timeout_seconds=0.3)
    first, second = pool.acquire(), pool.acquire()
    try:
        start = monotonic()
        with pytest.raises(SnakePoolTimeout, match="0.3"):
            pool.acquire()
        expected = monotonic() - start

        assert expected >= 0.3, (
            f"it gave up in {expected:.3f} s with a 0.3 deadline: it never waited"
        )
    finally:
        first.close()
        second.close()
        pool.close()


def test_a_freed_connection_is_handed_to_the_next_acquire(
    killer: PsycopgDriver,
) -> None:
    """A returned connection is available again to the next borrower.

    It used to be called `..._unblocks_the_waiting_acquire`, and nothing here ever waits: the
    `close()` happens BEFORE the `acquire()`, so `_borrow()` succeeds on its first attempt and the
    retry loop does not run once. The `timeout_seconds=2.0` was decorative. What it really checks is
    worth checking, so it is renamed rather than deleted — and the property its old name promised is
    the test below, which does make threads contend.
    """
    pool = _pool(timeout_seconds=2.0)
    first, second = pool.acquire(), pool.acquire()
    second.close()  # a free slot: the next acquire has to find it

    third = pool.acquire()
    try:
        assert third.fetch_all("SELECT 1", ()) == [(1,)]
    finally:
        third.close()
        first.close()
        pool.close()


def test_the_pool_never_lends_one_connection_to_two_threads_at_once(
    killer: PsycopgDriver,
) -> None:
    """Eight threads over a pool of two: no backend is ever held by two of them at the same time.

    This is the property the class exists for, and nothing exercised it. The test above promised
    contention in its name and arranged for there to be none; here the threads really do queue.

    Identity comes from `pg_backend_pid()` — the SERVER's view of which connection this is — rather
    than from the Python object, because the object could be re-wrapped and still be the same
    session. Overlap is detected by holding each one for a moment and recording who is inside.
    """
    import threading
    import time

    pool = _pool(timeout_seconds=5.0)
    inside: set[int] = set()
    overlaps: list[int] = []
    lock = threading.Lock()

    def work() -> None:
        with pool.connection() as driver:
            pid = driver.fetch_all("SELECT pg_backend_pid()", ())[0][0]
            assert isinstance(pid, int)
            with lock:
                if pid in inside:
                    overlaps.append(pid)
                inside.add(pid)
            time.sleep(
                0.05
            )  # held long enough for a second thread to collide if it can
            with lock:
                inside.discard(pid)

    threads = [threading.Thread(target=work) for _ in range(8)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        pool.close()

    assert not any(thread.is_alive() for thread in threads), (
        "a thread never got a connection"
    )
    assert overlaps == [], (
        f"backend(s) {overlaps} were held by two threads at once: the pool lent one connection twice"
    )
