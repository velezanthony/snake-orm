"""A select-in binds one placeholder per DISTINCT key, not one per parent row.

In a to-one the foreign key lives on the PARENT and it repeats: that is the definition of the
cardinality. 50,000 trucks over 50 makers built a `parent_keys` list of 50,000 entries, so the
emitted `IN (...)` carried 50,000 placeholders and ~150 KB of SQL to say what 50 placeholders say.

Two costs, and the second is the one that changes behaviour rather than just wasting work: it
crosses SQLite's 32,766-placeholder ceiling, so `parents_per_batch` splits the read into TWO
statements where one was enough — because the counting was done over repetitions.

Deduplicating with `dict.fromkeys` and not a `set`: the order of the parents is the order of the
placeholders, and an unordered one would make the emitted SQL differ between runs for no reason.

The `attach` side needs nothing: it already indexes the children by key and looks each parent up in
that map, so it never cared how many times a key was asked for.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from snakeorm.decorators import snake_model
from snakeorm.dialects import SQLiteDialect
from snakeorm.fields import (
    SnakeColumn,
    SnakePrefetch,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession


@snake_model(table="si_depots")
class _Depot(SnakeModel):
    """The far end of the NESTED to-one: few of these, many trucks pointing at each."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="si_makers")
class _Maker(SnakeModel):
    """The root of the chain."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    trucks: SnakeToMany[_Truck] = snake_to_many("maker")


@snake_model(table="si_trucks")
class _Truck(SnakeModel):
    """The middle. Its `depot_id` REPEATS, which is what a to-one means."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    maker_id: SnakeColumn[int] = snake_int()
    depot_id: SnakeColumn[int] = snake_int()
    maker: SnakeToOne[_Maker] = snake_to_one(maker_id)
    depot: SnakeToOne[_Depot] = snake_to_one(depot_id)


snake_link()

_PARENTS = 40
_DISTINCT = 4


class _Recorder:
    """Answers each read of the chain: 1 maker, `_PARENTS` trucks over `_DISTINCT` depots."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Sequence[object]]] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        if "si_makers" in sql:
            return [(1, "maker")]
        if "si_trucks" in sql:
            # id, maker_id, depot_id — the depot repeats, which is the whole point.
            return [(n, 1, n % _DISTINCT) for n in range(_PARENTS)]
        return [(n, f"depot-{n}") for n in range(_DISTINCT)]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


def _run() -> tuple[_Recorder, list[_Maker]]:
    """One maker, its trucks prefetched, and each truck's depot: a to-many then a NESTED to-one.

    The nesting is what reaches `plan_to_one_level`. A first-level to-one include is a LEFT JOIN and
    never binds keys at all, so a flat query could not see this defect.
    """
    driver = _Recorder()
    session = SnakeSession(driver, SQLiteDialect())
    makers = session.all(
        SnakeQuery(_Maker).include(SnakePrefetch(_Maker.trucks).then(_Truck.depot))
    )
    return driver, makers


def _depot_read(driver: _Recorder) -> tuple[str, Sequence[object]]:
    """The statement that fetched the DEPOTS: the nested to-one select-in."""
    return next(call for call in driver.calls if "si_depots" in call[0])


def test_the_select_in_binds_one_key_per_distinct_value() -> None:
    """40 trucks over 4 depots bind 4 placeholders, not 40.

    The assertion is on the PARAMETERS and not on the rows, because the rows were always right: the
    children came back correct either way, and that is exactly why nobody noticed the statement was
    ten times bigger than the question it was asking.
    """
    driver, _ = _run()

    _sql, params = _depot_read(driver)

    assert len(params) == _DISTINCT, (
        f"{len(params)} placeholders for {_DISTINCT} distinct depots: the FK was counted once per "
        f"parent row instead of once per value"
    )
    assert sorted(params) == list(range(_DISTINCT))  # type: ignore[type-var]


def test_the_children_are_still_attached_to_every_parent() -> None:
    """The floor: deduplicating the KEYS must not deduplicate the PARENTS.

    All 40 trucks still get their depot, including the 36 whose key had already been asked for.
    Without this, "send fewer keys" could be implemented as "load fewer parents" and the test above
    would applaud.
    """
    _driver, makers = _run()
    trucks = list(makers[0].trucks)

    assert len(trucks) == _PARENTS
    assert [truck.depot.id for truck in trucks] == [
        n % _DISTINCT for n in range(_PARENTS)
    ]
