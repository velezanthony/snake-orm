"""Connection pool: lend one CONNECTION per session, not one per statement."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from time import monotonic, sleep

from snakeorm.core.exceptions import SnakePoolTimeout
from snakeorm.drivers.base import SnakeDriver

Borrow = Callable[[], SnakeDriver]
GiveBack = Callable[[SnakeDriver], None]
CloseAll = Callable[[], None]
Discard = Callable[[SnakeDriver], None]
"""How a connection is THROWN AWAY, as opposed to returned to the pool. `pre_ping` and `recycle` need it."""
Clock = Callable[[], float]
"""Where the time comes from. Injectable so recycling can be tested without really waiting."""

_MAX_DISCARDS = 3
"""Dead connections in a row before giving up. Three are not bad luck: it is the database, not the connection."""


class _PooledDriver:
    """A lent driver: identical to the real one except that `close()` RETURNS it to the pool.
    The connection is lent for the whole session, not per statement: a driver HOLDS a transaction
    (if INSERT and COMMIT went through different connections, the transaction would be lost).
    """

    __slots__ = ("_inner", "_give_back", "_returned")

    def __init__(self, inner: SnakeDriver, give_back: GiveBack) -> None:
        self._inner = inner
        self._give_back = give_back
        self._returned = False

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Delegates the query to the lent connection."""
        return self._inner.fetch_all(sql, params)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Delegates the streaming to the lent connection.

        The connection does NOT go back to the pool once the iteration runs out: it stays lent to
        the session, like any other query. Returning it here would rip it away from a live
        transaction.
        """
        return self._inner.fetch_iter(sql, params, chunk=chunk)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Delegates the statement to the lent connection."""
        return self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT (see the Protocol). Forwarded to the wrapped driver."""
        return self._inner.last_insert_id

    def commit(self) -> None:
        """Commits the lent connection's transaction."""
        self._inner.commit()

    def rollback(self) -> None:
        """Rolls back the lent connection's transaction."""
        self._inner.rollback()

    def savepoint(self, name: str) -> None:
        """Marks a savepoint on the lent connection."""
        self._inner.savepoint(name)

    def release_savepoint(self, name: str) -> None:
        """Releases a savepoint on the lent connection."""
        self._inner.release_savepoint(name)

    def rollback_to_savepoint(self, name: str) -> None:
        """Rolls back to a savepoint on the lent connection."""
        self._inner.rollback_to_savepoint(name)

    def close(self) -> None:
        """RETURNS the connection to the pool instead of closing it, ROLLED BACK. Idempotent.

        The rollback is the pool's contract and not a courtesy. Whatever the borrower left open —
        an uncommitted write, a savepoint it never released — belongs to a unit of work that is
        over, and the next borrower must not be able to see it, commit it by accident, or roll its
        own work back into it. A savepoint is the sharpest case: the name still resolves, so
        `rollback_to_savepoint` on a stranger's mark raises nothing and quietly undoes work.

        It used to be `give_back` alone, and the promise held only because the one pool this project
        ships is psycopg2's, whose `putconn` rolls back on its own. `SnakePool` takes `give_back`
        from whoever builds it, so a pool written for SQLite or MySQL got no cleaning at all — the
        guarantee was BORROWED from a library rather than kept by the seam.

        Note this does not undo committed work: a commit ended its transaction, and the rollback
        finds nothing to discard. `test_a_committed_loan_is_not_undone_by_the_cleanup` is the net
        under that, because a cure that threw away commits would pass every other test here.
        """
        if self._returned:
            return  # returning it twice would hand it to two users at once
        self._returned = True
        try:
            self._inner.rollback()
        finally:
            # The RETURN is not optional; the CLEAN-UP is what may fail. Without this `finally` a
            # rollback that raised —a restarted database, a cut socket, a failover— skipped
            # `give_back` entirely, and the idempotency guard above stopped any retry from putting
            # it right: the backing pool went on counting that connection as lent, for ever. Ten of
            # those leave a `maximum=10` pool permanently dry, with the process alive and the
            # database recovered. It is the very failure `_MAX_DISCARDS` exists to prevent
            # —"process alive, no errors and no progress"— coming in through the next door along.
            self._give_back(self._inner)


class SnakePool:
    """Hands out connections and takes them back. Engine-agnostic: it receives the three operations
    and delegates the real pooling (`psycopg2.pool` today). Only the rule lives here: one connection
    per session, returned when it is done.
    """

    __slots__ = (
        "_borrow",
        "_give_back",
        "_close_all",
        "_discard",
        "_pre_ping",
        "_recycle",
        "_timeout",
        "_retry_interval",
        "_clock",
        "_born",
    )

    def __init__(
        self,
        borrow: Borrow,
        give_back: GiveBack,
        close_all: CloseAll,
        *,
        discard: Discard | None = None,
        pre_ping: bool = False,
        recycle_seconds: float | None = None,
        timeout_seconds: float | None = None,
        retry_interval: float = 0.05,
        clock: Clock = monotonic,
    ) -> None:
        self._borrow = borrow
        self._give_back = give_back
        self._close_all = close_all
        # How a connection is THROWN AWAY (as opposed to returned). Without this, `pre_ping` and
        # `recycle` would have nowhere to send the bad connection: returning it would put it back
        # in the queue.
        self._discard = discard
        self._pre_ping = pre_ping
        self._recycle = recycle_seconds
        self._timeout = timeout_seconds
        self._retry_interval = retry_interval
        self._clock = clock
        # When the pool first saw each connection, for `recycle`. The DRIVER lives in the value,
        # and that is what makes the key mean anything: while the entry exists the object cannot
        # die, so CPython cannot hand its address to the next connection. Keyed by `id()` alone, a
        # brand-new connection inherits a dead one's birthday and gets thrown away for being too
        # old, and `_born` is only ever cleaned in `_throw_away`, so the stale entry outlives
        # everything.
        #
        # Not a `WeakKeyDictionary`, and it is measured: `LoggingDriver` and `TimeoutDriver`
        # declare `__slots__` without `__weakref__`, so it raises `TypeError` on exactly the
        # wrapping the production guide recommends.
        #
        # Nothing is recorded unless `recycle_seconds` is set: holding a reference to every
        # connection the pool has ever seen would trade a bookkeeping bug for a socket leak.
        self._born: dict[int, tuple[SnakeDriver, float]] = {}

    def acquire(self) -> SnakeDriver:
        """Lends a HEALTHY connection, wrapped: closing it sends it back to the pool.

        With `timeout_seconds`, it retries until the deadline if the pool is drained instead of
        giving up on the first attempt (which is what `psycopg2` does: it does not block, it
        raises `PoolError` instantly). With `pre_ping` or `recycle_seconds`, it throws away
        whatever is no good and keeps looking.
        """
        deadline = None if self._timeout is None else self._clock() + self._timeout
        discarded = 0
        while True:
            try:
                inner = self._borrow()
            except Exception:
                if deadline is None or self._clock() >= deadline:
                    if deadline is None:
                        raise
                    raise SnakePoolTimeout(
                        f"No connection came free in {self._timeout} s. The pool is "
                        f"exhausted for longer than you are willing to wait: either there is too "
                        f"much load or too little pool (or somebody is not giving their "
                        f"connections back)."
                    ) from None
                sleep(self._retry_interval)
                continue
            if self._usable(inner):
                if self._recycle is not None:
                    self._born.setdefault(id(inner), (inner, self._clock()))
                return _PooledDriver(inner, self._give_back)
            self._throw_away(inner)
            discarded += 1
            # A cap on the discarding. Without it, a downed database would turn this into an
            # infinite loop throwing connections away and asking for another: the process alive,
            # with no errors and making no progress, which is the worst possible failure. Three
            # dead in a row are not bad luck: it is the DATABASE, not the connection, and the
            # caller has to hear that.
            if discarded >= _MAX_DISCARDS:
                raise SnakePoolTimeout(
                    f"The last {discarded} connections in the pool were dead. This is not one "
                    f"connection being unlucky: the database is not answering (restart, failover, "
                    f"network?). The pool has already thrown them away; retry when it comes back."
                )
            if deadline is not None and self._clock() >= deadline:
                raise SnakePoolTimeout(
                    f"No connection in the pool answered in {self._timeout} s."
                )

    def _usable(self, inner: SnakeDriver) -> bool:
        """Is this connection any good? It checks the AGE first (free) and then the pulse (costs a round trip)."""
        if self._recycle is not None:
            recorded = self._born.get(id(inner))
            # `recorded[0] is inner` is the whole guard: an entry left by a dead connection that
            # happened to hold this address answers about somebody else, and the age it carries is
            # not this connection's.
            if (
                recorded is not None
                and recorded[0] is inner
                and self._clock() - recorded[1] >= self._recycle
            ):
                return False
        if not self._pre_ping:
            return True
        try:
            inner.execute("SELECT 1", ())
        except Exception:
            # Any exception: the connection is broken and it does not matter why. Telling the
            # reasons apart here would be putting one engine's jargon into the very piece that
            # exists so as not to have it.
            return False
        return True

    def _throw_away(self, inner: SnakeDriver) -> None:
        """Takes the connection out of the pool for good. Without `discard`, it at least closes it."""
        self._born.pop(id(inner), None)
        if self._discard is not None:
            self._discard(inner)
        else:
            inner.close()

    @contextmanager
    def connection(self) -> Iterator[SnakeDriver]:
        """Lends a connection and ALWAYS returns it, even if the block blows up (or it drains the pool bit by bit)."""
        driver = self.acquire()
        try:
            yield driver
        except BaseException as error:
            # The caller's exception WINS. Closing in a plain `finally` meant a clean-up failure
            # came out instead of the business error that ended the block, and that second one is
            # what somebody is trying to read at three in the morning. The clean-up still has to
            # travel — losing it would hide a dying pool — so it rides as a note (PEP 678).
            try:
                driver.close()
            except BaseException as cleanup:  # noqa: BLE001 - it is re-attached, never swallowed
                error.add_note(
                    f"and the pool failed to clean up on the way out: {cleanup!r}"
                )
            raise
        else:
            driver.close()

    def close(self) -> None:
        """Closes every connection in the pool."""
        self._close_all()


def psycopg_pool(
    dsn: str,
    *,
    minimum: int = 1,
    maximum: int = 10,
    pre_ping: bool = False,
    recycle_seconds: float | None = None,
    timeout_seconds: float | None = None,
) -> SnakePool:
    """Builds a `SnakePool` on top of psycopg2's threaded pool.

    `pre_ping` checks the pulse before lending (it costs a round trip, and it saves the deployment
    where the database restarts and the pool carries on handing out dead connections).
    `recycle_seconds` throws away connections older than that without asking. `timeout_seconds`
    waits for one to be freed instead of giving up instantly, which is what psycopg2 does on its
    own.

    All three are OFF by default: turning them on costs round trips or throws away healthy
    connections, and that is decided by whoever knows their deployment, not by the library.

    Lazy import: do not force psycopg2 on whoever only generates SQL or migrations without
    connecting.
    """
    from psycopg2.pool import ThreadedConnectionPool

    from snakeorm.drivers.psycopg import PsycopgDriver, with_utc_timezone

    # Here too: the pool opens its own connections and without this they would speak in a
    # different time zone than the standalone driver's, depending on which way you came in.
    backend = ThreadedConnectionPool(minimum, maximum, with_utc_timezone(dsn))

    # One driver per CONNECTION, kept across loans. `SnakePool` tracks a connection's age by the
    # object `borrow` hands it, so building a fresh wrapper every time made every loan look newborn
    # and `recycle_seconds` discarded nothing — with the lifetime set to a hundred thousand seconds,
    # zero discards, in the ONLY pool this project ships. Adopting once and reusing gives the pool
    # the stable identity its bookkeeping needs, and costs one dict.
    adopted: dict[object, SnakeDriver] = {}

    def borrow() -> SnakeDriver:
        # `adopt` is the customs post: it adapts psycopg2's concrete type to our minimal DBAPI at an edge.
        connection = backend.getconn()
        driver = adopted.get(connection)
        if driver is None:
            driver = PsycopgDriver.adopt(connection)
            adopted[connection] = driver
        return driver

    def give_back(driver: SnakeDriver) -> None:
        # The connection is recovered from the driver itself, not from a map keyed by `id()`: that
        # one falls out of sync as soon as the driver is wrapped, and returning the wrong
        # connection to the pool is fiendishly hard to track down.
        if isinstance(driver, PsycopgDriver):
            # The `type: ignore` is a STRUCTURAL vs NOMINAL clash, not a hole: it is the SAME object
            # that came out of `getconn()`, only each type system looks at it its own way.
            backend.putconn(driver._connection)  # type: ignore[arg-type]  # noqa: SLF001

    def discard(driver: SnakeDriver) -> None:
        # `close=True` is the difference between returning and THROWING AWAY: without it, the bad
        # connection goes back in the queue and the next one to ask for it gets the same problem.
        if isinstance(driver, PsycopgDriver):
            # Out of the map too, or a connection thrown away would keep its old wrapper alive and
            # the next `getconn()` reusing that slot would inherit somebody else's age.
            adopted.pop(driver._connection, None)  # noqa: SLF001
            backend.putconn(driver._connection, close=True)  # type: ignore[arg-type]  # noqa: SLF001

    return SnakePool(
        borrow,
        give_back,
        backend.closeall,
        discard=discard,
        pre_ping=pre_ping,
        recycle_seconds=recycle_seconds,
        timeout_seconds=timeout_seconds,
    )
