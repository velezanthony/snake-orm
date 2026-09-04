"""Tests of the SQL a FILTERED prefetch emits: the select-in of that level carries `AND (...)`.

It is exercised with a FAKE driver that returns rows based on the table in the FROM and RECORDS
every `(sql, params)`. That is how it is checked that the prefetch filter is ADDED with AND to the
`WHERE fk IN (...)` of that level, with the params in order and numbered continuously, and that it
does NOT add queries: it is still ONE query per level. The grouping semantics (a parent with no
matching children → []) are tested in the integration suite.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.fields import SnakePrefetch
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Maker, Nation, Truck


class _CapturingDriver:
    """Fake driver: returns rows by the FROM table and keeps every `(sql, params)` it ran."""

    def __init__(self, rows_by_table: dict[str, list[tuple[object, ...]]]) -> None:
        self._rows_by_table = rows_by_table
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, tuple(params)))
        for name, rows in self._rows_by_table.items():
            if f'"public"."{name}"' in sql:
                return rows
        return []

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:  # pragma: no cover
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:  # pragma: no cover
        ...

    def rollback(self) -> None:  # pragma: no cover
        ...

    def savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def release_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def rollback_to_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover
        ...


# España(1) and Alemania(2); the makers and trucks of each (the driver does not read the WHERE).
_ROWS: dict[str, list[tuple[object, ...]]] = {
    "nations": [(1, "España"), (2, "Alemania")],
    "makers": [(1, "SEAT", 1), (2, "BMW", 2)],
    "trucks": [(1, "Ibiza", 1), (2, "M3", 2)],
}


def _session() -> tuple[SnakeSession, _CapturingDriver]:
    """Prepares a session with the SQL-capturing driver and the relations already linked."""
    snake_link()
    driver = _CapturingDriver(_ROWS)
    return SnakeSession(driver, PostgresDialect()), driver


def _query_for(driver: _CapturingDriver, table: str) -> tuple[str, tuple[object, ...]]:
    """Recovers the `(sql, params)` of the query whose FROM is the given table."""
    for sql, params in driver.calls:
        if f'"public"."{table}"' in sql:
            return sql, params
    raise AssertionError(f"no query was emitted over '{table}'")


def test_filtered_level_adds_the_condition_with_and() -> None:
    """The filtered level select-in emits `WHERE fk IN (...) AND (<filter>)`, params in order."""
    session, driver = _session()
    session.all(
        SnakeQuery(Nation).include(
            SnakePrefetch(Nation.makers).filter(Maker.name == "SEAT")
        )
    )
    sql, params = _query_for(driver, "makers")
    assert " AND " in sql  # the filter is added with AND to the IN of the select-in
    assert '"nation_id" IN' in sql  # the select-in over the FK is still there
    assert '"name" =' in sql  # the filter condition, unqualified (single-table)
    # Params: first the keys of the parents (1, 2), then the value of the filter ("SEAT").
    assert params == (1, 2, "SEAT")


def test_filter_does_not_add_queries_still_one_per_level() -> None:
    """The filter does NOT add queries: root + one level = 2 queries (not one per parent)."""
    session, driver = _session()
    session.all(
        SnakeQuery(Nation).include(
            SnakePrefetch(Nation.makers).filter(Maker.name == "SEAT")
        )
    )
    assert len(driver.calls) == 2  # nations (root) + makers (the filtered level)


def test_per_level_filters_narrow_each_level_and_keep_one_query_per_level() -> None:
    """A filter per level in a two-level chain: each select-in carries ITS AND; 3 queries in total."""
    session, driver = _session()
    session.all(
        SnakeQuery(Nation).include(
            SnakePrefetch(Nation.makers)
            .filter(Maker.name == "SEAT")
            .then(Maker.trucks)
            .filter(Truck.id > 1)
        )
    )
    assert len(driver.calls) == 3  # root + makers + trucks, one per level
    makers_sql, makers_params = _query_for(driver, "makers")
    trucks_sql, trucks_params = _query_for(driver, "trucks")
    assert " AND " in makers_sql and '"name" =' in makers_sql
    assert makers_params == (1, 2, "SEAT")
    assert " AND " in trucks_sql and '"id" >' in trucks_sql
    # The frontier of the second level is the makers returned (ids 1 and 2), then the filter value.
    assert trucks_params == (1, 2, 1)


def test_unfiltered_level_has_no_extra_condition() -> None:
    """A level WITHOUT a filter emits only the `WHERE fk IN (...)` (with no AND added)."""
    session, driver = _session()
    session.all(SnakeQuery(Nation).include(SnakePrefetch(Nation.makers)))
    sql, params = _query_for(driver, "makers")
    assert " AND " not in sql
    assert params == (1, 2)
