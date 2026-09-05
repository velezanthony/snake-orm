"""`session.explain(query)` asks the engine for its plan, on all three.

It lives entirely ABOVE the driver seam: the compiler already hands back `(sql, params)`, so the
dialect wraps the statement and the existing `fetch_all` runs it. Nothing in the driver Protocol
changes for this.

What is NOT done here is a typed row. Postgres answers one column, SQLite four and MySQL about a
dozen, and `plan_raw` checks the width strictly and positionally — one `@snake_row` cannot serve the
three, and normalising them would be inventing a shape over three things that share no fields.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
)
from test.scenarios.engines import three_async_sessions, three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="explain_widgets")
class Widget(SnakeModel):
    """Something to ask a plan about."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=50)
    stock: SnakeColumn[int] = snake_int()


@pytest.fixture
def engines() -> object:
    """The three synchronous sessions, seeded so a plan has rows to talk about."""
    with three_sessions([Widget]) as sessions:
        for session in sessions.values():
            session.add(Widget(id=1, name="tuerca", stock=5))
            session.add(Widget(id=2, name="tornillo", stock=0))
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_plan_comes_back_and_names_the_table(engine: str, engines: object) -> None:
    """Every engine answers something, and what it answers is ABOUT the table we asked for.

    Checking only "the list is not empty" would pass on an engine that explained the wrong
    statement, which is the one way this can go wrong quietly.
    """
    session: SnakeSession = engines[engine]  # type: ignore[index]

    plan = session.explain(SnakeQuery(Widget))

    assert plan, f"{engine} answered no plan at all"
    assert any("explain_widgets" in line for line in plan), (
        f"{engine} answered a plan that never mentions the table: {plan}"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_filtered_query_keeps_its_parameters(engine: str, engines: object) -> None:
    """The half that a naive implementation breaks: the values still travel as PARAMETERS.

    A version that pasted the filter into the string would work here too, so what makes this an
    assertion is that the statement reaching the engine is the compiled one — a placeholder with no
    parameter behind it is a syntax error on all three.
    """
    session: SnakeSession = engines[engine]  # type: ignore[index]

    plan = session.explain(SnakeQuery(Widget).filter(Widget.name == "tuerca"))

    assert plan, f"{engine} answered no plan for a filtered query"


@pytest.mark.parametrize("engine", _ENGINES)
def test_explaining_does_not_run_the_query(engine: str, engines: object) -> None:
    """A plan is a plan: the rows must not come back as data.

    The filter is on `stock` and what is looked for is a `name`, and that is the whole design of the
    assertion. Filtering on `name` and looking for the same name FAILS on Postgres for an innocent
    reason — it prints the condition into the plan (`Filter: ((name)::text = 'tornillo'::text)`), so
    the value being there proves the filter exists, not that anything ran.

    Asking across columns removes that: only the row carries `tornillo`, and the row is exactly what
    must not appear.
    """
    session: SnakeSession = engines[engine]  # type: ignore[index]

    plan = session.explain(SnakeQuery(Widget).filter(Widget.stock == 0))

    assert not any("tornillo" in line for line in plan), (
        f"{engine} returned the ROWS instead of the plan: {plan}"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_async_session_explains_the_same_way(
    engine: str, tmp_path: pathlib.Path
) -> None:
    """The async twin, because a method on one session and not the other is this repo's oldest bug."""

    async def scenario() -> None:
        async with three_async_sessions(
            [Widget], sqlite_path=str(tmp_path / "explain.db")
        ) as sessions:
            session = sessions[engine]
            await session.add(Widget(id=1, name="tuerca", stock=5))
            await session.commit()

            plan = await session.explain(SnakeQuery(Widget))

            assert plan, f"{engine} answered no plan at all in async"
            assert any("explain_widgets" in line for line in plan)

    asyncio.run(scenario())
