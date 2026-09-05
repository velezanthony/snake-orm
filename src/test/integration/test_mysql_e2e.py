"""End-to-end against a REAL MySQL/MariaDB: the third engine, end to end.

It validates what a pure dialect cannot: that the emitted DDL CREATES the table, that the INSERT
returns the PK through `lastrowid` (MySQL has no RETURNING) and that every type round-trips. It
skips gracefully if there is no server —just like the Postgres ones—, reading the connection from
`MYSQL_*` in the environment.

A local MariaDB: `docker run -d -e MARIADB_ROOT_PASSWORD=pass -e MARIADB_DATABASE=snakeorm_db
-p 3306:3306 mariadb:11`, and export MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DB.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from test.conftest import NO_MYSQL_REASON

from snakeorm import (
    PyMySQLDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    SnakeWarning,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_decimal,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.dialects import MySQLDialect
from snakeorm.drivers.base import SnakeDriver
from snakeorm.migration import emit_create_table


@snake_model(table="e2e_items")
class Item(SnakeModel):
    """One column per type, to test the complete round-trip against MySQL."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(max_length=50)
    qty: SnakeColumn[int] = snake_int()
    price: SnakeColumn[Decimal] = snake_decimal(precision=10, scale=2)
    created: SnakeColumn[SnakeUtc] = snake_datetimetz()
    active: SnakeColumn[bool] = snake_column()
    doc: SnakeColumn[dict] = snake_column()


snake_link()


@pytest.fixture(scope="module")
def session() -> Iterator[SnakeSession]:
    """MySQL session with the table created; it skips if there is no reachable server."""
    host = os.environ.get("MYSQL_HOST")
    if not host:
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    import pymysql

    try:
        driver = PyMySQLDriver.connect(
            host=host,
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DB", "snakeorm_db"),
        )
    except (
        pymysql.err.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    dialect = MySQLDialect()
    driver.execute("DROP TABLE IF EXISTS e2e_items", ())
    driver.execute(emit_create_table(snake_table(Item), dialect), ())
    driver.commit()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SnakeWarning)
        yield SnakeSession(driver, dialect)
    driver.close()


_INSTANT = SnakeUtc.of(datetime(2026, 6, 1, 15, 30, 0, tzinfo=UTC))
"""The instant that gets written and expected back. FIXED, and shared by both tests.

Before, `SnakeUtc.now()` was written and compared against a `datetime(2026, 6, 1, 15, 30)` that
nobody wrote. The test did not fail because it never got to run: the model declares `SnakeUtc`, and
MySQL REJECTED it, so the fixture died before reaching here. A test that cannot be run protects
nothing, and on top of that it ages without anyone noticing.
"""


def test_insert_returns_the_pk_via_lastrowid(session: SnakeSession) -> None:
    """Checks that `add()` fills in the PK even though MySQL has no RETURNING (via lastrowid)."""
    row = Item(
        name="silla",
        qty=3,
        price=Decimal("19.99"),
        created=_INSTANT,
        active=True,
        doc={"color": "rojo"},
    )
    session.add(row)
    session.commit()
    assert row.id > 0  # the autoincrement id came back, it did not stay at MISSING


def test_every_type_round_trips_through_mysql(session: SnakeSession) -> None:
    """Checks that every written type comes back IDENTICAL: Decimal, instant, bool (TINYINT), dict (JSON).

    The instant is the interesting case on this engine. MySQL has no usable type with a zone
    —`TIMESTAMP` tops out in 2038 and `DATETIME` is not tz-aware—, so a `SnakeUtc` falls back to
    TEXT. What is checked here is that this fallback loses NOTHING: the same instant comes back AND
    of the declared type, not a `str`. Without the second half, the fallback would have traded a
    noisy error for a silent type leak, which is worse.
    """
    read_back = session.all(SnakeQuery(Item).filter(Item.name == "silla"))
    assert read_back
    row = read_back[0]
    assert row.qty == 3
    assert row.price == Decimal("19.99")
    assert row.created == _INSTANT
    assert isinstance(row.created, SnakeUtc), "the declared type is the type you get"
    assert row.active is True
    assert row.doc == {"color": "rojo"}


def test_a_migration_that_creates_an_index_can_be_rolled_back(
    session: SnakeSession,
) -> None:
    """Creates an index with a migration and UNDOES it, against the real server.

    This is the case that was broken, and the one with the widest radius of the three grammar
    defects: `emit_drop_index` emitted `DROP INDEX x` without `ON table`, which MySQL rejects, and
    the one emitting it is `CreateIndex.down_sql` — meaning the rollback of ANY migration with an
    index died here. On an engine without transactional DDL, moreover, leaving what came before
    applied.

    It is run and reverted for real because the bug was one of SYNTAX: checking the emitted string
    would have measured the emitter against itself, and the only thing that proves a DDL is valid
    is that the server swallows it.
    """
    from snakeorm.metadata import SnakeIndexInfo
    from snakeorm.migration import CreateIndex, Migration, MigrationRunner

    driver = session._driver  # noqa: SLF001 - the runner needs the SAME driver as the session
    runner = MigrationRunner(driver, MySQLDialect())
    runner.ensure_tracking_table()
    index = SnakeIndexInfo(columns=("name",), name="ix_e2e_items_name")
    migration = Migration(
        version="mysql_e2e_index",
        operations=(CreateIndex(snake_table(Item), index),),
    )

    applied = runner.apply([migration])
    assert applied == ["mysql_e2e_index"]
    assert _has_index(driver, "ix_e2e_items_name"), "the index never got created"

    runner.rollback(migration)

    assert not _has_index(driver, "ix_e2e_items_name"), (
        "the rollback did not drop the index: this is the `DROP INDEX` without `ON table` bug"
    )


def _has_index(driver: SnakeDriver, name: str) -> bool:
    """Whether the index REALLY exists in the database, by asking the engine.

    `information_schema` is asked rather than the SQL the ORM emitted: what has to be checked is
    the effect on the database, not that the emitter agrees with itself.
    """
    rows = driver.fetch_all(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND index_name = %s",
        (name,),
    )
    return int(str(rows[0][0])) > 0
