"""Tests of the three pieces the pool was missing in order to survive a Tuesday afternoon.

`SnakePool` lent connections out and took them back, which is the easy part. The hard part of a pool
is **what happens when the connection is rotten and you do not know it**, and of that there was
nothing:

- `pre_ping`: the database restarts (a deployment, a failover) and the pool keeps handing out dead
  connections. The error does not come out in the pool: it comes out in the user's first query.
- `recycle`: MySQL's `wait_timeout` closes idle connections on its own. The pool does not find out
  and lends them anyway.
- `timeout`: with the pool exhausted, `psycopg2` raises `PoolError` INSTANTLY. A traffic spike blows
  up even if a connection were going to be released 50 ms later.

All three are tested here with injected operations, with no database: `SnakePool` is engine-agnostic
on purpose —it receives borrow/give-back/discard/close and only supplies the policy— and that is
exactly what makes it genuinely testable.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.core.exceptions import SnakePoolTimeout
from snakeorm.drivers import SnakePool


class _FakeDriver:
    """Fake connection that can be HEALTHY or DEAD, and notes down whether it was closed."""

    def __init__(self, name: str, *, alive: bool = True) -> None:
        self.name = name
        self.alive = alive
        self.closed = False
        self.pings = 0

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        if not self.alive:
            raise OSError("server closed the connection unexpectedly")
        return [(1,)]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.pings += 1
        if not self.alive:
            raise OSError("server closed the connection unexpectedly")
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...

    def close(self) -> None:
        self.closed = True


class _Backend:
    """Fake pool: it serves the connections it is given and records give-backs and discards."""

    def __init__(self, *connections: _FakeDriver) -> None:
        self.available = list(connections)
        self.returned: list[_FakeDriver] = []
        self.discarded: list[_FakeDriver] = []

    def borrow(self) -> _FakeDriver:
        # LIFO, like `psycopg2.pool`: it pops from the end and `putconn` returns to the end. It
        # matters for recycling —the one you just released is the next one out— and a FIFO would
        # not exercise it.
        if not self.available:
            raise RuntimeError("connection pool exhausted")
        return self.available.pop()

    def give_back(self, driver: object) -> None:
        assert isinstance(driver, _FakeDriver)
        self.returned.append(driver)
        self.available.append(driver)

    def discard(self, driver: object) -> None:
        assert isinstance(driver, _FakeDriver)
        driver.close()
        self.discarded.append(driver)

    def close_all(self) -> None: ...


def test_without_pre_ping_a_dead_connection_is_handed_out() -> None:
    """Pins down the behaviour WITHOUT `pre_ping`: the dead connection comes out of the pool as is.

    It is not a test of a shortcoming for the fun of it: it documents that `pre_ping` costs one
    round trip per loan, so turning it off is a legitimate option and you need to know what you buy.
    """
    muerta = _FakeDriver("muerta", alive=False)
    backend = _Backend(muerta)
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)
    driver = pool.acquire()
    with pytest.raises(OSError):
        driver.fetch_all("SELECT 1", ())


def test_pre_ping_discards_a_dead_connection_and_serves_a_live_one() -> None:
    """Verifies that with `pre_ping` the dead connection is DISCARDED and the user gets a healthy one.

    It is the deployment case: the database restarts, every connection in the pool is left dead and
    without this the error shows up in the user's first query, not here.
    """
    muerta, sana = _FakeDriver("muerta", alive=False), _FakeDriver("sana")
    backend = _Backend(sana, muerta)  # LIFO: the dead one comes out first
    pool = SnakePool(
        backend.borrow,
        backend.give_back,
        backend.close_all,
        discard=backend.discard,
        pre_ping=True,
    )
    driver = pool.acquire()
    assert driver.fetch_all("SELECT 1", ()) == [(1,)]
    assert backend.discarded == [muerta]
    assert muerta.closed is True


def test_pre_ping_costs_one_round_trip_on_the_live_connection() -> None:
    """Verifies that the ping really happens (and only once) on the connection being lent out."""
    sana = _FakeDriver("sana")
    backend = _Backend(sana)
    pool = SnakePool(
        backend.borrow,
        backend.give_back,
        backend.close_all,
        discard=backend.discard,
        pre_ping=True,
    )
    pool.acquire()
    assert sana.pings == 1


def test_pre_ping_gives_up_if_every_connection_is_dead() -> None:
    """Verifies that if ALL of them are dead it raises instead of spinning forever.

    With no cap, a database that is down would turn `acquire()` into an infinite loop discarding
    connections — the worst possible failure: the process alive, with no errors, and making no
    progress.
    """
    backend = _Backend()
    backend.available = []
    sin_fin = {"n": 0}

    def borrow_muerta() -> _FakeDriver:
        sin_fin["n"] += 1
        return _FakeDriver(f"muerta{sin_fin['n']}", alive=False)

    pool = SnakePool(
        borrow_muerta,
        backend.give_back,
        backend.close_all,
        discard=backend.discard,
        pre_ping=True,
    )
    with pytest.raises(SnakePoolTimeout, match="the database is not answering"):
        pool.acquire()
    assert sin_fin["n"] == 3  # the cap cuts in; it does not spin forever


def test_recycle_discards_a_connection_older_than_its_lifetime() -> None:
    """Verifies that a connection older than `recycle` is thrown away even if it answers.

    It is MySQL's `wait_timeout`: the server closes idle ones on its own and the pool does not find
    out. Recycling by age does not ask, it prevents.
    """
    clock = {
        "t": 0.0
    }  # controlled, not a sequence: the number of reads is an internal detail
    stale, fresh = _FakeDriver("stale"), _FakeDriver("fresh")
    backend = _Backend(fresh, stale)  # LIFO: `stale` is the first one out
    pool = SnakePool(
        backend.borrow,
        backend.give_back,
        backend.close_all,
        discard=backend.discard,
        recycle_seconds=60,
        clock=lambda: clock["t"],
    )
    pool.acquire().close()  # born at t=0 and goes back into the pool
    clock["t"] = 100.0  # 100 s go by: the old one exceeds its 60 s of useful life
    pool.acquire()
    assert backend.discarded == [stale]


def test_a_young_connection_is_not_recycled() -> None:
    """Verifies that recycling does not get too clever: within its lifetime the connection is reused."""
    clock = {"t": 0.0}
    connection = _FakeDriver("unica")
    backend = _Backend(connection)
    pool = SnakePool(
        backend.borrow,
        backend.give_back,
        backend.close_all,
        discard=backend.discard,
        recycle_seconds=60,
        clock=lambda: clock["t"],
    )
    clock["t"] = 10.0  # within its useful life
    pool.acquire().close()
    pool.acquire()
    assert backend.discarded == []


def test_an_exhausted_pool_fails_fast_without_a_timeout() -> None:
    """Pins down the behaviour WITHOUT `timeout`: once exhausted, the engine failure comes out raw.

    It is what `psycopg2` does today: `PoolError` instantly, without waiting. It does not hang —it
    gives up—, and that is why the remedy is to wait a little, not to stop hanging.
    """
    backend = _Backend()
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)
    with pytest.raises(RuntimeError, match="exhausted"):
        pool.acquire()


def test_the_timeout_waits_for_a_connection_before_giving_up() -> None:
    """Verifies that with `timeout` it RETRIES until the term and takes a late release.

    A traffic spike should not blow up because a connection was going to come free 50 ms later.
    """
    backend = _Backend()
    liberada = _FakeDriver("tarde")

    intentos = {"n": 0}

    def borrow_con_retraso() -> _FakeDriver:
        intentos["n"] += 1
        if intentos["n"] < 3:  # the first two times the pool is still full
            raise RuntimeError("connection pool exhausted")
        return liberada

    pool = SnakePool(
        borrow_con_retraso,
        backend.give_back,
        backend.close_all,
        timeout_seconds=5,
        retry_interval=0,
    )
    assert pool.acquire() is not None
    assert intentos["n"] == 3


def test_the_timeout_gives_up_and_says_so() -> None:
    """Verifies that once the term runs out `SnakePoolTimeout` is raised, not the raw engine error.

    The engine error says "pool exhausted", which does not tell "there is no room right now" apart
    from "we have been waiting for thirty seconds". The second is a capacity problem and deserves a
    name of its own, because the action it calls for is a different one.
    """
    clock = {"t": 0.0}
    backend = _Backend()

    def borrow_agotado() -> _FakeDriver:
        clock["t"] += 2.0  # each attempt burns time; by the third it is past the term
        raise RuntimeError("connection pool exhausted")

    pool = SnakePool(
        borrow_agotado,
        backend.give_back,
        backend.close_all,
        timeout_seconds=5,
        retry_interval=0,
        clock=lambda: clock["t"],
    )
    with pytest.raises(SnakePoolTimeout, match="5"):
        pool.acquire()


def test_the_defaults_keep_the_old_behaviour() -> None:
    """Verifies that with nothing configured, the pool behaves EXACTLY as it did before.

    The three pieces are opt-in: `pre_ping` costs a round trip per loan and `recycle` throws healthy
    connections away. Turning them on by default would be deciding a cost for the user that they may
    not want.
    """
    connection = _FakeDriver("unica")
    backend = _Backend(connection)
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)
    driver = pool.acquire()
    driver.close()
    assert (connection.pings, connection.closed, backend.returned) == (
        0,
        False,
        [connection],
    )


def test_the_pool_ages_a_connection_by_the_object_it_was_handed() -> None:
    """`SnakePool` measures age per driver OBJECT, so `borrow` must return a stable one.

    Stating the contract, because breaking it is invisible. `SnakePool` is engine-agnostic: all it
    ever sees is whatever `borrow` returns, so two different wrappers around one connection are two
    different connections as far as it can tell, and each loan looks newborn. That is exactly what
    `psycopg_pool` used to do — `PsycopgDriver.adopt(backend.getconn())` on every loan — so
    `recycle_seconds` discarded nothing in the only pool this project ships.

    The fix belongs on the `borrow` side and lives there; this pins the expectation the fix relies
    on, so the next pool written against this seam reads the requirement instead of discovering it.
    """
    inner = _FakeDriver("long-lived")
    clock = {"t": 0.0}
    discarded: list[str] = []
    pool = SnakePool(
        lambda: (
            inner
        ),  # STABLE: the same object for the same connection, as the contract asks
        lambda driver: None,
        lambda: None,
        discard=lambda driver: discarded.append("thrown away"),
        recycle_seconds=60,
        clock=lambda: clock["t"],
    )

    pool.acquire()
    clock["t"] = 10_000.0
    pool.acquire()  # past its lifetime: thrown away, and the next one is born now

    assert discarded, (
        "a connection well past its lifetime was handed out instead of recycled: the age is not "
        "reaching the pool"
    )


def test_a_new_connection_does_not_inherit_a_dead_ones_birthday() -> None:
    """A connection's age is ITS OWN, not whatever object last held that memory address.

    `_born` was keyed by `id(inner)` while the comment above it said, word for word, that it goes
    "per object and not per `id()`: `id()`s get recycled once the object dies and it would end up
    measuring the neighbour's age". The comment described the fix; the line below it was the bug.

    CPython reuses the address of a freed object for the next one of the same size, and a pool
    borrows and drops connections all day, so the reuse is not a curiosity — it is the normal case.
    A brand-new connection then inherited a dead one's birthday and got thrown away for being too
    old, and `_born` was only ever cleaned in `_throw_away`, so the stale entry outlived everything.

    Keeping the driver in the VALUE is what fixes it: while the entry exists the object cannot die,
    so its address cannot be handed to anybody else. `WeakKeyDictionary` does NOT work here, and it
    is measured: `LoggingDriver` and `TimeoutDriver` declare `__slots__` without `__weakref__`, so
    it raises `TypeError` on exactly the wrapping the production guide recommends.
    """
    now = 0.0
    seen_ids: set[int] = set()
    discarded: list[_FakeDriver] = []

    def borrow() -> _FakeDriver:
        # No reference is kept anywhere, so each of these is free to die —and to leave its
        # address to the next one— the moment the pool is done with it.
        fresh = _FakeDriver("rotating")
        seen_ids.add(id(fresh))
        return fresh

    pool = SnakePool(
        borrow,  # type: ignore[arg-type]
        lambda driver: None,
        lambda: None,
        discard=discarded.append,  # type: ignore[arg-type]
        recycle_seconds=10.0,
        clock=lambda: now,
    )

    for _ in range(200):
        pool.acquire().close()
        now += 1.0

    # Deliberately NOT asserted: that an address got reused. Under the fix it CANNOT be — holding
    # the driver in the value is exactly what stops CPython handing its address to the next one —
    # so demanding the collision would be demanding the bug back. The property is asserted instead.
    assert len(seen_ids) == 200, "each loan really was a distinct connection object"
    assert discarded == [], (
        "a connection born this instant was thrown away for being too old: it inherited the "
        "birthday of a dead one that had held the same address"
    )
