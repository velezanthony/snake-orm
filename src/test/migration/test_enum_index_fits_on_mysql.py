"""An index over an enum column CREATES on a real MySQL. Executed, not read.

The demo's `orders` table has `ix_orders_warehouse_state` over `(warehouse_id, state)`, and `state`
is a `StrEnum`. With the enum's width thrown away the column came out `TEXT`, and InnoDB refuses a
key over a blob-family column beyond its 3072-byte budget: `1071, Specified key was too long`. The
demo did not start.

WHAT THIS MEASURES, in this order:

1. That the OLD shape —the same index over a `TEXT` column— really is refused by THIS server, right
   now. Without that half the fix is an opinion; with it the bug is a fact, and the day a server
   stops refusing it this goes red and the reasoning gets re-examined.
2. That what the ORM emits TODAY for the very same model runs.
3. That the index actually landed, read back from the server's catalogue rather than assumed.
4. That the three dialects agree on what the column now is, and that the autogen does NOT invent a
   migration out of the change — a replayed migration file and today's model derive the same width.

It skips gracefully with no server, like every integration test here, and `SNAKEORM_REQUIRE_MYSQL`
turns that skip into a failure.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from enum import StrEnum

import pytest

from test.conftest import NO_MYSQL_REASON

from snakeorm import PyMySQLDriver
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeEnumStorage,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AlterColumn,
    diff_schema,
    emit_create_index,
    emit_create_table,
    sql_type_of,
)

_TABLE_NAME = "enum_index_probe"


class OrderState(StrEnum):
    """The demo's own states, copied from `frameworks/shared/models/orders_models.py`.

    `cancelled` is the longest at 9 characters, which is the number the whole file turns on.
    """

    DRAFT = "draft"
    RESERVED = "reserved"
    INVOICED = "invoiced"
    SETTLED = "settled"
    CANCELLED = "cancelled"


_LONGEST = len(OrderState.CANCELLED.value)

_ID = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
_WAREHOUSE = SnakeColumnInfo(name="warehouse_id", python_type=int)
_STATE = SnakeColumnInfo(
    name="state",
    python_type=OrderState,
    enum_type=OrderState,
    enum_storage=SnakeEnumStorage.CHECK,
)


def _table(state: SnakeColumnInfo = _STATE) -> SnakeTableInfo:
    """The cut-down `orders`: the PK, the FK column and the enum the index is built over."""
    return SnakeTableInfo(
        name=_TABLE_NAME,
        columns=(_ID, _WAREHOUSE, state),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


_INDEX = SnakeIndexInfo(
    columns=("warehouse_id", "state"),
    name="ix_enum_index_probe_warehouse_state",
)


@pytest.fixture
def driver() -> Iterator[PyMySQLDriver]:
    """A real MySQL/MariaDB with the probe table dropped on both ends; the tests create it."""
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

    connected.execute(f"DROP TABLE IF EXISTS `{_TABLE_NAME}`", ())
    connected.commit()
    try:
        yield connected
    finally:
        connected.execute(f"DROP TABLE IF EXISTS `{_TABLE_NAME}`", ())
        connected.commit()
        connected.close()


def test_the_server_really_refuses_the_index_over_a_text_column(
    driver: PyMySQLDriver,
) -> None:
    """The control: the shape the ORM used to emit is rejected by this server, right now.

    The whole change rests on InnoDB not indexing a `TEXT` column inside its key budget. Asserting it
    against the running server —instead of against the manual— keeps the claim falsifiable.
    """
    driver.execute(
        f"CREATE TABLE `{_TABLE_NAME}` ("
        "`id` BIGINT AUTO_INCREMENT, `warehouse_id` BIGINT NOT NULL, `state` TEXT NOT NULL, "
        "PRIMARY KEY (`id`))",
        (),
    )
    driver.commit()

    with pytest.raises(Exception) as error:  # noqa: B017 - the server raises its own 1071
        driver.execute(
            f"CREATE INDEX `{_INDEX.name}` ON `{_TABLE_NAME}` (`warehouse_id`, `state`)",
            (),
        )

    assert "1071" in str(error.value)


def test_what_the_orm_emits_today_the_server_accepts(driver: PyMySQLDriver) -> None:
    """The same model, the same index, emitted by the ORM as it stands: MySQL takes it.

    Deliberately NOT asserted against an expected string: the emission is free to change, and what
    must not is that the server swallows it.
    """
    driver.execute(emit_create_table(_table(), MySQLDialect()), ())
    driver.execute(emit_create_index(_table(), _INDEX, MySQLDialect()), ())
    driver.commit()


def test_the_index_lands_over_both_columns(driver: PyMySQLDriver) -> None:
    """And what lands is the composite index, read back from `SHOW INDEX`.

    An emitter that quietly dropped the enum column from the key would pass the test above and leave
    the listing scanning the whole order history.
    """
    driver.execute(emit_create_table(_table(), MySQLDialect()), ())
    driver.execute(emit_create_index(_table(), _INDEX, MySQLDialect()), ())
    driver.commit()

    rows = driver.fetch_all(f"SHOW INDEX FROM `{_TABLE_NAME}`", ())
    indexed = {(str(row[2]), str(row[4])) for row in rows}  # key_name, column_name

    assert (_INDEX.name, "warehouse_id") in indexed
    assert (_INDEX.name, "state") in indexed


def test_mysql_writes_a_varchar_of_the_enum_width() -> None:
    """Verifies the emission itself: MySQL sizes the enum column instead of falling back to TEXT."""
    assert sql_type_of(_STATE, MySQLDialect()) == f"VARCHAR({_LONGEST})"


def test_postgres_writes_a_varchar_of_the_enum_width() -> None:
    """Verifies Postgres writes the same `VARCHAR(n)`, which there is `TEXT` plus a length check.

    The type NAME changes on this engine —it used to be `TEXT`— and the behaviour does not: the CHECK
    already refuses anything that is not a member, so no value that fits the enum can fail the
    length. Written down instead of assumed, because a change of emitted SQL is a change.
    """
    assert sql_type_of(_STATE, PostgresDialect()) == f"VARCHAR({_LONGEST})"


def test_sqlite_still_writes_text() -> None:
    """Verifies SQLite is untouched: it has no lengths and does not pretend to.

    One TEXT affinity for everything, so the derived width has nothing to translate into there.
    """
    assert sql_type_of(_STATE, SQLiteDialect()) == "TEXT"


def test_the_autogen_converges_on_an_already_migrated_schema() -> None:
    """Verifies that the derivation invents NO migration where there was none.

    The autogen diffs today's model against the state replayed out of the migration FILES, and a
    generated file spells an enum column exactly like this one — `enum_type` set, `type_params`
    left out. Both sides derive the same width, so the two columns still compare equal and
    `makemigrations` proposes nothing. This is the test that says the fix is free for anybody with
    a schema already on disk.
    """
    assert diff_schema([_table()], [_table()]) == []


def test_a_longer_member_is_still_a_column_change() -> None:
    """Verifies the derivation stays VISIBLE to the diff: a wider enum migrates.

    A file generated when the longest value was 4 characters replays as an explicit
    `SnakeStrParams(max_length=4)`; today's enum derives 9. That is a real column change and the
    autogen has to propose it, or the database keeps a column too narrow for what the model allows.
    """
    historical = SnakeColumnInfo(
        name="state",
        python_type=OrderState,
        enum_type=OrderState,
        enum_storage=SnakeEnumStorage.CHECK,
        type_params=SnakeStrParams(max_length=4),
    )

    operations = diff_schema([_table(historical)], [_table()])

    assert [type(operation) for operation in operations] == [AlterColumn]
