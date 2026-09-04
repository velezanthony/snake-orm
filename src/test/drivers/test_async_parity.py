"""Async parity: the same Protocol, the same three engines and the same composition root.

The async seam existed by halves, and the halves that were missing were exactly the ones that stop a
silent failure:

- `AsyncDriver` did not declare `last_insert_id`, which `SnakeDriver` does have and whose docstring
  says "engines WITHOUT RETURNING (MySQL)". It did not blow up because the only async driver was
  Postgres, which recovers the PK through RETURNING. The day a MySQL one existed, the autoincrement
  PK would have been left at `None` without a word.
- There was no async path in `SnakeConnectionConfig`, which is the piece that EXISTS to stop you
  from pairing a `SQLiteDriver` with a `PostgresDialect`. So the async user was hand-wiring exactly
  what that module prevents.
- And there was an async driver for only one of the three engines, with all three declared first
  class.

On what the new drivers are like: they wrap the synchronous one in a thread of THEIR OWN instead of
speaking a native asyncio protocol. It is not a cheat, it is what `aiosqlite` does on the inside;
and for MySQL it gives real concurrency, because Python releases the GIL while the socket waits.
What would be better is a native driver (`aiomysql`), and that is why the adapter says so in its own
docstring instead of letting you believe it already is one.
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from snakeorm import (
    AsyncDriver,
    AsyncSession,
    AsyncSQLiteDriver,
    SnakeBackend,
    SnakeConnectionConfig,
    SQLiteDialect,
)
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.drivers.base import SnakeDriver
from snakeorm.drivers.threaded import ThreadedAsyncDriver


def test_the_two_driver_protocols_declare_the_same_members() -> None:
    """Verifies that no member lives in one Protocol and is missing from the other.

    It is the net for the pattern this project keeps repeating: implemented or verified in N-1 out of
    N siblings. Comparing the surfaces MECHANICALLY is the only thing that has caught it reliably;
    remembering to add it to both has never once worked.
    """
    sincronos = {name for name in dir(SnakeDriver) if not name.startswith("_")}
    asincronos = {name for name in dir(AsyncDriver) if not name.startswith("_")}

    assert sincronos == asincronos, (
        f"only in the synchronous one: {sorted(sincronos - asincronos)}; "
        f"only in the async one: {sorted(asincronos - sincronos)}"
    )


def test_the_two_sessions_declare_the_same_public_surface() -> None:
    """The same net one level up, where it did NOT exist: `SnakeSession` vs `AsyncSession`.

    The driver Protocols had this and the sessions did not, which is the asymmetry the file's own
    header is about: the half that is missing is the one that stops a silent failure. A method added
    to one session and forgotten in the other leaves the async user without it and nothing says so.
    """
    from snakeorm import SnakeSession

    sincronos = {name for name in dir(SnakeSession) if not name.startswith("_")}
    asincronos = {name for name in dir(AsyncSession) if not name.startswith("_")}

    assert sincronos == asincronos, (
        f"only in the synchronous one: {sorted(sincronos - asincronos)}; "
        f"only in the async one: {sorted(asincronos - sincronos)}"
    )


def test_an_async_sqlite_driver_reads_and_writes() -> None:
    """Verifies that the async SQLite driver really executes, not just satisfies the signature."""

    async def scenario() -> list[tuple[object, ...]]:
        driver = await AsyncSQLiteDriver.connect(":memory:")
        try:
            await driver.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, n TEXT)", ())
            await driver.execute("INSERT INTO t (n) VALUES (?)", ("uno",))
            return await driver.fetch_all("SELECT id, n FROM t", ())
        finally:
            await driver.close()

    assert asyncio.run(scenario()) == [(1, "uno")]


def test_the_async_driver_hands_over_the_last_insert_id_of_its_engine() -> None:
    """Verifies the member that was missing from the Protocol: the adapter DELEGATES it downwards.

    It is checked with a pretend driver returning a recognisable value, and not against SQLite,
    because the SQLite one returns 0 by contract —that engine recovers the PK through RETURNING—.
    Asserting a 1 there would have been a test that passes by coincidence and documents a falsehood.

    It is in MySQL that the autoincrement PK depends on this value, and that is why having it in the
    Protocol is what stops the async MySQL driver from being born leaving the PK at `None` silently.
    """

    class _ConId:
        """Minimal driver that only knows how to say which id it wrote."""

        @property
        def last_insert_id(self) -> int:
            return 42

        def close(self) -> None: ...

    async def scenario() -> int:
        driver = await ThreadedAsyncDriver.open(lambda: cast("SnakeDriver", _ConId()))
        try:
            return driver.last_insert_id
        finally:
            await driver.close()

    assert asyncio.run(scenario()) == 42


def test_async_streaming_does_not_materialise_the_whole_result() -> None:
    """Verifies that `fetch_iter` yields rows one at a time in async too.

    It is the part of the contract that cannot be taken for granted when wrapping a synchronous
    driver: the generator has to stay lazy as it crosses the thread, or async `iterate()` would turn
    into an `all()` under another name.
    """

    async def scenario() -> list[object]:
        driver = await AsyncSQLiteDriver.connect(":memory:")
        try:
            await driver.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)", ())
            for _ in range(5):
                await driver.execute("INSERT INTO t DEFAULT VALUES", ())
            vistas: list[object] = []
            async for row in driver.fetch_iter("SELECT id FROM t", (), chunk=2):
                vistas.append(row[0])
                if len(vistas) == 3:
                    break  # cutting mid-iteration must not blow up nor drag the rest along
            return vistas
        finally:
            await driver.close()

    assert asyncio.run(scenario()) == [1, 2, 3]


def test_the_connection_config_pairs_driver_and_dialect_in_async_too() -> None:
    """Verifies that the composition root has an async path.

    `SnakeConnectionConfig` exists so that the user does not pick driver and dialect separately and
    end up with a `SQLiteDriver` speaking Postgres. Without `open_async()`, the async user wired the
    two pieces by hand: precisely what this module prevents.
    """

    async def scenario() -> AsyncSession:
        config = SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
        session = await config.open_async()
        try:
            return session
        finally:
            await session.close()

    session = asyncio.run(scenario())
    assert isinstance(session._dialect, SQLiteDialect)  # noqa: SLF001 - the pairing is checked


@pytest.mark.parametrize("backend", list(SnakeBackend), ids=lambda b: b.name)
def test_no_backend_is_left_without_an_async_driver(backend: SnakeBackend) -> None:
    """Verifies that EVERY engine at least gets as far as attempting the async connection.

    This test used to check the opposite —that an engine WITHOUT an async driver would shout— and it
    passed for the worst of reasons: the `async` extra was not installed, so the `ImportError` it
    expected came from psycopg being absent, not from a decision of the ORM. Green because of a
    missing dependency. It came out when `make sync` got fixed, which now installs the extras and
    left the test without its excuse.

    And its premise no longer has a subject: the three engines are first class and all three have an
    async driver. What does deserve a net is exhaustiveness — that adding a `SnakeBackend` without
    its branch in `async_driver_and_dialect` is not discovered on the first request using that path.

    It is checked by the KIND of failure: getting as far as the connection and being refused (there
    is no server on these routes) proves the engine is accounted for. What cannot show up is a
    `SnakeConfigError`, an `ImportError` or an `AttributeError`, which are the three shapes of
    "nobody here knows this engine".
    """
    config = SnakeConnectionConfig(
        backend=backend, name="/proc/snakeorm_no_existe", host="127.0.0.1", port="1"
    )

    async def scenario() -> None:
        await config.open_async()

    with pytest.raises(Exception) as fallo:  # noqa: B017 - the type is exactly what is examined
        asyncio.run(scenario())

    assert not isinstance(
        fallo.value, SnakeConfigError | ImportError | AttributeError
    ), (
        f"{backend.name} does not manage to connect along the async path: it failed with "
        f"{type(fallo.value).__name__} ({fallo.value})"
    )
