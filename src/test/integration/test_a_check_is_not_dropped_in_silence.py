"""A CHECK exists in the database, the mirror cannot declare it, and nobody was being told.

`snake_check` takes a `SnakeCondition` and validates it at declaration time; there is no raw-SQL
escape hatch, and there should not be one — reconstructing a condition from the server's own text
would be writing a SQL parser, per engine. So a CHECK cannot be mirrored, which is fine.

What was NOT fine is that `unsupported()` never mentioned it. The generated file carries those
sentences as comments, and its header says the database holds more than the model shows. A rule
that silently rejects rows the model claims are valid is exactly what that comment block exists to
name, and the query never asked for one: Postgres only looked at `contype` `'u'` and `'f'`.

**This test has to be an integration test.** `test_unsupported_warnings` feeds canned rows to a
driver double that IGNORES the SQL, so it proves the sentence is worded once — it cannot prove the
query ASKS. Those are different failures, and the second one is the one that was live.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from snakeorm.drivers.base import SnakeDriver
from snakeorm.introspection import (
    MySQLIntrospector,
    PostgresIntrospector,
    SQLiteIntrospector,
)
from snakeorm.introspection.base import SnakeIntrospector
from test.scenarios.engines import three_drivers

pytestmark = pytest.mark.integration

_READERS: dict[str, Callable[[SnakeDriver], SnakeIntrospector]] = {
    "postgres": PostgresIntrospector,
    "mysql": MySQLIntrospector,
    "sqlite": SQLiteIntrospector,
}

_CAN_READ_CHECKS = ("postgres", "mysql")
"""SQLite keeps no catalogue of constraints: its CHECK lives inside the `CREATE TABLE` TEXT of
`sqlite_master`, so finding one means parsing DDL. A substring match would report a column called
`check_digit` as a constraint, which is the kind of lie this module exists to avoid — so SQLite
does not answer this question, and that is a difference in what a catalogue can say."""

_TABLE = (
    "CREATE TABLE chk_invoices ("
    "  id INT NOT NULL PRIMARY KEY,"
    "  total INT NOT NULL,"
    "  CONSTRAINT ck_chk_invoices_total CHECK (total > 0))"
)


@pytest.fixture
def drivers() -> Iterator[dict[str, SnakeDriver]]:
    """The three engines with one CHECK constraint in them."""
    with three_drivers([]) as engines:
        for driver in engines.values():
            driver.execute("DROP TABLE IF EXISTS chk_invoices", ())
            driver.execute(_TABLE, ())
            driver.commit()
        yield engines
        for driver in engines.values():
            driver.execute("DROP TABLE IF EXISTS chk_invoices", ())
            driver.commit()


@pytest.mark.parametrize("engine", _CAN_READ_CHECKS)
def test_the_engine_reports_the_check_it_is_enforcing(
    drivers: dict[str, SnakeDriver], engine: str
) -> None:
    """The warning names the constraint AND the table, against a real server.

    The expression is not compared: Postgres normalises `total > 0` to `(total > 0)` and MySQL
    quotes the identifier. Pinning the server's own rendering would be testing the server.
    """
    reader: SnakeIntrospector = _READERS[engine](drivers[engine])

    found = [line for line in reader.unsupported() if line.startswith("check: ")]

    assert len(found) == 1, f"{engine} reported {found}"
    assert "ck_chk_invoices_total" in found[0]
    assert "chk_invoices" in found[0]


@pytest.mark.parametrize("engine", _CAN_READ_CHECKS)
def test_the_check_does_not_come_back_as_a_mirrored_constraint(
    drivers: dict[str, SnakeDriver], engine: str
) -> None:
    """It is REPORTED, never declared. The two are different promises and only one is true here.

    Emitting a `snake_check` would mean having reconstructed the condition, and the mirror has
    not: what it has is the server's text.
    """
    reader: SnakeIntrospector = _READERS[engine](drivers[engine])

    mirrored = next(table for table in reader.tables() if table.name == "chk_invoices")

    assert mirrored.checks == ()
