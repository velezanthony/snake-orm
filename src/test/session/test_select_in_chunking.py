"""The select-in of a prefetch splits by the engine's placeholder ceiling.

`add_all` has chunked by `max_bind_params` since it existed; the READ side never did. A to-many
`include()` over more parents than the engine accepts placeholders emitted a single `IN (...)` with
one placeholder per parent, and the driver rejected the statement — 65,535 on Postgres and MySQL,
32,766 on SQLite. Nothing degraded gently: it worked up to the ceiling and blew up past it.

The asymmetry is the whole bug. There was no decision behind it, which is why the fix is to copy the
loop that was already there rather than invent one.

It is exercised with a dialect whose ceiling is FOUR, not with sixty-five thousand parents. Two
reasons, and the second is the one that matters: a test with real volume is slow and flaky, and it
would be pinning the NUMBER instead of the property. What has to hold is "it splits by whatever the
engine declares, and every parent still gets its children" — and that is exactly as true with four
as with 65,535, only visible in milliseconds.

A composite FK costs one placeholder PER COLUMN, so the batch is measured in placeholders and not in
parents. And the prefetch filter binds its own, which come out of the same budget: counting them is
worth an extra emission per level, because the alternative is a fixed margin, and a fixed margin is
a guess that an `in_([...5000 ids])` in the filter walks straight through.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Nation

_PARENTS = 10
_CEILING = 4


class _CappedDialect(PostgresDialect):
    """Postgres with a ceiling of four placeholders. Everything else is the real dialect."""

    limits = dataclasses.replace(PostgresDialect.limits, bind_params=_CEILING)


class _CountingDriver:
    """Fake driver: answers by the FROM table and counts the statements that reach it."""

    def __init__(self, rows_by_table: dict[str, list[tuple[object, ...]]]) -> None:
        self._rows_by_table = rows_by_table
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, tuple(params)))
        for name, rows in self._rows_by_table.items():
            if f'"public"."{name}"' in sql:
                return [row for row in rows if not params or row[2] in params]
        return []

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: no engine behind it to stream from, so it yields what `fetch_all` returns."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:  # pragma: no cover
        return 0

    @property
    def last_insert_id(self) -> int:  # pragma: no cover
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


def _session() -> tuple[SnakeSession, _CountingDriver]:
    snake_link()
    driver = _CountingDriver(
        {
            "nations": [(index, f"N{index}") for index in range(1, _PARENTS + 1)],
            "makers": [(index, f"M{index}", index) for index in range(1, _PARENTS + 1)],
        }
    )
    return SnakeSession(driver, _CappedDialect()), driver


def test_the_select_in_splits_by_the_declared_ceiling() -> None:
    """With more parents than placeholders, the select-in goes out in several statements."""
    session, driver = _session()

    session.all(SnakeQuery(Nation).include(Nation.makers))

    over_makers = [call for call in driver.calls if '"public"."makers"' in call[0]]
    assert len(over_makers) == 3, (
        f"{_PARENTS} parents with a ceiling of {_CEILING} need 3 statements, "
        f"{len(over_makers)} were emitted"
    )


def test_no_statement_overshoots_the_ceiling() -> None:
    """This is the property that matters: not one statement binds more than the engine accepts."""
    session, driver = _session()

    session.all(SnakeQuery(Nation).include(Nation.makers))

    overshooting = [
        (sql[:60], len(params))
        for sql, params in driver.calls
        if len(params) > _CEILING
    ]
    assert overshooting == [], (
        f"statements over the ceiling of {_CEILING} placeholders: {overshooting}"
    )


def test_every_parent_still_gets_its_children() -> None:
    """Splitting must not lose a parent: each one belongs to exactly one batch and gets its list."""
    session, _ = _session()

    nations = session.all(SnakeQuery(Nation).include(Nation.makers))

    loaded = {nation.id: [maker.id for maker in nation.makers] for nation in nations}
    assert loaded == {index: [index] for index in range(1, _PARENTS + 1)}
