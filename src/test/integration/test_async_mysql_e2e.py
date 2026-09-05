"""`AsyncSession` against a real MariaDB, through `AsyncPyMySQLDriver`.

That driver is exported, documented as one of the three async paths, and appeared in ZERO test
files — not one query, ever. The engine with the most to prove on this path was the one with
nothing behind it: unlike psycopg 3, PyMySQL has no native async, so this driver serves its
synchronous twin from a thread of its own, and whether that bridge actually works is not something
the SQL-level unit tests can answer.

MySQL is also where the async path has the most to lose. It has no `RETURNING`, so the id comes
back through `lastrowid` — a per-connection value — and a bridge that reused connections across
tasks would hand back somebody else's id. Writing a row and reading it back is what asks that
question.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Coroutine, Iterator, Sequence
from typing import Any, TypeVar

import pytest

from snakeorm import (
    AsyncPyMySQLDriver,
    AsyncSession,
    MySQLDialect,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    snake_auto,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.dialects.matrix import flavour_of
from snakeorm.migration import emit_create_table
from test.conftest import NO_MYSQL_REASON

T = TypeVar("T")


@snake_model(table="async_mi_notas")
class Nota(SnakeModel):
    """One table, on purpose: what is under test is the driver, not the mapping."""

    id: SnakeColumn[int] = snake_auto()
    cuerpo: SnakeColumn[str] = snake_str(max_length=80)


def _run(work: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Runs a coroutine in its own loop, the way each test wants one.

    `Coroutine` and not `Awaitable`: `asyncio.run` demands one, and the wider annotation only made
    the checker take the return type as `Never`.
    """
    return asyncio.run(work())


def _mysql_kwargs() -> dict[str, object]:
    """The connection, from the same variables the synchronous MySQL e2e reads."""
    host = os.environ.get("MYSQL_HOST")
    if not host:
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    return {
        "host": host,
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DB", "snakeorm_db"),
    }


@pytest.fixture(scope="module")
def session() -> Iterator[AsyncSession]:
    """An async MySQL session with the table already created."""
    kwargs = _mysql_kwargs()
    import pymysql

    async def open_it() -> AsyncPyMySQLDriver:
        return await AsyncPyMySQLDriver.connect(**kwargs)

    try:
        driver = _run(open_it)
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    dialect = MySQLDialect()

    async def prepare() -> None:
        await driver.execute("DROP TABLE IF EXISTS async_mi_notas", ())
        await driver.execute(emit_create_table(snake_table(Nota), dialect), ())
        await driver.commit()

    _run(prepare)
    yield AsyncSession(driver, dialect)
    _run(lambda: driver.close())


def test_a_row_written_asynchronously_comes_back_as_its_model(
    session: AsyncSession,
) -> None:
    """Write and read over the thread bridge: the round trip, which is the whole question.

    PyMySQL has no native async, so this driver serves the synchronous one from a thread of its
    own. Whether that bridge carries a statement out and its rows back is not something a test over
    emitted SQL can answer — it is the one thing only a real server can.
    """

    async def work() -> list[Nota]:
        await session.add(Nota(cuerpo="escrita sin bloquear el bucle"))
        await session.commit()
        return await session.all(SnakeQuery(Nota))

    filas = _run(work)

    assert [fila.cuerpo for fila in filas] == ["escrita sin bloquear el bucle"]
    assert isinstance(filas[0].id, int) and filas[0].id > 0


def test_the_id_comes_back_from_lastrowid_and_belongs_to_this_row(
    session: AsyncSession,
) -> None:
    """MySQL has no `RETURNING`: the id arrives through `lastrowid`, a PER-CONNECTION value.

    Which is why this is worth its own test on THIS engine. A bridge that handed different tasks
    the same connection would return somebody else's id — a number that looks perfectly valid,
    written into a foreign key, and wrong. Reading the row back by the id it claims is what tells
    the two apart.
    """

    async def work() -> tuple[int, list[Nota]]:
        nota = Nota(cuerpo="la que reclama su id")
        await session.add(nota)
        await session.commit()
        leidas = await session.all(SnakeQuery(Nota).filter(Nota.id == nota.id))
        return nota.id, leidas

    identificador, leidas = _run(work)

    assert [fila.cuerpo for fila in leidas] == ["la que reclama su id"], (
        f"id {identificador} does not name the row that was just written"
    )


def test_the_bridge_does_not_block_the_event_loop(session: AsyncSession) -> None:
    """While a query is in flight, other tasks keep running. That is the whole point of the thread.

    Serving a synchronous driver from a thread is only worth anything if the loop stays free; done
    wrong it is a synchronous driver with extra ceremony. The counter is what tells them apart: it
    can only advance if something else got to run while the query was out.
    """
    ticks = 0

    async def contar() -> None:
        nonlocal ticks
        for _ in range(50):
            await asyncio.sleep(0.001)
            ticks += 1

    async def work() -> Sequence[Nota]:
        contador = asyncio.create_task(contar())
        filas = await session.all(SnakeQuery(Nota))
        await contador
        return filas

    _run(work)

    assert ticks > 0, "nothing else ran while the query was out: the loop was blocked"


def test_the_async_route_reads_the_flavour_like_the_synchronous_one() -> None:
    """Capabilities belong to the ENGINE, not to how it is reached.

    MariaDB has `RETURNING` whether you talk to it with a blocking driver or an awaited one, so the
    two routes have to answer the same. They did not: `async_driver_and_dialect` built a bare
    `MySQLDialect()` and every async application kept the intersection of both flavours — no
    failure, just the narrow answer, in silence.
    """
    kwargs = _mysql_kwargs()
    import pymysql

    async def ask() -> str:
        driver = await AsyncPyMySQLDriver.connect(**kwargs)
        try:
            return await driver.server_version()
        finally:
            await driver.close()

    try:
        version = _run(ask)
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    assert version, "the async driver could not say what the server calls itself"
    assert flavour_of(version) is not None, (
        f"the flavour of {version!r} was not recognised, so the async route would silently "
        f"keep the intersection of MariaDB and MySQL"
    )
