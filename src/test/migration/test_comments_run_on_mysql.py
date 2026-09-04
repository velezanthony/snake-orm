"""What the ORM emits for a MySQL comment, a REAL MariaDB accepts — and the comment lands. Executed.

The sibling file reasons about the two spellings; this one is the half that pays for the decision.
The rule is the one written in `test_render_completeness` and in the emitter matrix: comparing an
emitted string against an expected string measures the emitter against itself, and both sides come
out of the same head. Here the previous head was wrong in the other direction — it believed the
engine could not do something it does — so the server is the only witness worth calling.

WHAT IT MEASURES, in this order:

1. The CONTROL that fixes the old claim as a fact: `COMMENT ON TABLE` really is refused by this
   server. If some future MySQL learns the statement, this goes red and the grammar gets re-chosen.
2. The CONTROL that fixes the NEW claim: the engine really does store a comment, so the previous
   `Nope` was false. Read out of `information_schema`, not assumed.
3. That each emission runs and that what ends up in the catalogue is the text asked for — table
   comment, column comment, the change of each and the removal of each.
4. The one that decides `Degraded` over `Full`: a `MODIFY COLUMN` that omits what it does not
   respell DESTROYS it. The naive shape drops a `NOT NULL DEFAULT` and an `AUTO_INCREMENT` without
   a word, and the ORM's own shape does not, because it respells the definition from the metadata.

It skips gracefully with no server, like every other integration test here, and
`SNAKEORM_REQUIRE_MYSQL` turns that skip into a failure.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace

import pytest

from test.conftest import NO_MYSQL_REASON

from snakeorm import PyMySQLDriver
from snakeorm.dialects import MySQLDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIntParams,
    SnakeIntSize,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AlterColumn,
    AlterTableComment,
    CreateTable,
    emit_column_comment,
)

_DIALECT = MySQLDialect()
_PROBE = "comment_probe"

_ID = SnakeColumnInfo(
    name="id", python_type=int, autoincrement=True, db_comment="the surrogate key"
)
_QTY = SnakeColumnInfo(
    name="qty",
    python_type=int,
    default=7,
    has_default=True,
    type_params=SnakeIntParams(size=SnakeIntSize.INTEGER),
    db_comment="how many are left",
)
_CODE = SnakeColumnInfo(
    name="code", python_type=str, type_params=SnakeStrParams(max_length=50)
)
_TABLE = SnakeTableInfo(
    name=_PROBE,
    columns=(_ID, _QTY, _CODE),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    db_comment="the parts catalogue",
)


@pytest.fixture
def driver() -> Iterator[PyMySQLDriver]:
    """A real MySQL/MariaDB with the commented probe table created, dropped again on the way out."""
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

    connected.execute(f"DROP TABLE IF EXISTS `{_PROBE}`", ())
    for statement in CreateTable(_TABLE).up_sql(_DIALECT):
        connected.execute(statement, ())
    connected.commit()
    try:
        yield connected
    finally:
        connected.execute(f"DROP TABLE IF EXISTS `{_PROBE}`", ())
        connected.commit()
        connected.close()


def _table_comment(driver: PyMySQLDriver) -> str:
    """The table's comment, read out of the server's own catalogue."""
    rows = driver.fetch_all(
        "SELECT TABLE_COMMENT FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (_PROBE,),
    )
    return str(rows[0][0])


def _column_comments(driver: PyMySQLDriver) -> dict[str, str]:
    """Every column's comment, by column name, read out of the server's own catalogue."""
    rows = driver.fetch_all(
        "SELECT COLUMN_NAME, COLUMN_COMMENT FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (_PROBE,),
    )
    return {str(row[0]): str(row[1]) for row in rows}


def _definition(driver: PyMySQLDriver, column: str) -> tuple[str, str, str]:
    """A column's (is_nullable, default, extra) — the three the naive `MODIFY` quietly wipes."""
    rows = driver.fetch_all(
        "SELECT IS_NULLABLE, COLUMN_DEFAULT, EXTRA FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (_PROBE, column),
    )
    return (str(rows[0][0]), str(rows[0][1]), str(rows[0][2]))


def test_the_server_really_refuses_comment_on(driver: PyMySQLDriver) -> None:
    """The control for the GRAMMAR half of the old reason, which was the true half.

    `COMMENT ON` genuinely does not exist here, so translating it was the right move rather than
    emitting it and hoping. The day a MySQL grows the statement, this goes red on purpose.
    """
    with pytest.raises(Exception) as error:  # noqa: B017 - the server raises its own 1064
        driver.execute(f"COMMENT ON TABLE `{_PROBE}` IS 'x'", ())

    assert "1064" in str(error.value) or "syntax" in str(error.value).lower()


def test_the_server_really_stores_the_comment(driver: PyMySQLDriver) -> None:
    """The control for the CAPABILITY half, which was the false one: the engine keeps them.

    This is the assertion the old `Nope` could not have survived. The fixture created the table with
    the ORM's own `CreateTable`, so what is read back is what this ORM writes today.
    """
    assert _table_comment(driver) == "the parts catalogue"
    assert _column_comments(driver)["qty"] == "how many are left"
    assert _column_comments(driver)["id"] == "the surrogate key"


def test_a_column_left_uncommented_stays_uncommented(driver: PyMySQLDriver) -> None:
    """The absence travels too: MySQL spells 'no comment' as the empty string."""
    assert _column_comments(driver)["code"] == ""


def test_the_table_comment_change_applies_and_reverts(driver: PyMySQLDriver) -> None:
    """`AlterTableComment` both ways, against the catalogue. It used to be refused outright."""
    operation = AlterTableComment(
        replace(_TABLE, db_comment="reworded"), previous="the parts catalogue"
    )

    for statement in operation.up_sql(_DIALECT):
        driver.execute(statement, ())
    driver.commit()
    assert _table_comment(driver) == "reworded"

    for statement in operation.down_sql(_DIALECT):
        driver.execute(statement, ())
    driver.commit()
    assert _table_comment(driver) == "the parts catalogue"


def test_removing_the_table_comment_runs(driver: PyMySQLDriver) -> None:
    """The rollback path, and the one that would have emitted `COMMENT = NULL`: a 1064.

    Measured on this server, `ALTER TABLE t COMMENT = NULL` is a syntax error. Nothing else in the
    suite runs a comment REMOVAL against MySQL, so a shared `dialect.literal(None)` would have sat
    there green until somebody rolled a migration back.
    """
    operation = AlterTableComment(replace(_TABLE, db_comment=None), previous="x")
    for statement in operation.up_sql(_DIALECT):
        driver.execute(statement, ())
    driver.commit()

    assert _table_comment(driver) == ""


def test_the_column_comment_change_applies_and_reverts(driver: PyMySQLDriver) -> None:
    """`AlterColumn` carrying only a comment change, both ways, against the catalogue."""
    new = replace(_QTY, db_comment="how many remain")
    operation = AlterColumn(_TABLE, _QTY, new)

    for statement in operation.up_sql(_DIALECT):
        driver.execute(statement, ())
    driver.commit()
    assert _column_comments(driver)["qty"] == "how many remain"

    for statement in operation.down_sql(_DIALECT):
        driver.execute(statement, ())
    driver.commit()
    assert _column_comments(driver)["qty"] == "how many are left"


def test_the_naive_modify_really_destroys_the_definition(driver: PyMySQLDriver) -> None:
    """THE control that chose `Degraded`. Measured, not argued.

    A `MODIFY COLUMN` that names only the type and the comment is accepted, and it silently turns
    `NOT NULL DEFAULT 7` into `DEFAULT NULL`. This is the shape an emitter written from the manual
    would produce, and it is why a column comment on this engine is not a free operation.
    """
    driver.execute(
        f"ALTER TABLE `{_PROBE}` MODIFY COLUMN `qty` INT COMMENT 'reworded'", ()
    )
    driver.commit()

    nullable, default, _ = _definition(driver, "qty")

    assert nullable == "YES", "the NOT NULL is gone, and nothing said so"
    assert default == "NULL", "the DEFAULT 7 is gone with it"


def test_the_orm_shape_keeps_the_definition_whole(driver: PyMySQLDriver) -> None:
    """And the emitter's own shape does not: it respells the definition out of the metadata.

    The pair with the test above is the whole argument. The engine's only spelling is destructive;
    what makes it safe is that the ORM knows the column and writes it out in full.
    """
    driver.execute(
        emit_column_comment(_TABLE, replace(_QTY, db_comment="reworded"), _DIALECT), ()
    )
    driver.commit()

    nullable, default, _ = _definition(driver, "qty")

    assert _column_comments(driver)["qty"] == "reworded"
    assert nullable == "NO"
    assert default == "7"


def test_the_orm_shape_keeps_the_autoincrement(driver: PyMySQLDriver) -> None:
    """The same, on the primary key, which is where the naive shape costs the most.

    Measured: `MODIFY COLUMN id INT COMMENT 'x'` drops `AUTO_INCREMENT` and leaves a table whose
    next insert has no key. The ORM emits the `AUTO_INCREMENT` because `map_type` puts it there.
    """
    driver.execute(
        emit_column_comment(_TABLE, replace(_ID, db_comment="reworded"), _DIALECT), ()
    )
    driver.commit()

    _, _, extra = _definition(driver, "id")

    assert "auto_increment" in extra.lower()
    assert _column_comments(driver)["id"] == "reworded"


def test_the_comments_survive_the_round_trip_through_introspection(
    driver: PyMySQLDriver,
) -> None:
    """What the ORM writes, its own introspector reads back as the same thing — and the diff is EMPTY.

    This is the property the change makes checkable at all: with the comments dropped there was
    nothing to read back. It matters because MySQL spells "no comment" as the empty string, so an
    introspector that returned `''` where the model says `None` would make the diff see a change on
    every single run — a migration generated for ever out of a schema that never moved.
    """
    from snakeorm.introspection.mysql import MySQLIntrospector
    from snakeorm.migration import diff_schema

    tables = [t for t in MySQLIntrospector(driver).tables() if t.name == _PROBE]
    assert len(tables) == 1
    mirrored = tables[0]

    assert mirrored.db_comment == "the parts catalogue"
    assert {column.name: column.db_comment for column in mirrored.columns} == {
        "id": "the surrogate key",
        "qty": "how many are left",
        "code": None,  # the empty string MySQL stores comes back as "no comment"
    }
    assert diff_schema([mirrored], [mirrored]) == []
