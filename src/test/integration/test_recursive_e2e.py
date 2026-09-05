"""`WITH RECURSIVE` RUN on the THREE engines: the whole tree with ONE query.

The emission proves that the string says `WITH RECURSIVE`. Only running it proves what matters:
that it goes down to ALL the levels (not just the direct children), that it does not bring back
foreign branches, and that reversing the pair of columns walks the tree the other way round.

And the query count is the entire argument for the feature: without it, walking a hierarchy of N
levels costs N queries.

It skips gracefully if there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    LoggingDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.drivers.base import SnakeDriver
from snakeorm.drivers.timeout import TimeoutDriver
from test.scenarios.engines import DIALECTS, three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="rec_e2e_nodes")
class Node(SnakeModel):
    """Tree: each node points at its parent in the same table."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    parent_id: SnakeColumn[int | None] = snake_int()
    name: SnakeColumn[str] = snake_str()


# The test tree. Two branches from the root and THREE levels of depth under 2, so that a walk that
# only goes down one level shows up.
#
#   1 `raiz`
#   ├── 2 `child`          10 `other-root`
#   │   ├── 4 `nieto`     └── 11 `its-child`
#   │   │   └── 5 bisnieto
#   │   └── 6 nieto-b
#   └── 3 child-b
_TREE = [
    (1, None, "raiz"),
    (2, 1, "child"),
    (3, 1, "child-b"),
    (4, 2, "nieto"),
    (5, 4, "bisnieto"),
    (6, 2, "nieto-b"),
    (10, None, "other-root"),
    (11, 10, "its-child"),
]


_ENGINES = ["postgres", "mysql", "sqlite"]

Stand = dict[str, tuple[SnakeSession, list[str]]]


@pytest.fixture
def engines() -> Iterator[Stand]:
    """The three sessions with the tree loaded, each with its OWN log of executed SQL.

    The log is what makes the one-query claim checkable, and it arrives through the `wrap` hook of
    the harness rather than by opening three connections here — which is how the third engine used
    to get dropped.
    """
    logs: dict[str, list[str]] = {name: [] for name in _ENGINES}

    def wrap(engine: str, driver: SnakeDriver) -> SnakeDriver:
        return LoggingDriver(driver, write=logs[engine].append)

    with three_sessions([Node], wrap=wrap) as sessions:
        for name, session in sessions.items():
            session.add_all([Node(id=i, parent_id=p, name=n) for i, p, n in _TREE])
            session.commit()
            logs[name].clear()
        yield {name: (session, logs[name]) for name, session in sessions.items()}


@pytest.mark.parametrize("engine", _ENGINES)
def test_it_walks_every_level_of_the_subtree(engine: str, engines: Stand) -> None:
    """It goes down to ALL the levels, not just the direct children.

    The great-grandchild (5) is three hops from the root. A walk that stopped at one level would
    return 1, 2, 3 and would look right at a glance — that is why the tree has depth.
    """
    built, _ = engines[engine]
    descendants = (
        SnakeQuery(Node)
        .filter(Node.id == 1)
        .recursive(on=(Node.parent_id, Node.id))
        .order_by(Node.id.asc())
    )

    assert [node.id for node in built.all(descendants)] == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize("engine", _ENGINES)
def test_it_does_not_bring_other_branches(engine: str, engines: Stand) -> None:
    """The other tree (10, 11) does NOT appear: the recursion follows the link, not the whole table."""
    built, _ = engines[engine]
    result = built.all(
        SnakeQuery(Node).filter(Node.id == 2).recursive(on=(Node.parent_id, Node.id))
    )

    assert sorted(node.id for node in result) == [2, 4, 5, 6]


@pytest.mark.parametrize("engine", _ENGINES)
def test_reversing_the_pair_walks_up_to_the_ancestors(
    engine: str, engines: Stand
) -> None:
    """Reversing the pair climbs up through the ANCESTORS. Same machinery, opposite direction.

    It is the proof that the direction is set by the ORDER of the columns and not by a flag: from
    the great-grandchild (5) you climb 5 -> 4 -> 2 -> 1.
    """
    built, _ = engines[engine]
    ancestors = (
        SnakeQuery(Node).filter(Node.id == 5).recursive(on=(Node.id, Node.parent_id))
    )

    assert sorted(node.id for node in built.all(ancestors)) == [1, 2, 4, 5]


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_whole_tree_costs_exactly_one_query(engine: str, engines: Stand) -> None:
    """THE argument for the feature: a four-level tree in ONE query.

    Without `WITH RECURSIVE` you have to go down level by level, one query per level, and you do
    not even know how many levels there are until one comes back empty. That is the N+1 by another
    name.
    """
    built, lines = engines[engine]
    lines.clear()

    built.all(
        SnakeQuery(Node).filter(Node.id == 1).recursive(on=(Node.parent_id, Node.id))
    )

    queries = [line for line in lines if "SELECT" in line]
    assert len(queries) == 1, f"it should be ONE query, it was {len(queries)}"


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_limit_bounds_the_walk(engine: str, engines: Stand) -> None:
    """The `limit()` bounds the RESULT, and that is all it does.

    This docstring used to call it the safety net against a cycle. It is not, and the shape right
    below is the counter-example: with `order_by()` in front, Postgres has to produce every row
    before it can sort them, so over cyclic data the same query never returns and the `LIMIT 3`
    never gets its turn. What ends a cyclic walk is `recursive(..., distinct=True)`, and
    `test_distinct_makes_a_cyclic_walk_finish` is where that gets run.
    """
    built, _ = engines[engine]
    result = built.all(
        SnakeQuery(Node)
        .filter(Node.id == 1)
        .recursive(on=(Node.parent_id, Node.id))
        .order_by(Node.id.asc())
        .limit(3)
    )

    assert [node.id for node in result] == [1, 2, 3]


@snake_model(table="rec_e2e_cycle")
class Ring(SnakeModel):
    """The same shape as `Node`, over data that BITES ITS OWN TAIL. Its own table so the tree stays clean."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    parent_id: SnakeColumn[int | None] = snake_int()
    name: SnakeColumn[str] = snake_str()


# A graph with a CYCLE, which a self-referencing column admits perfectly well: 20 -> 21 -> 22 -> 20.
# There is no root and no bottom, so a walk that only stops when a step comes back empty never stops.
_RING = [(20, 22, "a"), (21, 20, "b"), (22, 21, "c")]


@pytest.fixture
def rings() -> Iterator[dict[str, SnakeSession]]:
    """The cyclic graph on the three engines, with a statement timeout where there can be one.

    The timeout is a SAFETY NET, not the subject: if the walk below ever stopped terminating, this
    is what turns a hung suite into a failure. SQLite gets none because it has no server-side
    statement timeout at all — `TimeoutDriver` refuses to wrap it rather than hand back a connection
    that looks capped and is not. That exception is declared here instead of quietly dropping the
    engine.
    """

    def wrap(engine: str, driver: SnakeDriver) -> SnakeDriver:
        if engine == "sqlite":
            return driver
        return TimeoutDriver(driver, DIALECTS[engine], statement_timeout_ms=10_000)

    with three_sessions([Ring], wrap=wrap) as sessions:
        for session in sessions.values():
            session.add_all([Ring(id=i, parent_id=p, name=n) for i, p, n in _RING])
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_distinct_makes_a_cyclic_walk_finish(
    engine: str, rings: dict[str, SnakeSession]
) -> None:
    """THE reason the parameter exists: over a CYCLE, `distinct=True` TERMINATES and answers right.

    The same walk with the default `UNION ALL` does not come back. It is not asserted here and it
    will not be: the only way to prove a hang is to wait for a timeout, and a test that hangs is
    worse than no test. What is asserted is the half that has an answer — that this one ends, and
    that it ends with each row ONCE.

    The `order_by()` is deliberate. It is what makes the limit-as-a-safety-net story fall apart:
    a sort has to consume every row before it can emit one, so no bound on the result can rescue a
    traversal that never ends. Measured against this very server.
    """
    walk = (
        SnakeQuery(Ring)
        .filter(Ring.id == 20)
        .recursive(on=(Ring.parent_id, Ring.id), distinct=True)
        .order_by(Ring.id.asc())
    )

    assert [row.id for row in rings[engine].all(walk)] == [20, 21, 22]
