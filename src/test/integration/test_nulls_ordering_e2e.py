"""`nulls_last()` puts the nulls last on all three engines, against real servers.

The unit test next door pins the SPELLING. This one runs it, which is the half that matters: the
defect it closes was `ERROR 1064` from a server, and a test that asserts the emitted string is
exactly what let it live — `test_locking_and_nulls.py` fixed `PostgresDialect()` and compared a
string that is identical in all three dialects, so it could not see the failure at all.

Measured while writing this, on both engines the MySQL dialect serves — because `mysql.py` exists
partly because it "cannot promise what only one of them does":

    MariaDB 11.8.8   NULLS LAST -> ERROR 1064      (x IS NULL) form -> correct
    MySQL   8.4.11   NULLS LAST -> ERROR 1064      (x IS NULL) form -> correct
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, snake_int, snake_str
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.engines import three_sessions


@snake_model(table="nulls_order_e2e")
class _Row(SnakeModel):
    """A row whose sortable column is nullable, which is the whole point."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    nickname: SnakeColumn[str | None] = snake_str()


snake_link()


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three sessions, seeded with one null in the middle."""
    with three_sessions([_Row]) as sessions:
        for session in sessions.values():
            session.add_all(
                [
                    _Row(id=1, nickname="b"),
                    _Row(id=2, nickname=None),
                    _Row(id=3, nickname="a"),
                ]
            )
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_nulls_last_puts_the_null_at_the_end(
    engines: dict[str, SnakeSession], engine: str
) -> None:
    """Red before the fix on mysql with `ERROR 1064`; green on the other two."""
    rows = engines[engine].all(
        SnakeQuery(_Row).order_by(_Row.nickname.asc().nulls_last())
    )

    assert [row.nickname for row in rows] == ["a", "b", None]


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_nulls_first_puts_the_null_at_the_start(
    engines: dict[str, SnakeSession], engine: str
) -> None:
    """The other direction, because a translation that ignored it would sort every query alike.

    That failure is worse than the 1064: it runs, and it returns rows in an order nobody asked for.
    """
    rows = engines[engine].all(
        SnakeQuery(_Row).order_by(_Row.nickname.asc().nulls_first())
    )

    assert [row.nickname for row in rows] == [None, "a", "b"]


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_the_ordinary_order_is_unchanged(
    engines: dict[str, SnakeSession], engine: str
) -> None:
    """The floor: a key that did not ask for nulls ordering keeps the engine's own default.

    The three engines disagree about where a null goes by default, so this asserts only that the
    non-null rows are in order — which is the part the ORM promised.
    """
    rows = engines[engine].all(SnakeQuery(_Row).order_by(_Row.nickname.asc()))

    named = [row.nickname for row in rows if row.nickname is not None]
    assert named == ["a", "b"]
