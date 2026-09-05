"""The statement timeout SET on the engines that have one, and refused on the one that has not.

The emission had a test over the string. A string that no engine accepts caps nothing, and this is
the knob that keeps a single hung query from draining a pool — so it is worth running rather than
reading, on each engine, through the decorator a user actually wraps with.

The three answers are three different things and the file asserts all three:

- PostgreSQL takes `SET statement_timeout = <ms>` and the connection is capped from then on;
- MySQL takes its own spelling, in SECONDS, and the fork matters — MariaDB and MySQL do not share
  the variable name, which the dialect writes down;
- SQLite answers `None`, so `TimeoutDriver` REFUSES to wrap it. That refusal is the feature: a
  connection that looks capped and is not is worse than one that is honestly uncapped.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from snakeorm import SnakeDriver
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.drivers.timeout import TimeoutDriver
from test.scenarios.engines import DIALECTS, three_drivers

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.fixture
def drivers(tmp_path: pathlib.Path) -> Iterator[dict[str, SnakeDriver]]:
    """A bare driver per engine. No tables: the subject is the connection, not any data."""
    with three_drivers([], sqlite_path=str(tmp_path / "timeout.db")) as opened:
        yield opened


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_dialect_answers_for_the_engine_it_describes(engine: str) -> None:
    """`None` is a legitimate answer here and not a gap, so it is asserted as one.

    SQLite has no server-side statement timeout at all. Its `busy_timeout` waits for a LOCK and does
    nothing about a slow query, so answering with it would be answering a different question.
    """
    statement = DIALECTS[engine].statement_timeout_sql(5000)

    if engine == "sqlite":
        assert statement is None, "SQLite has no server-side statement timeout to give"
    else:
        assert statement, f"{engine} answered nothing for a timeout it does have"


@pytest.mark.parametrize("engine", ["postgres", "mysql"])
def test_the_engine_accepts_the_statement_and_the_wrap_holds(
    engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """The decorator SETS it on construction, so building it is what proves the engine took it.

    That is why there is no separate "did it run" assertion: `TimeoutDriver.__init__` executes the
    statement, so a spelling the engine rejects raises right here — which is exactly what happened
    when the driver wrote Postgres syntax for all three.
    """
    wrapped = TimeoutDriver(
        drivers[engine], DIALECTS[engine], statement_timeout_ms=5000
    )

    assert wrapped.fetch_all("SELECT 1", ()) == [(1,)]


def test_sqlite_is_refused_rather_than_wrapped_in_a_lie(
    drivers: dict[str, SnakeDriver],
) -> None:
    """The refusal IS the feature, and the message says why rather than just saying no.

    Accepting the wrap would hand back a connection that LOOKS capped and is not, which is the
    opposite of what asking for a timeout means.
    """
    with pytest.raises(SnakeDialectError, match="statement timeout"):
        TimeoutDriver(drivers["sqlite"], DIALECTS["sqlite"], statement_timeout_ms=5000)
