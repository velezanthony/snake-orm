"""`AsyncSession` against a real Postgres, with psycopg 3.

The unit tests compare the SQL each session DECIDES to emit. This one checks that the asynchronous
driver really does execute it and that the rows come back converted into instances.

It skips gracefully when there is no Postgres or when `snakeorm[async]` is not installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from typing import TypeVar

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    AsyncPsycopgDriver,
    AsyncSession,
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
    snake_to_many,
    snake_to_one,
)
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

# The header of this file promised to skip "when `snakeorm[async]` is not installed", and that
# guard did not exist: there was only the one for a missing Postgres. Without it, an environment
# without the extra —which is OPTIONAL on purpose, because psycopg2 has no native async— gave five
# red failures that mean nothing. An extra that is not there is not a failure; it is an extra that
# is not there.
pytest.importorskip(
    "psycopg",
    reason="the async path needs psycopg 3: install `snakeorm[async]`",
)

pytestmark = pytest.mark.integration


@snake_model(table="asye_orders")
class Order(SnakeModel):
    """Minimal model for the asynchronous path."""

    id: SnakeColumn[int] = snake_auto()
    customer: SnakeColumn[str] = snake_str()
    amount: SnakeColumn[int] = snake_int()
    lines: SnakeToMany["Line"] = snake_to_many("order")


@pytest.fixture
def table() -> Iterator[None]:
    """Creates and cleans the table with the SYNCHRONOUS driver: setting up needs no async."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS asye_orders CASCADE", ())
    driver.execute(emit_create_table(snake_table(Order), PostgresDialect()), ())
    driver.commit()
    try:
        yield
    finally:
        driver.execute("DROP TABLE IF EXISTS asye_orders CASCADE", ())
        driver.commit()
        driver.close()


R = TypeVar("R")


async def _with_session(work: Callable[[AsyncSession], Awaitable[R]]) -> R:
    """Opens an asynchronous session, runs the work and closes whatever happens."""
    driver = await AsyncPsycopgDriver.connect(dsn())
    session = AsyncSession(driver, PostgresDialect())
    try:
        return await work(session)
    finally:
        await driver.close()


def test_the_full_write_and_read_cycle_works(table: None) -> None:
    """The full cycle through the asynchronous path: insert, commit and read back."""

    async def work(session: AsyncSession) -> list[Order]:
        await session.add(Order(customer="ana", amount=100))
        await session.add(Order(customer="bea", amount=250))
        await session.commit()
        return await session.all(SnakeQuery(Order).order_by(Order.amount.desc()))

    rows = asyncio.run(_with_session(work))

    assert [order.customer for order in rows] == ["bea", "ana"]
    assert all(isinstance(order, Order) for order in rows)


def test_returning_fills_the_generated_key(table: None) -> None:
    """The `RETURNING` works the same in async: the generated PK comes back into the object.

    It is the proof that the colourless PLAN applies the same on both paths — the decision of which
    columns to bring back and where to place them is taken in `planning.py`, not twice.
    """

    async def work(session: AsyncSession) -> Order:
        order = Order(customer="ana", amount=10)
        await session.add(order)
        await session.commit()
        return order

    order = asyncio.run(_with_session(work))

    assert order.id is not None and order.id > 0


def test_count_and_delete_work(table: None) -> None:
    """Counting and deleting by PK, awaiting."""

    async def work(session: AsyncSession) -> tuple[int, int]:
        order = Order(customer="ana", amount=10)
        await session.add(order)
        await session.commit()
        before = await session.count(SnakeQuery(Order))
        await session.delete(order)
        await session.commit()
        return before, await session.count(SnakeQuery(Order))

    before, after = asyncio.run(_with_session(work))

    assert (before, after) == (1, 0)


def test_a_rollback_undoes_the_write(table: None) -> None:
    """Transaction control belongs to the user, just as in the synchronous session."""

    async def work(session: AsyncSession) -> int:
        await session.add(Order(customer="ana", amount=10))
        await session.rollback()
        return await session.count(SnakeQuery(Order))

    assert asyncio.run(_with_session(work)) == 0


@snake_model(table="asye_lines")
class Line(SnakeModel):
    """Child of Order: it exists to test the to-many `include` in async."""

    id: SnakeColumn[int] = snake_auto()
    order_id: SnakeColumn[int] = snake_int()
    order: SnakeToOne[Order] = snake_to_one(order_id)
    concepto: SnakeColumn[str] = snake_str()


@pytest.fixture
def with_lines() -> Iterator[None]:
    """Both tables, and the linking done."""
    import psycopg2

    from snakeorm.linker import snake_link

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    snake_link()
    driver.execute("DROP TABLE IF EXISTS asye_lines, asye_orders CASCADE", ())
    for model in (Order, Line):
        driver.execute(emit_create_table(snake_table(model), PostgresDialect()), ())
    driver.commit()
    try:
        yield
    finally:
        driver.execute("DROP TABLE IF EXISTS asye_lines, asye_orders CASCADE", ())
        driver.commit()
        driver.close()


def test_include_loads_the_children_without_n_plus_one(with_lines: None) -> None:
    """The to-many `include` works in async, and it costs TWO queries, not N+1.

    It is the last thing the asynchronous session was missing to have the same surface as the
    synchronous one. And the count is half the test: loading relations on the back of one query per
    parent "works" just as well in the tests and falls apart with real data.
    """
    from snakeorm import AsyncLoggingDriver, AsyncPsycopgDriver, AsyncSession

    sql_lines: list[str] = []

    async def work() -> list[Order]:
        raw = await AsyncPsycopgDriver.connect(dsn())
        driver = AsyncLoggingDriver(raw, write=sql_lines.append)
        session = AsyncSession(driver, PostgresDialect())
        try:
            order = await session.add(Order(customer="ana", amount=100))
            await session.add_all(
                [
                    Line(order_id=order.id, concepto="a"),
                    Line(order_id=order.id, concepto="b"),
                ]
            )
            await session.commit()
            sql_lines.clear()
            return await session.all(SnakeQuery(Order).include(Order.lines))
        finally:
            await driver.close()

    orders = asyncio.run(work())

    assert len(orders) == 1
    assert sorted(line.concepto for line in orders[0].lines) == ["a", "b"]
    queries = [line for line in sql_lines if "SELECT" in line]
    assert len(queries) == 2, (
        f"parents + children: DOS consultas, fueron {len(queries)}"
    )
