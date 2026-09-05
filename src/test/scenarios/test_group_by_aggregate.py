"""GROUP BY + aggregates against a real Postgres: the VALUES are checked, not just that it runs.

It creates its OWN schema with unique table names (copying the pattern of `test_any_cardinality`).
It seeds a catalog with categories of different sizes and checks that
`SELECT category, COUNT(*), AVG(price) ... GROUP BY category HAVING COUNT(*) > 1` returns
exactly the categories with more than one product, with their counts and averages correct.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.expressions.functions import avg, count
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.linker.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="wares")
class Ware(SnakeModel):
    """Catalog product with a category and a price, to group by category."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    category: SnakeColumn[str] = snake_str()
    price: SnakeColumn[int] = snake_int()


_DDL = (
    "DROP TABLE IF EXISTS wares CASCADE",
    "CREATE TABLE wares ("
    " id INTEGER PRIMARY KEY, category TEXT NOT NULL, price INTEGER NOT NULL)",
)

# Electronics: 3 products (average 200); Books: 2 (average 20); Toys: 1 (average 50).
_SEED = (
    "INSERT INTO wares VALUES"
    " (1, 'Electronics', 100), (2, 'Electronics', 200), (3, 'Electronics', 300),"
    " (4, 'Books', 10), (5, 'Books', 30),"
    " (6, 'Toys', 50)",
)


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates the schema, seeds it and returns a session against the real Postgres."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    snake_link()
    driver = PsycopgDriver(connection)
    for statement in (*_DDL, *_SEED):
        driver.execute(statement, ())
    driver.commit()
    return SnakeSession(driver, PostgresDialect())


def test_group_by_count_avg_having(session: SnakeSession) -> None:
    """GROUP BY category with COUNT/AVG and HAVING COUNT(*) > 1: only Electronics and Books.

    Toys has a single product, so the HAVING excludes it. The real counts and averages are
    checked, not just that the query runs.
    """
    query = SnakeQuery(Ware).group_by(Ware.category).having(count() > 1)
    rows = session.select(query, Ware.category, count(), avg(Ware.price))
    by_category = {category: (total, average) for category, total, average in rows}

    assert set(by_category) == {"Electronics", "Books"}
    assert by_category["Electronics"][0] == 3
    assert by_category["Books"][0] == 2

    # `avg()` is `float | None` because AVG of zero rows is NULL. Here it CANNOT be: a group from
    # a GROUP BY comes out of real rows, so it is never empty. The invariant is ASSERTED instead of
    # assumed — which is exactly what the `| None` forces you to do, and why it is well placed.
    electronics_avg = by_category["Electronics"][1]
    books_avg = by_category["Books"][1]
    assert electronics_avg is not None
    assert books_avg is not None
    assert Decimal(electronics_avg) == Decimal(200)
    assert Decimal(books_avg) == Decimal(20)


def test_group_by_without_having_includes_all_categories(session: SnakeSession) -> None:
    """With no HAVING, the GROUP BY returns the THREE categories with their count."""
    query = SnakeQuery(Ware).group_by(Ware.category)
    rows = session.select(query, Ware.category, count())
    counts = {category: total for category, total in rows}
    assert counts == {"Electronics": 3, "Books": 2, "Toys": 1}
