"""Locking, savepoints and case-insensitive matching, on the engines that have them.

Three features with three different shapes of engine support, which is why they share a file: what
is worth checking about each is the same question asked of a different subset.

| feature | Postgres | MySQL | SQLite |
|---|---|---|---|
| `for_update()` | runs | runs | declares `Nope` |
| `ILIKE` | runs | runs, `Degraded` | runs, `Degraded` |
| `savepoint()` / `set_isolation()` | runs | runs | runs |

The engines that cannot are not simply left out: each has a test that asks the CATALOGUE why, and
goes red the day the answer changes. An absent engine and a forgotten one look identical otherwise,
which is the confusion this project spends most of its guards on.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeIsolation,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.dialects.capabilities import Cap, Nope
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="cc_people")
class Person(SnakeModel):
    """Names in mixed case, so a case-insensitive match has something to prove."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    tally: SnakeColumn[int] = snake_int()


_ROWS = [(1, "Ada", 1), (2, "GRACE", 2), (3, "linus", 3), (4, "Hopper", 4)]
_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the same three people."""
    with three_sessions([Person]) as sessions:
        for session in sessions.values():
            session.add_all([Person(id=i, name=n, tally=t) for i, n, t in _ROWS])
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", ["postgres", "mysql"])
def test_for_update_locks_and_still_returns_the_rows(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`FOR UPDATE` is a clause on a SELECT: it must still answer the rows it selected.

    Only one connection here, so what is checked is not the contention — that needs two sessions
    fighting and belongs with the retry work — but that the clause reaches the engine and does not
    change the result. A `FOR UPDATE` the engine rejects would surface here as an error, and one the
    ORM silently dropped would look identical to this passing, which is why the SQL is checked too.
    """
    session = engines[engine]
    query = SnakeQuery(Person).filter(Person.tally >= 2).order_by(Person.id.asc())

    rows = session.all(query.for_update())

    assert [row.name for row in rows] == ["GRACE", "linus", "Hopper"]
    assert "FOR UPDATE" in query.for_update().to_sql(session.dialect)[0]


def test_sqlite_says_it_cannot_lock_rows_and_that_is_why_it_is_absent(
    engines: dict[str, SnakeSession],
) -> None:
    """SQLite is missing from the run above because it DECLARES it has no row locking."""
    support = engines["sqlite"].dialect.capabilities.support_for(Cap.ROW_LOCKING)

    assert isinstance(support, Nope), (
        f"SQLite now answers {type(support).__name__} for row locking: add it above"
    )
    assert support.reason


@pytest.mark.parametrize("engine", _ENGINES)
def test_ilike_matches_regardless_of_case_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """One pattern matches all three spellings of the letter, on the three engines.

    Only Postgres has the `ILIKE` keyword; the other two say so in `syntax.has_ilike`. What they do NOT
    do is fall back to a plain `LIKE`, which is the tempting shortcut and would be wrong in a way
    nobody notices: on MySQL a plain `LIKE` is case-insensitive by the COLUMN'S COLLATION, so it
    would work until somebody changed the schema. They emit `LOWER(col) LIKE LOWER(?)` instead —
    explicit, and the same answer everywhere. That is why this runs on all three.
    """
    session = engines[engine]

    rows = session.all(
        SnakeQuery(Person).filter(Person.name.ilike("%a%")).order_by(Person.id.asc())
    )

    assert [row.name for row in rows] == ["Ada", "GRACE"]


@pytest.mark.parametrize("engine", ["mysql", "sqlite"])
def test_the_engines_without_the_keyword_still_answer_the_same(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The two without the keyword emit the lowering, and the SQL says so rather than hiding it.

    Asserted against `syntax.has_ilike` and no longer against the catalogue, which is the whole of
    that fix: the SHAPE to write and how GOOD the result is are two questions. Reading the second
    for the first is what let `Nope` sit on a capability every engine answers.
    """
    session = engines[engine]
    sql, _ = SnakeQuery(Person).filter(Person.name.ilike("%a%")).to_sql(session.dialect)

    assert session.dialect.syntax.has_ilike is False
    assert "ILIKE" not in sql
    assert "LOWER" in sql


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_savepoint_discards_only_what_is_inside_it(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The block rolls back and the write BEFORE it survives, which is the whole point.

    Checking only that the inner write vanished would pass on an implementation that rolled the
    whole transaction back — the failure the savepoint exists to prevent. So both halves are read.
    """
    session = engines[engine]

    session.update_where(
        SnakeQuery(Person).filter(Person.id == 1), [(Person.tally, 100)]
    )

    with pytest.raises(RuntimeError):
        with session.savepoint():
            session.update_where(
                SnakeQuery(Person).filter(Person.id == 2), [(Person.tally, 200)]
            )
            raise RuntimeError("the block fails on purpose")

    session.commit()
    rows = session.all(SnakeQuery(Person).order_by(Person.id.asc()))

    assert [row.tally for row in rows] == [100, 2, 3, 4]


@pytest.mark.parametrize("engine", ["postgres", "mysql"])
def test_setting_the_isolation_level_is_accepted_where_the_engine_has_it(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The level is set and the session keeps working: the statement reached the engine."""
    session = engines[engine]

    session.set_isolation(SnakeIsolation.SERIALIZABLE)

    assert session.first(SnakeQuery(Person).filter(Person.id == 1)) is not None


def test_sqlite_refuses_to_set_an_isolation_level_and_says_why(
    engines: dict[str, SnakeSession],
) -> None:
    """SQLite says it cannot, instead of being handed a statement it does not have.

    This is the test that found it. `set_isolation` used to pass the SQL straight to the driver, so
    SQLite answered `near "SET": syntax error` — the ORM emitting something the engine refuses
    rather than saying what it could not do, and doing it from the session, which is exactly what
    the dialect seam exists to prevent.
    """
    session = engines["sqlite"]

    with pytest.raises(SnakeUnsupportedFeature) as refusal:
        session.set_isolation(SnakeIsolation.SERIALIZABLE)

    assert "isolation" in str(refusal.value)
    assert "PRAGMA read_uncommitted" in str(refusal.value)
