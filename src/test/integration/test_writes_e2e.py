"""The writes, EXECUTED on the three engines: insert, update, delete, bulk, upsert and refresh.

A write is where the string test is least able to help. The SQL of an `UPDATE ... WHERE` is the same
shape everywhere and the interesting part is what it TOUCHED: the count it reports, the rows it left
alone, and whether the object in memory still agrees with the database afterwards. None of that is
in the string.

`upsert` earns its place here above the rest. All three engines answer `Cap.UPSERT: Full()` and all
three spell it differently — `ON CONFLICT DO UPDATE`, `ON DUPLICATE KEY UPDATE`, and SQLite's own
`ON CONFLICT` since 3.24 — so it is the one write where "the dialect translates it" is a claim with
three different SQL strings behind it and one required outcome.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
)
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="wr_counters")
class Counter(SnakeModel):
    """A counter per key, so an upsert has something to collide with."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    key: SnakeColumn[str] = snake_str(unique=True)
    hits: SnakeColumn[int] = snake_int()


_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with an EMPTY table: every test here writes, so it seeds its own rows."""
    with three_sessions([Counter]) as sessions:
        yield sessions


def _seed(session: SnakeSession) -> None:
    """Three counters, one of which no test touches — the witness that a write stayed in its lane."""
    session.add_all(
        [
            Counter(id=1, key="alfa", hits=10),
            Counter(id=2, key="bravo", hits=20),
            Counter(id=3, key="untouched", hits=99),
        ]
    )
    session.commit()


def _hits(session: SnakeSession, key: str) -> int:
    """What the database holds for one key, read back."""
    row = session.first(SnakeQuery(Counter).filter(Counter.key == key))
    assert row is not None
    return row.hits


@pytest.mark.parametrize("engine", _ENGINES)
def test_insert_update_and_delete_touch_only_what_they_name(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Each of the three reports how many rows it moved, and the bystander keeps its value.

    The bystander is the point. An `UPDATE` with a filter the ORM dropped would report a bigger
    number, but a count is easy to read past; a row that changed when nothing named it is not.
    """
    session = engines[engine]
    _seed(session)

    changed = session.update_where(
        SnakeQuery(Counter).filter(Counter.key == "alfa"), [(Counter.hits, 11)]
    )
    session.commit()
    assert changed == 1
    assert _hits(session, "alfa") == 11

    removed = session.delete_where(SnakeQuery(Counter).filter(Counter.key == "bravo"))
    session.commit()
    assert removed == 1
    assert session.first(SnakeQuery(Counter).filter(Counter.key == "bravo")) is None

    assert _hits(session, "untouched") == 99


@pytest.mark.parametrize("engine", _ENGINES)
def test_an_update_can_read_the_column_it_is_writing(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`hits = hits + 1` is computed by the ENGINE, not by reading the row and writing it back."""
    session = engines[engine]
    _seed(session)

    session.update_where(
        SnakeQuery(Counter).filter(Counter.key == "alfa"),
        [(Counter.hits, Counter.hits + 5)],
    )
    session.commit()

    assert _hits(session, "alfa") == 15


@pytest.mark.parametrize("engine", _ENGINES)
def test_add_all_writes_every_row(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A bulk insert leaves every row in, and the count matches what was handed over."""
    session = engines[engine]

    session.add_all([Counter(id=i, key=f"k{i}", hits=i) for i in range(1, 6)])
    session.commit()

    rows = session.all(SnakeQuery(Counter).order_by(Counter.id.asc()))
    assert [(row.id, row.hits) for row in rows] == [(i, i) for i in range(1, 6)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_upsert_inserts_the_first_time_and_updates_the_second(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The same call twice: it creates the row, then rewrites the column it was told to.

    Called twice on purpose. An `upsert` that silently degraded into a plain INSERT would pass a
    test that only ran it once, and fail with a duplicate key on the second — which is the failure
    the feature exists to prevent.
    """
    session = engines[engine]
    _seed(session)

    session.upsert(
        Counter(id=4, key="alfa", hits=100),
        on_conflict=[Counter.key],
        update=[Counter.hits],
    )
    session.commit()
    assert _hits(session, "alfa") == 100

    session.upsert(
        Counter(id=5, key="alfa", hits=250),
        on_conflict=[Counter.key],
        update=[Counter.hits],
    )
    session.commit()
    assert _hits(session, "alfa") == 250

    assert _hits(session, "untouched") == 99


@pytest.mark.parametrize("engine", _ENGINES)
def test_refresh_brings_the_object_back_in_step_with_the_database(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """After a bulk update the in-memory object is stale, and `refresh()` is what fixes it."""
    session = engines[engine]
    _seed(session)

    alfa = session.first(SnakeQuery(Counter).filter(Counter.key == "alfa"))
    assert alfa is not None

    session.update_where(
        SnakeQuery(Counter).filter(Counter.key == "alfa"), [(Counter.hits, 77)]
    )
    session.commit()
    assert alfa.hits == 10, (
        "the bulk write does not reach into the objects already loaded"
    )

    session.refresh(alfa)
    assert alfa.hits == 77
