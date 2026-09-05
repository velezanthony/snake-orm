"""The everyday query, EXECUTED on the three engines: filter, order, distinct, group and aggregate.

These five are the ones every other feature stands on, and the tests the index pointed at assert
`to_sql` — the emitted STRING. That is a real check and not the same claim: a string all three
dialects agree on still says nothing about what any of them RETURNS, and the difference is where
this ORM's bugs have lived. `ORDER BY` losing a relationship hop produced valid SQL on all three,
which is precisely why comparing engines could not find it.

One file for the five because they share a table and a seeding, and because what is worth checking
about them is mostly how they COMBINE — a `DISTINCT` over an ordered projection, a `HAVING` over a
grouped aggregate — which is where the engines stop agreeing.
"""

from __future__ import annotations

from collections.abc import Iterator

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
from snakeorm import SnakeRow, snake_row
from snakeorm.core.exceptions import SnakeColumnNotLoaded
from snakeorm.expressions import avg, count, max_, min_, string_agg, sum_
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


_TABLE = "qb_sales"


@snake_model(table=_TABLE)
class Sale(SnakeModel):
    """Sales with repeated regions and a NULL, so grouping and distinct have something to say."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    region: SnakeColumn[str] = snake_str()
    seller: SnakeColumn[str] = snake_str()
    amount: SnakeColumn[int] = snake_int()


_ROWS = [
    (1, "north", "ada", 100),
    (2, "north", "ada", 300),
    (3, "north", "grace", 200),
    (4, "south", "grace", 50),
    (5, "south", "linus", 50),
]


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the same five sales."""
    with three_sessions([Sale]) as sessions:
        for session in sessions.values():
            session.add_all(
                [Sale(id=i, region=r, seller=s, amount=a) for i, r, s, a in _ROWS]
            )
            session.commit()
        yield sessions


_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_filter_brings_back_the_rows_that_match(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A filter over two conditions returns exactly the rows that satisfy both."""
    session = engines[engine]

    rows = session.all(
        SnakeQuery(Sale)
        .filter(Sale.region == "north", Sale.amount >= 200)
        .order_by(Sale.id.asc())
    )

    assert [row.id for row in rows] == [2, 3]


@pytest.mark.parametrize("engine", _ENGINES)
def test_order_limit_and_offset_agree_on_the_window(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Descending order plus a window: the same three rows in the same order, everywhere.

    `offset` after `order_by` and not before, because an offset over an unordered set is a different
    question on each engine — and one that happens to agree on small tables, which is worse.
    """
    session = engines[engine]

    rows = session.all(
        SnakeQuery(Sale).order_by(Sale.amount.desc(), Sale.id.asc()).limit(3).offset(1)
    )

    assert [(row.id, row.amount) for row in rows] == [(3, 200), (1, 100), (4, 50)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_distinct_collapses_the_repeated_values(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`DISTINCT` over a projection leaves one row per value, ordered the same on the three."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Sale).distinct().order_by(Sale.region.asc()), Sale.region
    )

    assert [row[0] for row in rows] == ["north", "south"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_group_by_with_having_keeps_only_the_groups_that_qualify(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Grouped totals, then a `HAVING` over the aggregate — not over a column."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Sale)
        .group_by(Sale.region)
        .having(sum_(Sale.amount) > 200)
        .order_by(Sale.region.asc()),
        Sale.region,
        sum_(Sale.amount),
    )

    # The aggregates are typed `int | None` because a SUM over no rows is NULL, and the checker is
    # right to insist: asserting the absence first is what makes the number below meaningful.
    assert all(total is not None for _region, total in rows)
    assert [(region, total) for region, total in rows] == [("north", 600)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_aggregates_answer_the_same_numbers(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The five aggregates over the whole table come back as one row.

    `avg` is asked separately and compared loosely: the engines do not agree on its TYPE — some
    answer a decimal, others a float — and pinning the type here would be testing the driver's
    coercion rather than the aggregate. What has to agree is the number.
    """
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Sale),
        count(Sale.id),
        sum_(Sale.amount),
        min_(Sale.amount),
        max_(Sale.amount),
    )
    how_many, total, smallest, largest = rows[0]

    assert None not in (total, smallest, largest)
    assert (how_many, total, smallest, largest) == (5, 700, 50, 300)

    mean = session.select(SnakeQuery(Sale), avg(Sale.amount))[0][0]
    assert mean is not None
    assert float(mean) == pytest.approx(140.0)


# -- Projection: what comes back in the row, and what deliberately does not -----------------------


@pytest.mark.parametrize("engine", _ENGINES)
def test_only_brings_the_asked_columns_and_locks_the_rest(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`only()` narrows the SELECT, and touching what was left out RAISES instead of lying.

    The second half is the one that matters. A projection that returned `None` for the missing
    column would be indistinguishable from a column that IS null, which is how a partial read turns
    into wrong data downstream.
    """
    session = engines[engine]

    rows = session.all(SnakeQuery(Sale).only(Sale.region).order_by(Sale.id.asc()))

    assert [row.region for row in rows] == ["north", "north", "north", "south", "south"]
    with pytest.raises(SnakeColumnNotLoaded, match="seller"):
        _ = rows[0].seller


@pytest.mark.parametrize("engine", _ENGINES)
def test_defer_leaves_out_the_named_column_and_keeps_the_rest(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`defer()` is the same idea from the other end: everything EXCEPT this one."""
    session = engines[engine]

    rows = session.all(SnakeQuery(Sale).defer(Sale.seller).order_by(Sale.id.asc()))

    assert [row.amount for row in rows] == [100, 300, 200, 50, 50]
    with pytest.raises(SnakeColumnNotLoaded, match="seller"):
        _ = rows[0].seller


@pytest.mark.parametrize("engine", _ENGINES)
def test_string_agg_joins_a_group_in_a_stated_order(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """One name per engine, one behaviour: `string_agg`, `GROUP_CONCAT` and `group_concat`.

    The `order_by` inside the aggregate is not cosmetic — without it the order within a group is the
    engine's business and the three would disagree for a reason that has nothing to do with the ORM.
    SQLite only grew it in 3.44, which is why the dialect measured it instead of assuming.
    """
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Sale).group_by(Sale.region).order_by(Sale.region.asc()),
        Sale.region,
        string_agg(Sale.seller, ",", order_by=[Sale.seller.asc()]),
    )

    assert [(region, str(joined)) for region, joined in rows] == [
        ("north", "ada,ada,grace"),
        ("south", "grace,linus"),
    ]


# -- `raw()`: the escape hatch, and what it still guarantees ---------------------------------------


@snake_row
class RegionAmount(SnakeRow):
    """The DECLARED shape of a raw read: scalars only, hydrated positionally."""

    region: str
    amount: int


@pytest.mark.parametrize("engine", _ENGINES)
def test_raw_hydrates_into_the_declared_shape_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The hatch is typed on the way out, and the values arrive as the declared types.

    The SQL below is deliberately the plainest thing the three agree on, because what is under test
    is the HYDRATION, not anyone's grammar. Reading `amount` as an `int` and not as whatever the
    driver felt like is the whole guarantee `raw()` still offers after giving up on the builder.
    """
    session = engines[engine]

    rows = session.raw(
        f"SELECT region, amount FROM {_TABLE} WHERE id = 1",
        into=RegionAmount,
    )

    assert len(rows) == 1
    assert rows[0].region == "north"
    assert rows[0].amount == 100
    assert isinstance(rows[0].amount, int)


@pytest.mark.parametrize("engine", _ENGINES)
def test_raw_takes_its_values_as_parameters(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A placeholder is the engine's own, so the hatch does not become a hole.

    `dialect.placeholder(1)` is asked for rather than written: `$1`, `%s` and `?` are three
    different strings, and hard-coding any of them is how an escape hatch stops being portable.
    """
    session = engines[engine]
    marker = session.dialect.placeholder(1)

    rows = session.raw(
        f"SELECT region, amount FROM {_TABLE} WHERE region = {marker}",
        ["south"],
        into=RegionAmount,
    )

    assert sorted(row.amount for row in rows) == [50, 50]
