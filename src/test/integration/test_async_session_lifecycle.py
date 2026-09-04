"""`async with AsyncSession(...)` and the two async methods nobody had ever called, on all three.

`AsyncSession.__aenter__`/`__aexit__`, `_run_prefetch` and `delete_where` were published API that no
test and no demo had ever executed — `grep "async with .*[Ss]ession"` over the whole repo returned
one hit, and it was `async with session.savepoint()`.

The commit is proved with a `rollback()` AFTER the block: if `__aexit__` did not commit, the
rollback takes the write with it. Reading straight back would pass on a session that committed
nothing, because an open transaction sees its own writes.
"""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import Awaitable, Callable

import pytest

from snakeorm import (
    AsyncSession,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_model,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from test.scenarios.engines import three_async_sessions

pytest.importorskip(
    "psycopg",
    reason="the async path needs psycopg 3: install `snakeorm[async]`",
)

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="asyl_orders")
class Order(SnakeModel):
    """The parent side, so `include()` has a collection to prefetch."""

    id: SnakeColumn[int] = snake_auto()
    customer: SnakeColumn[str] = snake_str(max_length=50)
    amount: SnakeColumn[int] = snake_int()
    lines: SnakeToMany["Line"] = snake_to_many("order")


@snake_model(table="asyl_lines")
class Line(SnakeModel):
    """The child side."""

    id: SnakeColumn[int] = snake_auto()
    order_id: SnakeColumn[int] = snake_int()
    order: SnakeToOne[Order] = snake_to_one(order_id)
    label: SnakeColumn[str] = snake_str(max_length=50)


def _run(
    engine: str, path: pathlib.Path, work: Callable[[AsyncSession], Awaitable[None]]
) -> None:
    """Opens the three engines, hands the one under test to `work`, and tears everything down."""
    from snakeorm.linker import snake_link

    snake_link()

    async def scenario() -> None:
        async with three_async_sessions(
            [Order, Line], sqlite_path=str(path / "lifecycle.db")
        ) as sessions:
            await work(sessions[engine])

    asyncio.run(scenario())


@pytest.mark.parametrize("engine", _ENGINES)
def test_leaving_the_block_cleanly_commits(engine: str, tmp_path: pathlib.Path) -> None:
    """`__aexit__` commits, and the rollback afterwards is what proves it did."""

    async def work(session: AsyncSession) -> None:
        async with session:
            await session.add(Order(customer="ana", amount=10))

        await session.rollback()

        assert await session.count(SnakeQuery(Order)) == 1, (
            "leaving the block did not COMMIT: the rollback took the write with it"
        )

    _run(engine, tmp_path, work)


@pytest.mark.parametrize("engine", _ENGINES)
def test_leaving_the_block_does_not_close_the_connection(
    engine: str, tmp_path: pathlib.Path
) -> None:
    """The half that is easy to get wrong: the docstring promises the connection stays open."""

    async def work(session: AsyncSession) -> None:
        async with session:
            await session.add(Order(customer="ana", amount=10))

        assert await session.count(SnakeQuery(Order)) == 1

    _run(engine, tmp_path, work)


@pytest.mark.parametrize("engine", _ENGINES)
def test_an_exception_inside_the_block_rolls_back(
    engine: str, tmp_path: pathlib.Path
) -> None:
    """The other branch, and the exception must still reach the caller."""

    class Boom(RuntimeError):
        pass

    async def work(session: AsyncSession) -> None:
        with pytest.raises(Boom):
            async with session:
                await session.add(Order(customer="leaked", amount=99))
                raise Boom

        assert await session.count(SnakeQuery(Order)) == 0, (
            "the block did not ROLL BACK: the write survived an exception"
        )

    _run(engine, tmp_path, work)


@pytest.mark.parametrize("engine", _ENGINES)
def test_include_of_a_collection_runs_on_the_async_path(
    engine: str, tmp_path: pathlib.Path
) -> None:
    """`_run_prefetch` had never executed: `include()` of a to-many was untried in async."""

    async def work(session: AsyncSession) -> None:
        order = await session.add(Order(customer="ana", amount=10))
        await session.add(Line(order_id=order.id, label="first"))
        await session.add(Line(order_id=order.id, label="second"))
        await session.commit()

        loaded = await session.all(SnakeQuery(Order).include(Order.lines))

        assert [line.label for line in loaded[0].lines] == ["first", "second"]

    _run(engine, tmp_path, work)


@pytest.mark.parametrize("engine", _ENGINES)
def test_delete_where_removes_only_what_matches(
    engine: str, tmp_path: pathlib.Path
) -> None:
    """`delete_where` had never executed either. The survivor is what makes it an assertion."""

    async def work(session: AsyncSession) -> None:
        await session.add(Order(customer="ana", amount=10))
        await session.add(Order(customer="bea", amount=20))
        await session.commit()

        removed = await session.delete_where(
            SnakeQuery(Order).filter(Order.customer == "ana")
        )
        await session.commit()

        assert removed == 1
        assert [row.customer for row in await session.all(SnakeQuery(Order))] == ["bea"]

    _run(engine, tmp_path, work)
