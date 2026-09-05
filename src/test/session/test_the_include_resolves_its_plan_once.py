"""The include path resolves its hydration plan per SEGMENT, not per segment per ROW.

`_instantiate_with_includes` called `_instantiate(...)` and `_pk_is_null(...)` inside the row loop,
and both of those go through `mapper._entry` — `dispatch_for`, `plan_for` and `pk_positions`, three
lookups per segment per row.

The flat path had already solved this: `_instantiate_all` hoists the plan out of the loop, and
`mapper` promises it in writing — "Whoever maps N rows resolves the plan once". The include was the
one caller that did not keep the promise.

WHERE THE LINE IS, and it is worth writing down because getting it wrong would be worse than the
bug: `mapper` invalidates its cache by the table's REFERENCE, so hoisting out of the ROW loop is
safe and hoisting out of the QUERY would be a second cache with its own rule — which is exactly what
`_entry`'s docstring forbids. The plan is resolved once per call, not once per process.

Counting the lookups rather than timing them: a microsecond assertion is a flake generator, and the
count is the actual claim.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.decorators import snake_model
from snakeorm.dialects import SQLiteDialect
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_str, snake_to_one
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession, mapper


@snake_model(table="ip_brands")
class _Brand(SnakeModel):
    """The far end of the include."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="ip_cars")
class _Car(SnakeModel):
    """The root."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    brand_id: SnakeColumn[int] = snake_int()
    brand: SnakeToOne[_Brand] = snake_to_one(brand_id)


snake_link()

_ROWS = 50


class _Wide:
    """Answers the joined read with `_ROWS` wide rows (car columns + brand columns)."""

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return [(n, 1, 1, "brand") for n in range(_ROWS)]

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


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts every entry into `mapper._entry`, which is where a plan gets resolved."""
    calls = [0]
    original = mapper._entry

    def spy(model: type, table: object, owner: type) -> object:
        calls[0] += 1
        return original(model, table, owner)  # type: ignore[arg-type]

    monkeypatch.setattr(mapper, "_entry", spy)
    return calls


def test_the_include_resolves_its_plan_once_per_segment(counted: list[int]) -> None:
    """Two segments over 50 rows cost a handful of lookups, not 300.

    Before: `dispatch_for`, `plan_for` and `pk_positions` per segment per row — 3 x 2 x 50. The
    ceiling here is loose on purpose; what distinguishes the two implementations is whether the
    number grows with the ROWS.
    """
    session = SnakeSession(_Wide(), SQLiteDialect())

    cars = session.all(SnakeQuery(_Car).include(_Car.brand))

    assert len(cars) == _ROWS
    assert counted[0] <= 12, (
        f"{counted[0]} plan lookups for {_ROWS} rows: the include still resolves inside the row loop"
    )


def test_the_rows_are_still_hydrated_correctly(counted: list[int]) -> None:
    """The floor: hoisting must not change what comes out.

    Without this, "resolve the plan once" could be implemented as "reuse the first row's objects"
    and the count assertion above would be delighted.
    """
    session = SnakeSession(_Wide(), SQLiteDialect())

    cars = session.all(SnakeQuery(_Car).include(_Car.brand))

    assert [car.id for car in cars] == list(range(_ROWS))
    assert all(car.brand is not None and car.brand.name == "brand" for car in cars)
    assert len({id(car.brand) for car in cars}) == _ROWS, (
        "every row got the SAME brand object: the hoisting reached past the plan into the results"
    )


def test_the_streamed_include_also_resolves_its_plan_once(counted: list[int]) -> None:
    """`iterate()` hydrates row by row from a generator, and it has to hoist too.

    This is the half a `.all()` test cannot see, and it is the half that matters more: streaming is
    where the row count is unbounded by definition. A first version of this test called the builder
    and walked a list, which would have stayed green with the streaming path unhoisted.
    """
    session = SnakeSession(_Wide(), SQLiteDialect())

    cars = list(session.iterate(SnakeQuery(_Car).include(_Car.brand)))

    assert len(cars) == _ROWS
    assert counted[0] <= 12, (
        f"{counted[0]} plan lookups streaming {_ROWS} rows: `iterate` still resolves per row"
    )


def test_the_streamed_rows_are_hydrated_like_the_eager_ones() -> None:
    """The two colours of the same read agree, relationships included.

    Hoisting in one path and not the other is how the two stop matching, and nothing else here
    compares them.
    """
    eager = SnakeSession(_Wide(), SQLiteDialect()).all(
        SnakeQuery(_Car).include(_Car.brand)
    )
    streamed = list(
        SnakeSession(_Wide(), SQLiteDialect()).iterate(
            SnakeQuery(_Car).include(_Car.brand)
        )
    )

    assert [(c.id, c.brand.name) for c in eager] == [
        (c.id, c.brand.name) for c in streamed
    ]
