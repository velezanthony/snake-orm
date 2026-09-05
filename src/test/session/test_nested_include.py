"""Tests of the NESTED include (SnakePrefetch) in the session: ONE query per LEVEL, never N+1.

It is exercised with a FAKE 'scripted' driver that returns rows based on the table in the FROM and
RECORDS every SQL it receives. That is how the number of emitted queries is counted: for
Nation→makers→trucks there must be 3 (root + one level per hop), NOT one per parent. No Postgres:
the session is the only thing with colour, and what is observed here is the slicing per level and
the parent↔children matching done in memory.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.fields import SnakePrefetch
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Maker, Nation


class _ScriptedDriver:
    """Fake driver: it returns rows based on the table in the `FROM` and records every SQL run.

    It does not interpret the WHERE (the `IN` of the select-in): it returns ALL the rows of the
    table and lets the session group them by FK. That is enough to count queries and to check the
    matching done in memory.
    """

    def __init__(self, rows_by_table: dict[str, list[tuple[object, ...]]]) -> None:
        self._rows_by_table = rows_by_table
        self.queries: list[str] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.queries.append(sql)
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
        self.queries.append(sql)
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


# España(1) has TWO makers (SEAT, Cupra); Alemania(2) has one (BMW).
# SEAT(1) has two trucks; BMW(2) has one; Cupra(3) has NONE.
_ROWS: dict[str, list[tuple[object, ...]]] = {
    "nations": [(1, "España"), (2, "Alemania")],
    "makers": [(1, "SEAT", 1), (3, "Cupra", 1), (2, "BMW", 2)],
    "trucks": [(1, "Ibiza", 1), (4, "León", 1), (2, "M3", 2)],
}


def _session() -> tuple[SnakeSession, _ScriptedDriver]:
    """Prepares a session with the scripted driver and the relations already linked."""
    snake_link()
    driver = _ScriptedDriver(_ROWS)
    return SnakeSession(driver, PostgresDialect()), driver


def test_nested_prefetch_emits_one_query_per_level() -> None:
    """Verifies that Nation→makers→trucks emits 3 queries (root + 2 levels), NOT one per parent."""
    session, driver = _session()
    session.all(
        SnakeQuery(Nation).include(SnakePrefetch(Nation.makers).then(Maker.trucks))
    )
    assert len(driver.queries) == 3
    # The header of each query gives away its level: root, then makers, then trucks.
    assert 'FROM "public"."nations"' in driver.queries[0]
    assert 'FROM "public"."makers"' in driver.queries[1]
    assert 'FROM "public"."trucks"' in driver.queries[2]


def test_nested_prefetch_wires_the_object_graph() -> None:
    """Verifies that the values hang correctly: each nation with its makers, each maker with its trucks."""
    session, _driver = _session()
    nations = session.all(
        SnakeQuery(Nation).include(SnakePrefetch(Nation.makers).then(Maker.trucks))
    )
    by_name = {nation.name: nation for nation in nations}
    spain_makers = {maker.name: maker for maker in by_name["España"].makers}
    assert sorted(spain_makers) == ["Cupra", "SEAT"]
    assert sorted(truck.model for truck in spain_makers["SEAT"].trucks) == [
        "Ibiza",
        "León",
    ]
    assert spain_makers["Cupra"].trucks == []  # a child with no grandchildren gets []
    germany_makers = by_name["Alemania"].makers
    assert [maker.name for maker in germany_makers] == ["BMW"]
    assert [truck.model for truck in germany_makers[0].trucks] == ["M3"]


def test_nested_prefetch_mixing_to_one_uses_one_query_per_level() -> None:
    """Verifies that mixing a to-one into the chain (makers→nation) is still one query per level.

    Nation→makers (many)→nation (one): 3 queries (root + makers + nations). The to-one is resolved
    with ONE extra query (select-in over the referenced PK), not with a JOIN nor a query per maker.
    """
    session, driver = _session()
    nations = session.all(
        SnakeQuery(Nation).include(SnakePrefetch(Nation.makers).then(Maker.nation))
    )
    assert len(driver.queries) == 3
    spain = next(nation for nation in nations if nation.name == "España")
    # Every maker of España has ITS nation hooked on (one object, not a list).
    assert {maker.nation.name for maker in spain.makers} == {"España"}


def test_childless_parent_and_parent_without_children_get_empty_lists() -> None:
    """Verifies that a parent with no children gets [] and does not break the chain (Cupra)."""
    session, _driver = _session()
    nations = session.all(
        SnakeQuery(Nation).include(SnakePrefetch(Nation.makers).then(Maker.trucks))
    )
    all_makers = [maker for nation in nations for maker in nation.makers]
    cupra = next(maker for maker in all_makers if maker.name == "Cupra")
    assert cupra.trucks == []
