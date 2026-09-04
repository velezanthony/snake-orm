"""Relationships, EXECUTED on the three engines: joins, loading, deep navigation and existence.

The five features here are the thesis of the project — a typed path across models that becomes SQL —
and the tests the index pointed at assert the emitted string. That is the weaker half twice over:
a join that names the wrong column still parses, and a `.any()` whose correlation is wrong still
returns rows. Both are valid SQL on all three engines, so comparing engines cannot see them either;
only the rows can.

The chain is `Truck → Maker → Nation`, reused from `test/scenarios/deep_domain.py` rather than
declared again. The data is seeded so that every claim has a row that would break it if the ORM got
it wrong: a nation with no makers, a maker with no trucks, and two makers sharing a nation.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import SnakeQuery, SnakeResult, SnakeSession, snake_result
from snakeorm.linker import snake_link
from test.scenarios.deep_domain import Maker, Nation, Truck
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_NATIONS = [(1, "Sweden"), (2, "Japan"), (3, "Nowhere")]
_MAKERS = [(1, "Scania", 1), (2, "Volvo", 1), (3, "Hino", 2), (4, "Idle", 3)]
_TRUCKS = [(1, "R500", 1), (2, "S730", 1), (3, "FH16", 2), (4, "Profia", 3)]


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the same chain. `Nowhere` has a maker with no trucks, on purpose."""
    # The relations are resolved once, here: a path across models is metadata the linker builds,
    # and without it `Truck.maker` is a declaration nobody has connected to anything.
    snake_link()
    with three_sessions([Nation, Maker, Truck]) as sessions:
        for session in sessions.values():
            session.add_all([Nation(id=i, name=n) for i, n in _NATIONS])
            session.commit()
            session.add_all([Maker(id=i, name=n, nation_id=c) for i, n, c in _MAKERS])
            session.commit()
            session.add_all([Truck(id=i, model=m, maker_id=k) for i, m, k in _TRUCKS])
            session.commit()
        yield sessions


_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_deep_path_filters_across_two_hops(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`Truck.maker.nation.name` reaches two tables away and brings back only the matching trucks.

    The claim of the whole project in one line: the path is typed, and what it becomes is a JOIN
    the caller never wrote. A path that lost a hop would still be valid SQL — it would filter on a
    column of the wrong table — so what proves it is which rows come back.
    """
    session = engines[engine]

    rows = session.all(
        SnakeQuery(Truck)
        .filter(Truck.maker.nation.name == "Sweden")
        .order_by(Truck.id.asc())
    )

    assert [row.model for row in rows] == ["R500", "S730", "FH16"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_an_explicit_join_multiplies_the_parent_by_its_children(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`join()` takes a COLLECTION into the projection, so the parent repeats once per child.

    That multiplication is the whole reason it exists and the reason `all()` refuses the result:
    hydrating a model from multiplied rows would hand back the same maker twice pretending to be two.
    A maker with two trucks is what makes it visible. The child's columns come off `joined.right`,
    which carries the JOIN's alias — naming `Truck.model` directly would be a second, unaliased
    reference to the same table.
    """
    session = engines[engine]
    joined = SnakeQuery(Maker).join(Maker.trucks)

    rows = session.select(
        joined.order_by(Maker.id.asc(), joined.right.id.asc()),
        Maker.name,
        joined.right.model,
    )

    assert rows == [
        ("Scania", "R500"),
        ("Scania", "S730"),
        ("Volvo", "FH16"),
        ("Hino", "Profia"),
    ]


@pytest.mark.parametrize("engine", _ENGINES)
def test_include_loads_the_related_rows_without_another_query_per_row(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`include()` fills the to-one and the to-many, and the collection keeps its rows."""
    session = engines[engine]

    trucks = session.all(
        SnakeQuery(Truck).include(Truck.maker).order_by(Truck.id.asc())
    )
    assert [truck.maker.name for truck in trucks] == [
        "Scania",
        "Scania",
        "Volvo",
        "Hino",
    ]

    makers = session.all(
        SnakeQuery(Maker).include(Maker.trucks).order_by(Maker.id.asc())
    )
    assert [len(maker.trucks) for maker in makers] == [2, 1, 1, 0]


@pytest.mark.parametrize("engine", _ENGINES)
def test_any_answers_the_parents_that_have_a_child(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`.any()` is a correlated EXISTS: the maker with no trucks must not come back.

    `Idle` exists for this test alone. Without a childless row the query returns everything and a
    broken correlation — one that ignores the parent — looks exactly like a working one.
    """
    session = engines[engine]

    rows = session.all(
        SnakeQuery(Maker).filter(Maker.trucks.any()).order_by(Maker.id.asc())
    )

    assert [row.name for row in rows] == ["Scania", "Volvo", "Hino"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_correlated_scalar_subquery_counts_per_parent(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A scalar subquery answers ONE number per parent row, and a different one for each."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Maker).order_by(Maker.id.asc()),
        Maker.name,
        Maker.trucks.count(),
    )

    assert [(name, int(how_many)) for name, how_many in rows] == [
        ("Scania", 2),
        ("Volvo", 1),
        ("Hino", 1),
        ("Idle", 0),
    ]


# -- `annotate()`: the base row plus correlated counts, typed --------------------------------------


@snake_result
class NationStats(SnakeResult[Nation]):
    """Typed container: the nation plus how many makers it has."""

    nation: Nation
    maker_count: int


@pytest.mark.parametrize("engine", _ENGINES)
def test_annotate_carries_the_row_and_its_count_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`annotate()` had only ever run against a FAKE driver: the SQL was checked, never an answer.

    `Nowhere` is what makes this an assertion rather than a smoke test. Its maker has no trucks, so
    a correlated count that silently became an INNER JOIN would drop the row entirely — and a list
    that is one shorter looks like data, not like a bug.
    """
    session = engines[engine]

    stats = session.annotate(
        SnakeQuery(Nation).order_by(Nation.id.asc()),
        NationStats,
        maker_count=Nation.makers.count(),
    )

    assert [(row.nation.name, int(row.maker_count)) for row in stats] == [
        ("Sweden", 2),
        ("Japan", 1),
        ("Nowhere", 1),
    ]
