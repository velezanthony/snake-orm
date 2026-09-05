"""The index the ORM emits for MySQL is one a REAL MySQL/MariaDB accepts. Executed, not read.

This is the test that pays for the decision, and the reason is written in `test_render_completeness`
and in the emitter matrix: comparing the emitted string against an expected string measures the
emitter against itself. Both sides of that comparison come from the same head, and this bug is
precisely the case where that head was wrong — the string was exactly what the author intended and
the server rejected it.

WHAT IT MEASURES, in this order:

1. That the OLD emission —the `WHERE` written out— really is refused by the server. Without this
   half, the fix is a change of opinion; with it, the bug is a fact, and the day some MariaDB does
   learn partial indexes this test goes red and forces the capability to be re-answered.
2. That the NEW emission runs. Whatever `emit_create_index` decides to write for this engine, the
   server swallows it.
3. That what ends up in the database is a usable index over the whole table, read back out of
   `SHOW INDEX` rather than assumed.

It skips gracefully with no server, like every other integration test here, and `SNAKEORM_REQUIRE_MYSQL`
turns that skip into a failure.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from test.conftest import NO_MYSQL_REASON

from snakeorm import PyMySQLDriver
from snakeorm.dialects import MySQLDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
)
from snakeorm.migration import emit_create_index, emit_create_table

_ID = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
_TABLE = SnakeTableInfo(
    name="partial_index_probe",
    columns=(
        _ID,
        SnakeColumnInfo(
            name="code", python_type=str, type_params=SnakeStrParams(max_length=50)
        ),
        SnakeColumnInfo(name="active", python_type=bool),
    ),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
)
# Copied from `frameworks/shared/models/inventory_models.py`: the condition that broke.
_SEARCH = SnakeIndexInfo(
    columns=("code",),
    name="ix_partial_index_probe_active_code",
    where=SnakeExpr[bool](path=("active",)) == True,  # noqa: E712 - a SQL condition
)


@pytest.fixture
def driver() -> Iterator[PyMySQLDriver]:
    """A real MySQL/MariaDB with the probe table created, dropped again on the way out."""
    host = os.environ.get("MYSQL_HOST")
    if not host:
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    import pymysql

    try:
        connected = PyMySQLDriver.connect(
            host=host,
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DB", "snakeorm_db"),
        )
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    connected.execute("DROP TABLE IF EXISTS partial_index_probe", ())
    connected.execute(emit_create_table(_TABLE, MySQLDialect()), ())
    connected.commit()
    try:
        yield connected
    finally:
        connected.execute("DROP TABLE IF EXISTS partial_index_probe", ())
        connected.commit()
        connected.close()


def test_the_server_really_refuses_the_where(driver: PyMySQLDriver) -> None:
    """The control: the SQL the ORM used to emit is rejected by this server, right now.

    The whole change rests on MySQL/MariaDB not having partial indexes. Asserting it against the
    running server —instead of against the manual— is what keeps the claim falsifiable: if a future
    engine accepts the clause, this goes red and the capability has to be answered again.
    """
    with pytest.raises(Exception) as error:  # noqa: B017 - the server raises its own 1064
        driver.execute(
            "CREATE INDEX `ix_partial_index_probe_active_code` "
            "ON `partial_index_probe` (`code`) WHERE `active` = 1",
            (),
        )

    assert "1064" in str(error.value) or "syntax" in str(error.value).lower()


def test_what_the_orm_emits_today_the_server_accepts(driver: PyMySQLDriver) -> None:
    """Whatever the emitter decides to write for a partial index, MySQL runs it.

    Deliberately NOT asserted against an expected string: the emission is free to change, and what
    must not change is that the server takes it.
    """
    driver.execute(emit_create_index(_TABLE, _SEARCH, MySQLDialect()), ())
    driver.commit()


def test_the_index_lands_over_the_whole_table(driver: PyMySQLDriver) -> None:
    """And what lands is a usable index on `code`, read back from the server's own catalogue.

    The degradation is honest only if something is actually there: an emitter that returned an empty
    statement would pass the test above and leave the table with no index at all.
    """
    driver.execute(emit_create_index(_TABLE, _SEARCH, MySQLDialect()), ())
    driver.commit()

    rows = driver.fetch_all("SHOW INDEX FROM `partial_index_probe`", ())
    indexed = {(str(row[2]), str(row[4])) for row in rows}  # key_name, column_name

    assert ("ix_partial_index_probe_active_code", "code") in indexed
