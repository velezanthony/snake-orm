"""The three ways a row comes back must give the SAME `Decimal`, padding included.

`mapper` hands `column.scale` to `converter_for`; `coerce` did not. So the same column read through
`all()` came back `Decimal('1.00')` and through `add()`/`refresh()` came back `Decimal('1')`.

Measured on SQLite with `snake_decimal(precision=10, scale=2)`:

    after add():     Decimal('1')
    after all():     Decimal('1.00')
    after refresh(): Decimal('1')

`refresh()` is the one that stings: it takes an object that was already right —hydrated by `all()`
with its scale— and makes it worse. A method whose whole job is "go and get the current truth".

WHY NOBODY SAW IT: `Decimal('1') == Decimal('1.00')` is True. Every equality assertion in the suite
passes across the discrepancy, and arithmetic never notices either. It shows up in `str()`, which is
to say on a screen: one price printed `1` and the other `1.00`. So these assertions compare `str()`
on purpose — comparing the values would reproduce exactly the blindness that let it live.

`coercion.py` argues the general case against itself: "A subset is a copy that has already started
drifting; the fix is not to top it up but to stop having two." This is the same drift one argument
further down — the delegation was there, and it dropped a parameter on the way through.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from decimal import Decimal

from snakeorm.decorators import snake_model
from snakeorm.dialects import SQLiteDialect
from snakeorm.fields import SnakeColumn, snake_decimal, snake_int
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession


@snake_model(table="ds_prices")
class _Price(SnakeModel):
    """A model with a scaled decimal, which is the only kind that can show this."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    amount: SnakeColumn[Decimal] = snake_decimal(precision=10, scale=2)


snake_link()


class _FakeDriver:
    """Fake driver that answers every read with the same unpadded value the engine would give.

    SQLite stores a `Decimal` as TEXT and gives back exactly what went in, so `'1'` is what a real
    engine hands over here — the padding is the ORM's job, and the question is whether all three
    doors do it.
    """

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return [(1, "1")]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return 1

    @property
    def last_insert_id(self) -> int:
        return 1

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


def _session() -> SnakeSession:
    """A session over the fake driver."""
    return SnakeSession(_FakeDriver(), SQLiteDialect())


def test_the_read_back_doors_pad_the_decimal_the_same_way() -> None:
    """`all()` and `refresh()` must agree, to the last zero.

    `str()` and not `==`, because `Decimal('1') == Decimal('1.00')` is True and that equality is
    precisely why this survived. What differs is what a user sees printed.
    """
    session = _session()

    hydrated = session.all(SnakeQuery(_Price))[0]
    assert str(hydrated.amount) == "1.00", "the hydration door lost the declared scale"

    session.refresh(hydrated)

    assert str(hydrated.amount) == "1.00", (
        "refresh() took an object that was already right and made it worse: it read the value back "
        "through a door that does not know the column's scale"
    )


def test_the_value_itself_is_untouched_by_the_padding() -> None:
    """The floor: padding is presentation, not arithmetic. The number must not change.

    Without this, "pad to the declared scale" could be implemented as a rounding that silently
    changed stored money, and every assertion above would still pass.
    """
    session = _session()
    row = session.all(SnakeQuery(_Price))[0]

    assert row.amount == Decimal(1)
