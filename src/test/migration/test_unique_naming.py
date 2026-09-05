"""Uniqueness: ONE single database object and ONE single naming scheme (`uq_{table}_{columns}`).

There were two ways of asking for uniqueness that produced DIFFERENT objects:

- `snake_column(unique=True)` → an INLINE and UNNAMED `UNIQUE` in the `CREATE TABLE`, which Postgres
  auto-names `{table}_{column}_key`.
- `SnakeIndex(..., unique=True)` → `CREATE UNIQUE INDEX ix_{table}_{columns}`.

And `emit_alter_column`, on removing `unique`, emitted `DROP CONSTRAINT uq_{table}_{column}`: a name
that did NOT exist in the database. Verified against a real Postgres:

    CREATE TABLE uq_probe (... "email" TEXT NOT NULL UNIQUE ...);
    -- pg_constraint -> uq_probe_email_key
    ALTER TABLE uq_probe DROP CONSTRAINT "uq_uq_probe_email";
    -- ERROR: constraint "uq_uq_probe_email" of relation "uq_probe" does not exist

That is: removing `unique=True` from a column generated a migration that BLOWS UP when applied.
Now the constraint is ALWAYS created with an explicit name, and creating and dropping agree.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import emit_create_index, emit_create_table, emit_drop_index

_ID = SnakeColumnInfo(name="id", python_type=int)


def _table(
    *, unique_column: bool = False, indexes: tuple[SnakeIndexInfo, ...] = ()
) -> SnakeTableInfo:
    """The 'users' table (id, email, city), with the email column unique if asked for."""
    return SnakeTableInfo(
        name="users",
        columns=(
            _ID,
            SnakeColumnInfo(name="email", python_type=str, unique=unique_column),
            SnakeColumnInfo(name="city", python_type=str),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        indexes=indexes,
    )


def test_unique_column_emits_a_named_constraint_not_a_bare_unique() -> None:
    """THE BUG: the CREATE TABLE constraint must carry OUR name, not the one Postgres invents."""
    ddl = emit_create_table(_table(unique_column=True), PostgresDialect())

    assert 'CONSTRAINT "uq_users_email" UNIQUE ("email")' in ddl
    # And NOT the bare inline UNIQUE any more, which was what Postgres auto-named.
    assert '"email" TEXT NOT NULL UNIQUE' not in ddl


def test_non_unique_column_adds_no_constraint() -> None:
    """Verifies that a plain column drags no uniqueness constraint along with it."""
    assert "UNIQUE" not in emit_create_table(_table(), PostgresDialect())


def test_unique_index_declaration_becomes_a_constraint_too() -> None:
    """Verifies that `SnakeIndex(unique=True)` produces the SAME class of object as the column.

    A constraint STATES a domain rule; the unique index is only how it gets implemented (Postgres
    creates the index underneath anyway). One single object and one single naming scheme.
    """
    index = SnakeIndexInfo(columns=("email", "city"), unique=True)
    ddl = emit_create_index(_table(), index, PostgresDialect())

    assert ddl == (
        'ALTER TABLE "public"."users" ADD CONSTRAINT "uq_users_email_city" '
        'UNIQUE ("email", "city")'
    )


def test_dropping_a_unique_declaration_drops_the_same_constraint() -> None:
    """Verifies that the reverse attacks EXACTLY the name the `up` created (the root of the bug)."""
    index = SnakeIndexInfo(columns=("email", "city"), unique=True)
    ddl = emit_drop_index(_table(), index, PostgresDialect())

    assert ddl == 'ALTER TABLE "public"."users" DROP CONSTRAINT "uq_users_email_city"'


def test_non_unique_index_is_still_an_index() -> None:
    """Verifies that a NON-unique index is still an index: only uniqueness changes object."""
    index = SnakeIndexInfo(columns=("city",))
    dialect = PostgresDialect()

    assert emit_create_index(_table(), index, dialect) == (
        'CREATE INDEX "ix_users_city" ON "public"."users" ("city")'
    )
    assert (
        emit_drop_index(_table(), index, dialect)
        == 'DROP INDEX "public"."ix_users_city"'
    )


def test_resolved_name_encodes_the_kind_of_object() -> None:
    """Verifies the prefix per kind: `uq_` for a constraint, `ix_` for an index."""
    assert (
        SnakeIndexInfo(columns=("email",), unique=True).resolved_name("users")
        == "uq_users_email"
    )
    assert SnakeIndexInfo(columns=("email",)).resolved_name("users") == "ix_users_email"
    # The explicit name overrules the prefix in both cases.
    assert (
        SnakeIndexInfo(columns=("email",), unique=True, name="mi_regla").resolved_name(
            "users"
        )
        == "mi_regla"
    )
