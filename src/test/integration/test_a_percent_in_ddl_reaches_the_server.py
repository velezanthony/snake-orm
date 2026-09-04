"""A statement carrying a literal `%` has to reach the SERVER, on all three engines.

This is the test the previous one could not be. `src/test/sql/test_condition_ddl.py:50` celebrates
that a literal `'100%s'` survives the inlining and asserts the STRING — and it is green over the
exact line psycopg refuses, because the string is right and the string was never the problem. The
statement died in the driver, one layer below where that test stops looking.

The cause: `adapt_params` returned `()` for a statement with no parameters, and psycopg and PyMySQL
read `()` as "you gave me parameters, so re-read this SQL as a format template". DDL cannot be
parametrised, so every DDL statement takes that path — a `COMMENT ON`, a `DEFAULT`, a `CHECK` with a
`LIKE '%mail%'`, the `WHERE` of a partial index, the body of a routine.

Coverage answers whether a line RAN, never what was checked: a line can come out 100% covered by a
test that only asserts the emitted SQL. This one executes.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm.decorators import SnakeRow, snake_row
from snakeorm.drivers import SnakeDriver
from snakeorm.session import SnakeSession
from test.scenarios.engines import three_drivers, three_sessions


@snake_row
class _Text(SnakeRow):
    """The DECLARED shape of the one-column answer these probes read back."""

    x: str


@pytest.fixture
def drivers() -> Iterator[dict[str, SnakeDriver]]:
    """One driver per engine, with no models: every statement here is raw DDL or a raw SELECT."""
    with three_drivers([]) as engines:
        yield engines


@pytest.fixture
def sessions() -> Iterator[dict[str, SnakeSession]]:
    """One session per engine, for the PUBLIC escape hatch (`session.raw`)."""
    with three_sessions([]) as opened:
        yield opened


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_a_literal_percent_survives_the_trip_to_the_engine(
    sessions: dict[str, SnakeSession], engine: str
) -> None:
    """A SELECT of a literal `'100%'` comes back as `100%`, with no parameters in play.

    Red before the fix on postgres (`ProgrammingError: only '%s', '%b', '%t' are allowed as
    placeholders`) and on mysql (`TypeError: not enough arguments for format string`); green on
    sqlite, whose DBAPI does not reformat. That split IS the defect, and it is why the fix is a
    per-driver flag rather than a blanket `or None` — sqlite3 REFUSES `None` outright.
    """
    rows = sessions[engine].raw("SELECT '100%' AS x", into=_Text)

    assert rows[0].x == "100%"


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_ddl_carrying_a_percent_is_accepted(
    drivers: dict[str, SnakeDriver], engine: str
) -> None:
    """A `DEFAULT` with a `%` inside it: the shape the migration runner actually emits.

    A SELECT is the smallest reproduction; this is the one that matters, because DDL is where the
    parameters are ALWAYS empty and so where the bug was unavoidable rather than occasional.
    """
    driver = drivers[engine]

    driver.execute("DROP TABLE IF EXISTS pct_probe", ())
    driver.execute(
        "CREATE TABLE pct_probe (id INTEGER, label VARCHAR(40) DEFAULT '50% off')", ()
    )
    driver.execute("INSERT INTO pct_probe (id) VALUES (1)", ())
    driver.commit()

    rows = driver.fetch_all("SELECT label FROM pct_probe WHERE id = 1", ())

    assert rows[0][0] == "50% off"


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_a_percent_alongside_real_parameters_is_still_the_callers_business(
    sessions: dict[str, SnakeSession], engine: str
) -> None:
    """The scope of the fix, pinned down: only the EMPTY case changed.

    With real parameters the DBAPI's formatting pass runs as it always has, and a bare `%` in the
    SQL is still the caller's problem. Writing that down here stops the next reader from assuming
    the ORM now escapes percent signs, which it does not and should not — it is the same reason
    `MOD` is not in the capability catalogue.
    """
    session = sessions[engine]
    placeholder = session.dialect.placeholder(1)

    rows = session.raw(f"SELECT {placeholder} AS x", ("100%",), into=_Text)

    assert rows[0].x == "100%"
