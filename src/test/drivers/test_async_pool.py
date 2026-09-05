"""The async pool: the same three safeguards as the synchronous one, and the same discard cap.

In async the pool matters MORE, not less: a hundred concurrent tasks open a hundred connections if
nobody hands them out, and every Postgres connection costs memory on the server even while idle.

It is tested with doubles and a fake clock because what has to be verified is the RULE, not the
pooling library: that an old connection gets recycled, that a dead one gets discarded, that
exhausting the pool waits instead of giving up, and that a database that is down ends up shouting
instead of spinning in an infinite loop. Against a real server those four things either cannot be
provoked or take minutes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

from snakeorm.core.exceptions import SnakePoolTimeout
from snakeorm.drivers.asyncpool import AsyncSnakePool


class _Connection:
    """Pretend connection that knows how to be alive or dead and tells whether it was closed."""

    def __init__(self, *, viva: bool = True) -> None:
        self.viva = viva
        self.cerrada = False
        self.ejecutadas: list[str] = []

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        return []

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        for row in await self.fetch_all(sql, params):
            yield row

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        if not self.viva:
            raise ConnectionError("the connection is dead")
        self.ejecutadas.append(sql)
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def savepoint(self, name: str) -> None: ...
    async def release_savepoint(self, name: str) -> None: ...
    async def rollback_to_savepoint(self, name: str) -> None: ...

    async def close(self) -> None:
        self.cerrada = True


class _Store:
    """A pretend pool: a queue of connections that get lent out and given back.

    With `abre_nuevas`, when it runs out of free ones it opens one instead of failing — which is what
    a real pool does until it reaches its maximum size. Without that, a discard would leave the store
    empty and the test would measure the scarcity of its own double instead of the rule it wants to
    check.
    """

    def __init__(
        self, conexiones: list[_Connection], *, abre_nuevas: bool = False
    ) -> None:
        self.libres = list(conexiones)
        self.tiradas: list[_Connection] = []
        self._abre_nuevas = abre_nuevas

    async def borrow(self) -> _Connection:
        if not self.libres:
            if not self._abre_nuevas:
                raise RuntimeError("pool agotado")
            return _Connection()
        return self.libres.pop(0)

    async def give_back(self, driver: object) -> None:
        self.libres.append(driver)  # type: ignore[arg-type]

    async def discard(self, driver: object) -> None:
        self.tiradas.append(driver)  # type: ignore[arg-type]

    async def close_all(self) -> None: ...


def test_closing_a_borrowed_connection_returns_it_instead_of_closing_it() -> None:
    """Verifies the rule that holds the whole pool up: `close()` RETURNS, it does not close.

    It is what lets nothing upstream know there is a pool at all: the session closes its driver when
    it finishes, as always, and the connection goes back into the queue.
    """
    connection = _Connection()
    store = _Store([connection])
    pool = AsyncSnakePool(store.borrow, store.give_back, store.close_all)

    async def scenario() -> None:
        driver = await pool.acquire()
        await driver.close()

    asyncio.run(scenario())

    assert connection.cerrada is False
    assert store.libres == [connection]


def test_returning_the_same_connection_twice_does_not_duplicate_it() -> None:
    """Verifies that a repeated `close()` does not put the connection into the queue twice.

    If it did, two tasks would each believe they had their own and would write over the same
    transaction. It is among the hardest failures to find that a pool can have, and it is caused by
    something as ordinary as a session that closes plus an outer `finally` that closes too.
    """
    connection = _Connection()
    store = _Store([connection])
    pool = AsyncSnakePool(store.borrow, store.give_back, store.close_all)

    async def scenario() -> None:
        driver = await pool.acquire()
        await driver.close()
        await driver.close()

    asyncio.run(scenario())

    assert store.libres == [connection]


def test_a_dead_connection_is_discarded_and_a_live_one_served() -> None:
    """Verifies `pre_ping`: the dead connection is thrown away and the caller gets a healthy one.

    It is the failover case: the server restarts and the pool is left full of dead connections.
    Without this, the next request takes one and fails for something that is not its fault.
    """
    muerta, viva = _Connection(viva=False), _Connection()
    store = _Store([muerta, viva])
    pool = AsyncSnakePool(
        store.borrow,
        store.give_back,
        store.close_all,
        discard=store.discard,
        pre_ping=True,
    )

    async def scenario() -> object:
        driver = await pool.acquire()
        await driver.close()
        return driver

    asyncio.run(scenario())

    assert store.tiradas == [muerta]
    assert store.libres == [viva]


def test_an_old_connection_is_recycled_before_the_server_kills_it() -> None:
    """Verifies `recycle_seconds`, with a fake clock because the real one would take the full term.

    Many servers cut idle connections off on their own. Recycling by age throws them away BEFORE,
    which is the difference between a silent discard and an error in production.
    """
    stale = _Connection()
    store = _Store([stale], abre_nuevas=True)
    ahora = [0.0]
    pool = AsyncSnakePool(
        store.borrow,
        store.give_back,
        store.close_all,
        discard=store.discard,
        recycle_seconds=10.0,
        clock=lambda: ahora[0],
    )

    async def scenario() -> None:
        first = await pool.acquire()  # marks the birth of `stale`
        await first.close()
        ahora[0] = 11.0  # the term expires
        segunda = await pool.acquire()
        await segunda.close()

    asyncio.run(scenario())

    assert store.tiradas == [stale]


def test_an_exhausted_pool_waits_instead_of_giving_up_at_once() -> None:
    """Verifies that with `timeout_seconds` it WAITS, and that when the term runs out it says why.

    `psycopg2` does not hang on an exhausted pool: it raises instantly. The timeout is not there to
    avoid a hang, it is there so you can wait for somebody to give theirs back.
    """
    store = _Store([])
    pool = AsyncSnakePool(
        store.borrow,
        store.give_back,
        store.close_all,
        timeout_seconds=0.05,
        retry_interval=0.01,
    )

    async def scenario() -> None:
        await pool.acquire()

    with pytest.raises(
        SnakePoolTimeout,
        match="The pool is exhausted for longer than you are willing to wait",
    ):
        asyncio.run(scenario())


def test_a_database_that_is_down_stops_the_loop_instead_of_spinning() -> None:
    """Verifies the discard CAP, which is not a knob: it is an insurance against the worst failure.

    Without it, a database that is down leaves the pool throwing connections away and asking for
    another one forever: the process alive, with no errors and making no progress. No alert notices
    that.
    """
    dead = [_Connection(viva=False) for _ in range(10)]
    store = _Store(dead)
    pool = AsyncSnakePool(
        store.borrow,
        store.give_back,
        store.close_all,
        discard=store.discard,
        pre_ping=True,
    )

    async def scenario() -> None:
        await pool.acquire()

    with pytest.raises(SnakePoolTimeout, match="the database is not answering"):
        asyncio.run(scenario())

    assert len(store.tiradas) == 3
