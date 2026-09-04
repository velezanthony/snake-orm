"""A COMPOSITE foreign key comes back with its pairs once each, in key order, on the three.

PostgreSQL returned each pair TWICE. The query joined `pg_attribute` for the local columns and
again for the remote ones, both with `= ANY(...)`, which is a CARTESIAN PRODUCT: a two-column key
matched two local rows by two remote ones and aggregated FOUR. A one-column key is 1x1, so every
single-column FK in the suite looked perfect and the composite one nobody introspected was wrong.

The ordering was the same bug's other half: `ORDER BY attnum` is the order the columns were DECLARED
in the table, not their position in the KEY. A composite key whose columns are not in declaration
order would have paired the wrong ones together — a mirror pointing at the wrong column, which
compiles and returns rows.

Found by running the scaffold against a real database and reading the line it emitted:
`snake_to_one(province_region, province_region, province_code, province_code)`. No unit test could
have caught it: the doubling is in what the SERVER answers, not in what the code does with it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm.drivers.base import SnakeDriver
from snakeorm.introspection import (
    MySQLIntrospector,
    PostgresIntrospector,
    SQLiteIntrospector,
)
from snakeorm.introspection.base import SnakeIntrospector
from test.scenarios.engines import three_drivers

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]

_PARENT = (
    "CREATE TABLE cfk_parent ("
    "  region VARCHAR(8) NOT NULL, code VARCHAR(8) NOT NULL,"
    "  PRIMARY KEY (region, code))"
)
# The FK's columns are declared in the OPPOSITE order to the key, which is what tells an ordering
# bug apart from a working one: `ORDER BY attnum` would pair `p_code` with `region`.
_CHILD = (
    "CREATE TABLE cfk_child ("
    "  id INT NOT NULL PRIMARY KEY,"
    "  p_code VARCHAR(8) NOT NULL, p_region VARCHAR(8) NOT NULL,"
    "  FOREIGN KEY (p_region, p_code) REFERENCES cfk_parent(region, code))"
)


@pytest.fixture
def drivers() -> Iterator[dict[str, SnakeDriver]]:
    """The three engines with one composite foreign key in them."""
    with three_drivers([]) as engines:
        for driver in engines.values():
            for statement in (
                "DROP TABLE IF EXISTS cfk_child",
                "DROP TABLE IF EXISTS cfk_parent",
            ):
                driver.execute(statement, ())
            driver.execute(_PARENT, ())
            driver.execute(_CHILD, ())
            driver.commit()
        yield engines
        for driver in engines.values():
            for statement in (
                "DROP TABLE IF EXISTS cfk_child",
                "DROP TABLE IF EXISTS cfk_parent",
            ):
                driver.execute(statement, ())
            driver.commit()


def _introspector(engine: str, driver: SnakeDriver) -> SnakeIntrospector:
    """The engine's own reader. There is no common one and there should not be."""
    if engine == "postgres":
        return PostgresIntrospector(driver)
    if engine == "mysql":
        return MySQLIntrospector(driver)
    return SQLiteIntrospector(driver)


@pytest.mark.parametrize("engine", _ENGINES)
def test_each_pair_comes_back_once_and_in_key_order(
    engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """Two pairs, not four, and `p_region` with `region` rather than with `code`."""
    tables = _introspector(engine, drivers[engine]).tables()
    child = next(table for table in tables if table.name == "cfk_child")

    assert len(child.relationships) == 1, "one key, one relationship"
    pairs = child.relationships[0].foreign_key.pairs

    assert pairs == (("p_region", "region"), ("p_code", "code"))
