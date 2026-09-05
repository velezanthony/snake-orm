"""One intention —document a table— spelled differently by each engine, which is a dialect's job.

`Cap.COMMENTS` was `Nope` on MySQL, and the reason it gave contradicted itself in its own sentence:
"it has no COMMENT ON: MySQL comments INLINE (COLUMN ... COMMENT), so db_comment values are
omitted". The first half is grammar and it is TRUE; the second half is a capability claim and it is
FALSE. Measured against the MariaDB 11.8.8 of the compose file:

    CREATE TABLE t (c INT COMMENT 'x') COMMENT = 'y'   -> accepted, and both are readable
    ALTER TABLE t COMMENT = 'z'                        -> accepted, and it REPLACES the comment
    COMMENT ON TABLE t IS 'z'                          -> ERROR 1064, syntax error
    information_schema.tables.table_comment            -> 'z'

So the engine stores comments and the ORM was throwing them away — a `db_comment` DISCARDED in
silence on a server that keeps it — while `AlterTableComment` was refused with "there is no comment
to change", a sentence that is simply not true of this engine.

WHY THE ANSWER IS `Degraded` AND NOT `Full`, and it is the column case that decides it. Measured:

    ALTER TABLE t ALTER COLUMN c COMMENT 'x'   -> ERROR 1064
    ALTER TABLE t MODIFY COLUMN c COMMENT 'x'  -> ERROR 4161, Unknown data type: 'COMMENT'
    ALTER TABLE t MODIFY COLUMN c INT NOT NULL DEFAULT 7 COMMENT 'x'  -> accepted

There is no statement that changes a COLUMN comment on its own: the only spelling rewrites the whole
column definition. Everything the statement does not respell is destroyed, and measured that is not
theory — `MODIFY COLUMN qty INT COMMENT 'new'` turned `NOT NULL DEFAULT 7` into `DEFAULT NULL`, and
the same shape on the primary key dropped its `AUTO_INCREMENT` without a word. The ORM respells the
definition out of its own metadata, so what it models survives; what the DATABASE holds and the
model does not describe does not. On Postgres a `COMMENT ON COLUMN` touches nothing but the comment.
That asymmetry is exactly what `Degraded` exists to declare.

WHAT THIS FILE PINS is that both spellings exist, that each engine gets its own, and that neither
one leaks into the other. What it does NOT pin is that a real server accepts them: that is
`test_comments_run_on_mysql.py`, and comparing an emitted string against an expected string measures
the emitter against itself.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.capabilities import Cap, CommentStyle, Degraded, Full, Nope
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
    emit_comments,
    emit_create_table,
    emit_table_comment,
    realize,
)

_POSTGRES = PostgresDialect()
_MYSQL = MySQLDialect()
_SQLITE = SQLiteDialect()

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
    name="parts",
    columns=(_ID, _QTY, _CODE),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    db_comment="the parts catalogue",
)


def _uncommented() -> SnakeTableInfo:
    """The same table with every comment stripped, table and columns alike."""
    return SnakeTableInfo(
        name="parts",
        columns=tuple(
            SnakeColumnInfo(
                name=column.name,
                python_type=column.python_type,
                autoincrement=column.autoincrement,
                default=column.default,
                type_params=column.type_params,
            )
            for column in _TABLE.columns
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(_TABLE.columns[0],)),
    )


# --- What each engine ANSWERS about the capability -------------------------------------------


def test_mysql_declares_comments_degraded_and_not_absent() -> None:
    """MySQL stores comments, so `Nope` was false; the column rewrite is why it is not `Full`."""
    support = _MYSQL.capabilities.support_for(Cap.COMMENTS)

    assert isinstance(support, Degraded)
    assert _MYSQL.capabilities.can(Cap.COMMENTS) is True


def test_the_degraded_reason_names_the_column_rewrite() -> None:
    """The reason is the text a user reads at startup, so it has to name what they actually lose.

    A `Degraded` that only said "it spells it differently" would describe the ORM's problem, not
    theirs. What they lose is that changing ONE column's comment rewrites that column.
    """
    support = _MYSQL.capabilities.support_for(Cap.COMMENTS)
    assert isinstance(support, Degraded)

    assert "MODIFY COLUMN" in support.reason
    assert "COMMENT ON" in support.reason


def test_the_other_two_engines_keep_their_answers() -> None:
    """Postgres does it whole; SQLite stores none at all. Neither answer moves."""
    assert isinstance(_POSTGRES.capabilities.support_for(Cap.COMMENTS), Full)
    assert isinstance(_SQLITE.capabilities.support_for(Cap.COMMENTS), Nope)


def test_every_dialect_declares_a_comment_style() -> None:
    """The SHAPE is grammar and lives in `SnakeSyntax`, so all three answer it — SQLite included.

    `UNSUPPORTED` is the same shape `AlterColumnStyle` already uses for the engine that cannot: the
    plan stops before the emitter runs, so what it would have written never reaches a server.
    """
    assert _POSTGRES.syntax.comment_style is CommentStyle.COMMENT_ON
    assert _MYSQL.syntax.comment_style is CommentStyle.INLINE
    assert _SQLITE.syntax.comment_style is CommentStyle.UNSUPPORTED


# --- CREATE TABLE ----------------------------------------------------------------------------


def test_mysql_carries_both_comments_inside_the_create_table() -> None:
    """The table comment is a clause of the CREATE TABLE here, and so is every column's."""
    sql = emit_create_table(_TABLE, _MYSQL)

    assert sql.endswith("COMMENT = 'the parts catalogue'")
    assert "`id` BIGINT AUTO_INCREMENT COMMENT 'the surrogate key'" in sql
    assert "`qty` INT NOT NULL DEFAULT 7 COMMENT 'how many are left'" in sql


def test_a_column_without_a_comment_gets_no_clause() -> None:
    """Only the columns that carry text; an empty `COMMENT ''` everywhere would be noise."""
    sql = emit_create_table(_TABLE, _MYSQL)

    assert "`code` VARCHAR(50) NOT NULL," in sql or sql.endswith(
        "`code` VARCHAR(50) NOT NULL"
    )
    assert "`code` VARCHAR(50) NOT NULL COMMENT" not in sql


def test_mysql_emits_no_separate_comment_statements() -> None:
    """`emit_comments` is EMPTY on MySQL, and for a new reason: they already travelled inline.

    It used to be empty because the comment was thrown away. Returning statements now would write
    each comment twice — once in the CREATE and once after it.
    """
    assert emit_comments(_TABLE, _MYSQL) == []
    assert CreateTable(_TABLE).up_sql(_MYSQL) == [emit_create_table(_TABLE, _MYSQL)]


def test_postgres_still_keeps_the_comments_out_of_the_create() -> None:
    """The other engine is untouched: `COMMENT ON` is a statement of its own, emitted after."""
    statements = CreateTable(_TABLE).up_sql(_POSTGRES)

    assert "COMMENT" not in statements[0]
    assert any(sql.startswith("COMMENT ON TABLE") for sql in statements)
    assert any(sql.startswith("COMMENT ON COLUMN") for sql in statements)


def test_sqlite_writes_no_comment_anywhere() -> None:
    """The engine that stores none keeps dropping them, in the CREATE and after it."""
    assert "COMMENT" not in emit_create_table(_TABLE, _SQLITE)
    assert emit_comments(_TABLE, _SQLITE) == []


# --- ALTER TABLE ... COMMENT = ---------------------------------------------------------------


def test_mysql_changes_a_table_comment_with_an_alter_table() -> None:
    """The engine's own spelling, and it REPLACES the previous comment rather than adding one."""
    assert (
        emit_table_comment(_TABLE, _MYSQL)
        == "ALTER TABLE `parts` COMMENT = 'the parts catalogue'"
    )


def test_removing_a_table_comment_on_mysql_writes_an_empty_string() -> None:
    """`COMMENT = NULL` is a SYNTAX ERROR here, measured; the empty string is how MySQL clears one.

    Postgres removes a comment with `IS NULL`, and `dialect.literal(None)` returns `NULL` on both
    engines — so the shared emitter would have written MySQL a 1064 on the one path nobody tests,
    the rollback.
    """
    sql = emit_table_comment(_uncommented(), _MYSQL)

    assert sql == "ALTER TABLE `parts` COMMENT = ''"
    assert "NULL" not in sql


def test_postgres_still_removes_a_comment_with_is_null() -> None:
    """The control on the other side: the engine that HAS `IS NULL` keeps using it."""
    assert emit_table_comment(_uncommented(), _POSTGRES).endswith("IS NULL")


def test_the_alter_table_comment_operation_runs_on_mysql_now() -> None:
    """`AlterTableComment` up and down both emit, where before both were empty lists."""
    operation = AlterTableComment(_TABLE, previous="the old wording")

    assert operation.up_sql(_MYSQL) == [
        "ALTER TABLE `parts` COMMENT = 'the parts catalogue'"
    ]
    assert operation.down_sql(_MYSQL) == [
        "ALTER TABLE `parts` COMMENT = 'the old wording'"
    ]


def test_realize_stops_refusing_the_comment_change_on_mysql() -> None:
    """The plan let it through: `Degraded` is a yes, and the refusal message was false here.

    It said "this engine does not store COMMENT ON, so there is no comment to change". MySQL stores
    one and changes it; the sentence described the ORM's missing grammar as the engine's missing
    feature.
    """
    assert realize([AlterTableComment(_TABLE, previous=None)], _MYSQL)


def test_realize_still_refuses_the_comment_change_on_sqlite() -> None:
    """And the engine the refusal was always TRUE about keeps being refused."""
    with pytest.raises(SnakeMigrationError, match="AlterTableComment"):
        realize([AlterTableComment(_TABLE, previous=None)], _SQLITE)


# --- The column comment, which is the degraded half ------------------------------------------


def test_mysql_changes_a_column_comment_by_rewriting_the_column() -> None:
    """The only spelling the engine has, and the whole definition travels with it.

    Not decoration: measured, a `MODIFY` that omits the `NOT NULL` and the `DEFAULT` DELETES them.
    The definition is respelled from the metadata precisely so nothing the model knows is lost.
    """
    sql = emit_column_comment(_TABLE, _QTY, _MYSQL)

    assert sql == (
        "ALTER TABLE `parts` MODIFY COLUMN `qty` INT NOT NULL DEFAULT 7 "
        "COMMENT 'how many are left'"
    )


def test_the_rewrite_keeps_the_autoincrement_of_a_primary_key() -> None:
    """The worst measured case: a `MODIFY` without `AUTO_INCREMENT` drops it in silence.

    The table stays, the rows stay, and the next insert has no key. A green migration that broke the
    table — which is the failure shape this branch exists to kill.
    """
    assert emit_column_comment(_TABLE, _ID, _MYSQL) == (
        "ALTER TABLE `parts` MODIFY COLUMN `id` BIGINT AUTO_INCREMENT "
        "COMMENT 'the surrogate key'"
    )


def test_a_comment_only_change_emits_exactly_one_statement() -> None:
    """Nothing else about the column moved, so one `MODIFY` carries the whole change.

    Before this, `AlterColumn` returned an EMPTY list on MySQL for a comment-only edit: the diff saw
    the change, wrote it into the migration file, and the file did nothing.
    """
    old = SnakeColumnInfo(name="qty", python_type=int, db_comment="the old wording")
    new = SnakeColumnInfo(name="qty", python_type=int, db_comment="the new wording")

    statements = AlterColumn(_TABLE, old, new).up_sql(_MYSQL)

    assert len(statements) == 1
    assert "COMMENT 'the new wording'" in statements[0]


def test_the_comment_rides_the_same_modify_as_a_type_change() -> None:
    """When the column changes anyway, the comment goes in that statement — not a second one.

    `MODIFY` rewrites the definition whole, so a second statement would not add anything; it would
    just be one more chance for the two to disagree.
    """
    old = SnakeColumnInfo(name="qty", python_type=int, db_comment="the old wording")
    new = SnakeColumnInfo(
        name="qty",
        python_type=int,
        nullable=True,
        db_comment="the new wording",
    )

    statements = AlterColumn(_TABLE, old, new).up_sql(_MYSQL)

    assert len(statements) == 1
    assert "COMMENT 'the new wording'" in statements[0]


def test_the_reverse_puts_the_previous_comment_back() -> None:
    """Reversibility is the property that lets this be emitted at all instead of refused."""
    old = SnakeColumnInfo(name="qty", python_type=int, db_comment="the old wording")
    new = SnakeColumnInfo(name="qty", python_type=int, db_comment="the new wording")

    down = AlterColumn(_TABLE, old, new).down_sql(_MYSQL)

    assert len(down) == 1
    assert "COMMENT 'the old wording'" in down[0]


def test_dropping_a_column_comment_omits_the_clause() -> None:
    """Measured: a `MODIFY` with no `COMMENT` clause clears whatever comment the column had.

    So removal needs no special spelling — which is the opposite of the TABLE comment, where the
    absent clause changes nothing and the empty string is required.
    """
    old = SnakeColumnInfo(name="qty", python_type=int, db_comment="the old wording")
    new = SnakeColumnInfo(name="qty", python_type=int)

    statements = AlterColumn(_TABLE, old, new).up_sql(_MYSQL)

    assert len(statements) == 1
    assert "COMMENT" not in statements[0]


def test_postgres_keeps_the_comment_in_a_statement_of_its_own() -> None:
    """The other engine does not rewrite anything: two statements, and the column is untouched."""
    old = SnakeColumnInfo(name="qty", python_type=int, db_comment="the old wording")
    new = SnakeColumnInfo(name="qty", python_type=int, db_comment="the new wording")

    statements = AlterColumn(_TABLE, old, new).up_sql(_POSTGRES)

    assert statements == [
        'COMMENT ON COLUMN "public"."parts"."qty" IS \'the new wording\''
    ]


# --- Neither grammar leaks into the other engine ----------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        emit_create_table(_TABLE, _MYSQL),
        emit_table_comment(_TABLE, _MYSQL),
        emit_column_comment(_TABLE, _QTY, _MYSQL),
    ],
    ids=["create_table", "table_comment", "column_comment"],
)
def test_no_comment_emission_writes_mysql_a_comment_on(sql: str) -> None:
    """`COMMENT ON` is Postgres grammar and this server answers 1064 to it, measured."""
    assert "COMMENT ON" not in sql


def test_postgres_never_gets_the_inline_spelling() -> None:
    """And the reverse leak: `ALTER TABLE ... COMMENT =` is not a statement Postgres has."""
    assert "COMMENT =" not in emit_create_table(_TABLE, _POSTGRES)
    assert "COMMENT =" not in emit_table_comment(_TABLE, _POSTGRES)
