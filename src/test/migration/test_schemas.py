"""`CreateSchema`: declaring `schema="analytics"` compiled, and the `migrate` blew up.

`CREATE SCHEMA` existed nowhere in the repository. The compiler accepted the schema, the metadata
stored it, the DDL emitted `CREATE TABLE "analytics"."x"`… and Postgres answered that the schema
does not exist.

It is EXACTLY the same pattern as the index diff and as `db_comment`: the metadata accepts something
the DDL does not know how to create. Three times the same class of error in this repository, and
that is why the 4-point contract is written down in the roadmap.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    CreateSchema,
    DropSchema,
    SchemaState,
    diff_schema,
    emit_create_schema,
    emit_drop_schema,
)

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)


def _table(name: str, schema: str = "public") -> SnakeTableInfo:
    """Minimal table in the given schema."""
    return SnakeTableInfo(
        name=name,
        columns=(_ID,),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        schema=schema,
    )


def test_the_ddl_is_idempotent_on_creation() -> None:
    """Verifies the `IF NOT EXISTS`: the DBA may have created it before, and then the state is right."""
    assert (
        emit_create_schema("analytics", _DIALECT)
        == 'CREATE SCHEMA IF NOT EXISTS "analytics"'
    )


def test_the_reverse_does_not_cascade() -> None:
    """Verifies that the `DROP` does NOT carry CASCADE: if anything is left inside, let it fail.

    A reverse that razes what it did not create is far worse than one that refuses.
    """
    ddl = emit_drop_schema("analytics", _DIALECT)
    assert ddl == 'DROP SCHEMA "analytics"'
    assert "CASCADE" not in ddl


def test_a_new_schema_is_created_before_its_tables() -> None:
    """THE BUG: a table in a new schema needs the schema to exist BEFOREHAND."""
    operations = diff_schema([], [_table("events", schema="analytics")])

    kinds = [type(op).__name__ for op in operations]
    assert kinds == ["CreateSchema", "CreateTable"]
    created = operations[0]
    assert isinstance(created, CreateSchema)
    assert created.schema == "analytics"


def test_public_is_never_created() -> None:
    """Verifies that no migration is dirtied by creating the schema that always exists."""
    operations = diff_schema([], [_table("users")])
    assert [type(op).__name__ for op in operations] == ["CreateTable"]


def test_an_existing_schema_is_not_recreated() -> None:
    """Verifies that a schema already present in the previous state is not created again."""
    before = [_table("events", schema="analytics")]
    after = [_table("events", schema="analytics"), _table("hits", schema="analytics")]

    assert [type(op).__name__ for op in diff_schema(before, after)] == ["CreateTable"]


def test_an_emptied_schema_is_not_dropped() -> None:
    """Verifies that running out of tables does NOT drop the schema.

    Inside there may be things we do not govern —views from another team, functions, grants— and
    dropping it would take down what is not ours. What is needed gets created; cleaning up is a
    decision for the human.
    """
    operations = diff_schema([_table("events", schema="analytics")], [])
    assert "DropSchema" not in [type(op).__name__ for op in operations]


def test_the_operations_are_inverse_and_mutate_the_state() -> None:
    """Verifies the operation contract: inverse up/down and a coherent `apply_to_state`."""
    state = SchemaState()
    assert "analytics" not in state.schemas()

    CreateSchema("analytics").apply_to_state(state)
    assert "analytics" in state.schemas()

    assert CreateSchema("analytics").down_sql(_DIALECT) == DropSchema(
        "analytics"
    ).up_sql(_DIALECT)

    DropSchema("analytics").apply_to_state(state)
    assert "analytics" not in state.schemas()


def test_public_is_in_the_state_from_the_start() -> None:
    """Verifies that `public` is taken as existing: in Postgres it is, nobody creates it."""
    assert "public" in SchemaState().schemas()
