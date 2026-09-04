"""A missing value does not vanish from the INSERT: either it is legitimate, or it is said aloud.

`_insert_values` builds the INSERT with the columns that DO have a value and omits the ones sitting
at `MISSING`. Omitting is the right thing almost always —an autoincrement PK, a column with a
default, one the server fills in—, and that is why nobody looked at it: silence got mistaken for the
rule.

But there is one case where omitting is exactly the opposite of right: a NOT NULL column, with no
default of any kind and no autoincrement. There the `MISSING` does not mean "let the database put
it in", it means "nobody put it in", and omitting it turns a bug in the program into an INSERT the
engine rejects — or worse, accepts.

That is how it was found, and the chain deserves to stay written down because it explains why this
matters: on an engine without `RETURNING`, `add_all()` leaves the PKs unfilled; that `MISSING`
travels as a foreign key into the next row; `_insert_values` omits it without a word; and what
reaches the server is `INSERT INTO user_roles () VALUES ()`. Four steps, not one warning, and a
final message that points at none of the four.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator, Sequence

import pytest

from snakeorm import (
    MySQLDialect,
    SnakeColumn,
    SnakeModel,
    SnakeSession,
    SnakeWarning,
    SQLiteDialect,
    snake_auto,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeValueError
import snakeorm.session.shared as session_mod


@snake_model(table="mvg_orders")
class Order(SnakeModel):
    """`customer_id` is required and nobody fills it in: it is the column of the case."""

    id: SnakeColumn[int] = snake_auto()
    customer_id: SnakeColumn[int] = snake_int()
    note: SnakeColumn[str | None] = snake_str(default=None)
    status: SnakeColumn[str] = snake_str(default="new")


snake_link()


class _Driver:
    """Pretend driver: it records the SQL and returns as many rows as it is asked for.

    The number of rows matters: `add_all` with RETURNING zips instances and rows with `strict=True`,
    so a double that always returned a single one would break the test through its own scaffolding.
    """

    def __init__(self, rows: int = 1) -> None:
        self.seen: list[str] = []
        self._rows = rows

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.seen.append(sql)
        return [(index + 1, 1, None, "new") for index in range(self._rows)]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.seen.append(sql)
        return 1

    @property
    def last_insert_id(self) -> int:
        return 7

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


@pytest.fixture(autouse=True)
def _reset_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empties the warnings already emitted: the dedup is per process and would hide the one here.

    BOTH records: the capabilities one from startup and the `add_all` one. Resetting only one leaves
    the test depending on what ran before it, which is the worst kind of flaky test.
    """
    monkeypatch.setattr(session_mod, "_warned_caveats", set())
    monkeypatch.setattr(session_mod, "_warned_bulk_keys", set())


def test_a_required_column_holding_the_missing_sentinel_is_named_out_loud() -> None:
    """Verifies that a `MISSING` in a required column STOPS the write, and says which one it is.

    It is reproduced the way it really happened, and not by omitting the argument: the constructor
    already DEMANDS `customer_id`, so nothing sneaks in that way. What sneaks in is the sentinel
    itself, passed as a value — which is what the `id` of an instance whose PK never came back from
    the bulk INSERT returns.

    The message names the column. The engine's says "Field 'customer_id' doesn't have a default value"
    and says nothing about which model or which row; over an `add_all` of a thousand, that helps
    nobody.
    """
    sin_id = Order(
        customer_id=1
    )  # its `id` is still MISSING: nobody has written it yet
    session = SnakeSession(_Driver(), SQLiteDialect())

    with pytest.raises(SnakeValueError, match="customer_id"):
        session.add(Order(customer_id=sin_id.id))


def test_what_is_legitimately_missing_stays_quiet() -> None:
    """Verifies the other half: omitting is still the NORMAL thing, and it is left alone.

    Without this check, the guard could shout at any absence and break the three cases in which the
    `MISSING` is exactly what is wanted: an autoincrement PK the database supplies, a column with a
    declared default, and a nullable one left empty.
    """
    driver = _Driver()
    session = SnakeSession(driver, SQLiteDialect())

    session.add(
        Order(customer_id=42)
    )  # id, note and status go MISSING, and that is fine

    assert driver.seen, "the write had to reach the driver"


def test_bulk_insert_warns_that_this_engine_cannot_give_the_ids_back() -> None:
    """Verifies that `add_all` warns when the engine cannot hand the PKs back.

    `add()` recovers them with `lastrowid`; the bulk path cannot, because `lastrowid` only speaks
    about ONE row. Leaving them at MISSING without a word is what chained the disaster together: the
    id that never came back ended up as an empty foreign key three lines further down.

    It warns instead of forbidding: inserting in bulk WITHOUT needing the ids is perfectly
    legitimate and is the majority case. What cannot happen is that whoever DOES need them never
    finds out.
    """
    session = SnakeSession(_Driver(rows=2), MySQLDialect())

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        session.add_all([Order(customer_id=1), Order(customer_id=2)])

    recorded = [
        str(w.message)
        for w in captured
        if issubclass(w.category, SnakeWarning) and "add_all" in str(w.message)
    ]
    assert len(recorded) == 1
    assert "id" in recorded[0]


def test_an_engine_that_returns_rows_says_nothing() -> None:
    """Verifies that where there IS `RETURNING` nothing is warned about: there is nothing to say."""
    session = SnakeSession(_Driver(rows=2), SQLiteDialect())

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        session.add_all([Order(customer_id=1), Order(customer_id=2)])

    assert not [
        w
        for w in captured
        if issubclass(w.category, SnakeWarning) and "add_all" in str(w.message)
    ]


def test_the_bulk_warning_is_said_once_not_once_per_batch() -> None:
    """Verifies that the warning is not repeated on every batch.

    A seeding run does dozens of `add_all`. One warning per batch is noise, and noise ends up in a
    `filterwarnings("ignore")` that takes the ones that did matter down with it.
    """
    session = SnakeSession(_Driver(rows=2), MySQLDialect())

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        session.add_all([Order(customer_id=1)])
        session.add_all([Order(customer_id=2)])

    recorded = [
        w
        for w in captured
        if issubclass(w.category, SnakeWarning) and "add_all" in str(w.message)
    ]
    assert len(recorded) == 1
