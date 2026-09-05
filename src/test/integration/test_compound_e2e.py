"""Set operations EXECUTED against Postgres.

Emission proves that the string says `UNION`. Only execution proves that `UNION` and
`UNION ALL` are not synonyms, that `EXCEPT` subtracts in the direction one believes, and —most
important of all— that the rows of the set come back turned into INSTANCES of the model.

That last point is the one that validates the design: the compound runs down the same path as a
normal query, without any special branch in the session.

Skips gracefully if there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="set_orders")
class Order(SnakeModel):
    """Orders with status and amount, to cross two criteria that OVERLAP."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    status: SnakeColumn[str] = snake_str()
    amount: SnakeColumn[int] = snake_int()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session populated so that the two criteria SHARE one row (number 2)."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS set_orders CASCADE", ())
    driver.execute(emit_create_table(snake_table(Order), PostgresDialect()), ())
    driver.commit()
    built = SnakeSession(driver, PostgresDialect())
    built.add_all(
        [
            Order(id=1, status="open", amount=100),  # only open
            Order(
                id=2, status="open", amount=900
            ),  # open AND large: the overlapping row
            Order(id=3, status="closed", amount=900),  # only large
        ]
    )
    built.commit()
    try:
        yield built
    finally:
        driver.execute("DROP TABLE IF EXISTS set_orders CASCADE", ())
        driver.commit()
        driver.close()


def _open() -> SnakeQuery[Order]:
    """The open ones: orders 1 and 2."""
    return SnakeQuery(Order).filter(Order.status == "open")


def _large() -> SnakeQuery[Order]:
    """The high-amount ones: orders 2 and 3."""
    return SnakeQuery(Order).filter(Order.amount > 500)


def test_the_union_returns_model_instances(session: SnakeSession) -> None:
    """WHAT validates the design: the set comes back as INSTANCES, down the usual path.

    The session has no special branch for compounds: `SnakeCompound` fulfils the same contract
    as a query (`model`, `has_includes`, `to_sql`) and that is why it runs exactly the same.
    """
    rows = session.all(_open().union(_large()).order_by(Order.id.asc()))

    assert [type(row).__name__ for row in rows] == ["Order"] * 3
    assert [row.id for row in rows] == [1, 2, 3]
    assert rows[1].status == "open", "the columns are mapped, they do not come back raw"


def test_union_deduplicates_and_union_all_does_not(session: SnakeSession) -> None:
    """THE proof that emission cannot give: order 2 satisfies BOTH criteria.

    `UNION` returns it ONCE; `UNION ALL` returns it TWICE. That the names look so alike and the
    result does not is exactly why this had to be executed for real.
    """
    joined = session.all(_open().union(_large()).order_by(Order.id.asc()))
    every = session.all(_open().union_all(_large()).order_by(Order.id.asc()))

    assert [row.id for row in joined] == [1, 2, 3]
    assert [row.id for row in every] == [1, 2, 2, 3], (
        "the 2 comes out twice: it satisfies both"
    )


def test_intersect_returns_only_the_overlap(session: SnakeSession) -> None:
    """`INTERSECT`: only order 2, which is the only one in both queries."""
    rows = session.all(_open().intersect(_large()))

    assert [row.id for row in rows] == [2]


def test_except_subtracts_in_the_declared_direction(session: SnakeSession) -> None:
    """`EXCEPT` is NOT symmetric, and checking it both ways round is the point of this test."""
    open_not_large = session.all(_open().except_(_large()))
    large_not_open = session.all(_large().except_(_open()))

    assert [row.id for row in open_not_large] == [1]
    assert [row.id for row in large_not_open] == [3]


def test_order_and_limit_apply_to_the_whole_set(session: SnakeSession) -> None:
    """Verifies that ordering and limiting belong to the SET, not to one of its branches.

    And on the way it proves the unqualified `ORDER BY` is right against the engine: with the
    table alias in front, Postgres would reject the whole query.
    """
    rows = session.all(_open().union(_large()).order_by(Order.id.desc()).limit(2))

    assert [row.id for row in rows] == [3, 2]
