"""The GRAMMAR of the DDL per engine: the same operation, written the way each one understands it.

Until now a dialect decided the VOCABULARY —identifiers, types, literals— and not the grammar: the
SHAPE of the statement was wired into the emitter, with the Postgres one. It worked while the ORM
was single-engine, and with three it leaves three holes no test could see because the emitter matrix
only ran Postgres × SQLite. The orphan sibling was precisely the one that breaks.

The three of them, and why they are not cosmetic:

1. `DROP INDEX` without `ON table` is refused by MySQL. And the one emitting it is
   `CreateIndex.down_sql`, that is, **the rollback of any migration creating an index failed on MySQL**.
2. `ALTER COLUMN ... TYPE ... USING` is Postgres syntax; MySQL writes `MODIFY COLUMN`. Since MySQL
   declares that it DOES know how to alter columns, the plan let the operation through and the error
   came out as engine syntax halfway through a migration — and MySQL has no transactional DDL, so
   with no rollback.
3. `emit_alter_column` emitted the `COMMENT ON` of a comment change without looking at whether the
   engine stores them, when `emit_comments` had been looking from the very beginning.

These tests check the SHAPE of the SQL, not its execution: the third engine would need a server, and
the failure is one of grammar, not of semantics. Real execution lives in the e2e ones.
"""

from __future__ import annotations

import pytest

from snakeorm import MySQLDialect, PostgresDialect, SnakeDialect, SQLiteDialect
from snakeorm.dialects.capabilities import Cap
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import ddl

_ID = SnakeColumnInfo(name="id", python_type=int)
_TEXT = SnakeColumnInfo(name="texto", python_type=str, nullable=True)
_TEXT_REQUIRED = SnakeColumnInfo(name="texto", python_type=str, nullable=False)
_TABLE = SnakeTableInfo(
    name="parts",
    columns=(_ID, _TEXT),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
)
_INDEX = SnakeIndexInfo(columns=("texto",), name="ix_parts_texto")


def test_drop_index_names_the_table_only_where_the_engine_asks_for_it() -> None:
    """Verifies that MySQL gets `ON table` and the other two do not.

    It is the widest-reaching bug of the three: `CreateIndex.down_sql` calls in here, so without the
    `ON` the rollback of every migration with an index died on MySQL with a syntax error.
    """
    in_mysql = ddl.emit_drop_index(_TABLE, _INDEX, MySQLDialect())
    in_postgres = ddl.emit_drop_index(_TABLE, _INDEX, PostgresDialect())
    in_sqlite = ddl.emit_drop_index(_TABLE, _INDEX, SQLiteDialect())

    assert " ON " in in_mysql and "parts" in in_mysql
    assert " ON " not in in_postgres
    assert " ON " not in in_sqlite


def test_drop_index_qualifies_by_schema_only_where_there_are_schemas() -> None:
    """Verifies that the schema and the `ON table` are SEPARATE decisions.

    They were conflated: the condition for adding the `ON` was `supports_schemas`, which has nothing
    to do with it. With that mixture, MySQL (no schemas) fell into the branch that also omitted the
    `ON`, and the two errors covered for each other.
    """
    assert "public" in ddl.emit_drop_index(_TABLE, _INDEX, PostgresDialect())
    assert "public" not in ddl.emit_drop_index(_TABLE, _INDEX, MySQLDialect())
    assert "public" not in ddl.emit_drop_index(_TABLE, _INDEX, SQLiteDialect())


def test_postgres_alters_a_column_with_its_own_grammar() -> None:
    """Verifies that Postgres keeps emitting `ALTER COLUMN ... TYPE ... USING`, unchanged."""
    statements = ddl.emit_alter_column(_TABLE, _TEXT, _TEXT_REQUIRED, PostgresDialect())

    assert any("ALTER COLUMN" in s and "SET NOT NULL" in s for s in statements)
    assert not any("MODIFY COLUMN" in s for s in statements)


def test_mysql_alters_a_column_with_modify_not_with_alter_column() -> None:
    """Verifies that MySQL gets `MODIFY COLUMN` with the WHOLE definition, not the Postgres shape.

    `MODIFY` rewrites the complete definition, so a type change and a nullability change come
    together in ONE statement. Emitting two (one per change, the way Postgres does) would leave the
    second one trampling what the first did.
    """
    statements = ddl.emit_alter_column(_TABLE, _TEXT, _TEXT_REQUIRED, MySQLDialect())

    assert any("MODIFY COLUMN" in s for s in statements)
    assert not any("ALTER COLUMN" in s for s in statements)
    assert not any("USING" in s for s in statements)
    modify = [s for s in statements if "MODIFY COLUMN" in s]
    assert len(modify) == 1, "MODIFY rewrites the whole definition: a single statement"
    assert "NOT NULL" in modify[0], "the whole definition includes the nullability"


def test_altering_a_column_never_emits_a_comment_on_outside_postgres() -> None:
    """Verifies that no engine but Postgres is written a `COMMENT ON`, for TWO different reasons.

    `emit_comments` had been looking from the start; this path did not, so altering a column with a
    `db_comment` smuggled in a `COMMENT ON` that neither of the other two understands.

    The reasons stopped being the same, and the name of this test used to claim they were the one
    that is now half false. SQLite stores no comment at all; MySQL stores them perfectly well and
    spells them as a clause, so what it gets here is a `MODIFY COLUMN`. What both share is only the
    thing asserted below: `COMMENT ON` is Postgres grammar and it never reaches them.
    """
    without_comment = SnakeColumnInfo(name="texto", python_type=str, nullable=True)
    with_comment = SnakeColumnInfo(
        name="texto", python_type=str, nullable=True, db_comment="qué guarda"
    )

    for dialect in (MySQLDialect(), SQLiteDialect()):
        statements = ddl.emit_alter_column(
            _TABLE, without_comment, with_comment, dialect
        )
        assert not any("COMMENT ON" in s for s in statements), (
            f"{type(dialect).__name__} has no COMMENT ON statement and still got one"
        )

    in_postgres = ddl.emit_alter_column(
        _TABLE, without_comment, with_comment, PostgresDialect()
    )
    assert any("COMMENT ON" in s for s in in_postgres), (
        "Postgres does store them: dropping it for all would be the other half of the bug"
    )


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect(), SQLiteDialect()],
    ids=lambda d: type(d).__name__,
)
def test_no_engine_ever_receives_the_grammar_of_another(dialect: SnakeDialect) -> None:
    """Verifies that no engine ever receives a construction that is not its own.

    It is the net above the concrete cases: it enumerates the (engine, foreign syntax) pairs and
    demands that they not show up. A new emitter that copies the Postgres shape falls in here
    without anybody having to remember to write it a test.
    """
    foreign_syntax = {
        "MySQLDialect": ("ALTER COLUMN", "USING"),
        "PostgresDialect": ("MODIFY COLUMN",),
        "SQLiteDialect": ("MODIFY COLUMN",),
    }[type(dialect).__name__]

    alterations = (
        ddl.emit_alter_column(_TABLE, _TEXT, _TEXT_REQUIRED, dialect)
        if dialect.capabilities.can(Cap.ALTER_COLUMN)
        else []
    )
    emitted = " ".join([ddl.emit_drop_index(_TABLE, _INDEX, dialect), *alterations])

    for construct in foreign_syntax:
        assert construct not in emitted


def test_an_insert_with_no_values_is_written_as_each_engine_writes_it() -> None:
    """A row with NO values (a PK-only table) is written differently in each engine.

    `INSERT INTO t DEFAULT VALUES` is standard and Postgres and SQLite understand it; MySQL does NOT,
    and asks for `INSERT INTO t () VALUES ()`. It is not a laboratory case: it is triggered by any
    bridge or event table whose only field of its own is the autoincrement id, and the demo uncovered
    it while seeding against a real MySQL.
    """
    from snakeorm.sql import emit_insert

    pk_only_table = SnakeTableInfo(
        name="events",
        columns=(_ID,),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )

    in_postgres, _ = emit_insert(pk_only_table, PostgresDialect(), {})
    in_sqlite, _ = emit_insert(pk_only_table, SQLiteDialect(), {})
    in_mysql, _ = emit_insert(pk_only_table, MySQLDialect(), {})

    assert "DEFAULT VALUES" in in_postgres
    assert "DEFAULT VALUES" in in_sqlite
    assert "DEFAULT VALUES" not in in_mysql
    assert "() VALUES ()" in in_mysql
