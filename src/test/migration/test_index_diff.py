"""Tests of the INDEX diff: two schema states → CreateIndex / DropIndex.

Covers the hole through which adding an index to an ALREADY migrated model generated an EMPTY
migration, and silently: `diff_schema` did not compare the indexes and the operations did not
exist. Indexes were only born inside the `up_sql` of `CreateTable`.

The IDENTITY of an index is its RESOLVED NAME (the explicit one, or the generated
`ix_{table}_{columns}`): it is what the database knows, so it is what the diff runs on.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    CreateIndex,
    CreateTable,
    DropIndex,
    SchemaState,
    diff_schema,
    emit_drop_index,
)

_ID = SnakeColumnInfo(name="id", python_type=int)
_EMAIL = SnakeColumnInfo(name="email", python_type=str)
_CITY = SnakeColumnInfo(name="city", python_type=str)


def _table(*indexes: SnakeIndexInfo) -> SnakeTableInfo:
    """The 'users' table (id, email, city) with the given indexes."""
    return SnakeTableInfo(
        name="users",
        columns=(_ID, _EMAIL, _CITY),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        indexes=indexes,
    )


def test_resolved_name_falls_back_to_generated() -> None:
    """Verifies that the resolved name is the explicit one if there is one, else the generated."""
    assert SnakeIndexInfo(columns=("email",)).resolved_name("users") == "ix_users_email"
    assert (
        SnakeIndexInfo(columns=("email", "city")).resolved_name("users")
        == "ix_users_email_city"
    )
    assert (
        SnakeIndexInfo(columns=("email",), name="mi_indice").resolved_name("users")
        == "mi_indice"
    )


def test_new_index_on_existing_table_yields_create_index() -> None:
    """Verifies THE BUG: a new index on an already existing table produces a CreateIndex."""
    operations = diff_schema([_table()], [_table(SnakeIndexInfo(columns=("email",)))])

    assert len(operations) == 1
    operation = operations[0]
    assert isinstance(operation, CreateIndex)
    assert operation.index.columns == ("email",)
    assert operation.table.name == "users"


def test_removed_index_yields_drop_index() -> None:
    """Verifies that an index no longer in the metadata produces a DropIndex."""
    operations = diff_schema([_table(SnakeIndexInfo(columns=("email",)))], [_table()])

    assert len(operations) == 1
    operation = operations[0]
    assert isinstance(operation, DropIndex)
    assert operation.index.columns == ("email",)


def test_unchanged_index_yields_nothing() -> None:
    """Verifies that an index identical in both states produces no operation at all."""
    index = SnakeIndexInfo(columns=("email",), unique=True)
    assert diff_schema([_table(index)], [_table(index)]) == []


def test_changed_unique_yields_drop_then_create() -> None:
    """Verifies that changing `unique` under the SAME name recreates the index (drop + create).

    Postgres cannot turn an index into a unique one: it has to be dropped and created again.
    """
    before = SnakeIndexInfo(columns=("email",))
    after = SnakeIndexInfo(columns=("email",), unique=True)

    operations = diff_schema([_table(before)], [_table(after)])

    assert len(operations) == 2
    drop, create = operations
    assert isinstance(drop, DropIndex) and drop.index.unique is False
    assert isinstance(create, CreateIndex) and create.index.unique is True


def test_new_table_does_not_duplicate_its_indexes() -> None:
    """Verifies that a NEW table emits no separate CreateIndex: its CreateTable already carries them.

    `CreateTable.up_sql` includes the `CREATE INDEX` of the table. Emitting a CreateIndex on top
    would duplicate the DDL and the migration would fail when applied.
    """
    operations = diff_schema([], [_table(SnakeIndexInfo(columns=("email",)))])

    assert len(operations) == 1
    assert isinstance(operations[0], CreateTable)


def test_dropped_table_does_not_emit_drop_index() -> None:
    """Verifies that dropping a table emits no DropIndex: the DROP TABLE takes its indexes."""
    operations = diff_schema([_table(SnakeIndexInfo(columns=("email",)))], [])

    assert len(operations) == 1
    assert not isinstance(operations[0], DropIndex)


def test_emit_drop_index_uses_the_resolved_name() -> None:
    """Verifies the drop DDL: `DROP INDEX "schema"."name"` (the index lives in the schema)."""
    ddl = emit_drop_index(
        _table(), SnakeIndexInfo(columns=("email",)), PostgresDialect()
    )
    assert ddl == 'DROP INDEX "public"."ix_users_email"'


def test_emit_drop_index_honours_the_explicit_name() -> None:
    """Verifies that the DROP uses the explicit name when the index declares one."""
    index = SnakeIndexInfo(columns=("email",), name="mi_indice")
    ddl = emit_drop_index(_table(), index, PostgresDialect())
    assert ddl == 'DROP INDEX "public"."mi_indice"'


def test_create_index_up_and_down_are_inverse() -> None:
    """Verifies that the `up` of CreateIndex creates and its `down` drops the SAME object.

    With `unique=True` the object is a CONSTRAINT (`uq_*`), not an index: uniqueness is declared
    as a domain rule and the index is only its implementation.
    """
    index = SnakeIndexInfo(columns=("email",), unique=True)
    operation = CreateIndex(_table(), index)
    dialect = PostgresDialect()

    assert operation.up_sql(dialect) == [
        'ALTER TABLE "public"."users" ADD CONSTRAINT "uq_users_email" UNIQUE ("email")'
    ]
    assert operation.down_sql(dialect) == [
        'ALTER TABLE "public"."users" DROP CONSTRAINT "uq_users_email"'
    ]


def test_drop_index_up_and_down_are_inverse() -> None:
    """Verifies that DropIndex is the exact mirror of CreateIndex."""
    index = SnakeIndexInfo(columns=("email",))
    operation = DropIndex(_table(), index)
    dialect = PostgresDialect()

    assert operation.up_sql(dialect) == ['DROP INDEX "public"."ix_users_email"']
    assert operation.down_sql(dialect) == [
        'CREATE INDEX "ix_users_email" ON "public"."users" ("email")'
    ]


def test_create_index_apply_to_state_adds_it() -> None:
    """Verifies that CreateIndex mutates the abstract state (what the autogen replays)."""
    state = SchemaState([_table()])
    index = SnakeIndexInfo(columns=("email",))

    CreateIndex(_table(), index).apply_to_state(state)

    table = state.get_table("users")
    assert table is not None
    assert table.indexes == (index,)


def test_drop_index_apply_to_state_removes_it() -> None:
    """Verifies that DropIndex removes the index from the abstract state."""
    index = SnakeIndexInfo(columns=("email",))
    state = SchemaState([_table(index)])

    DropIndex(_table(index), index).apply_to_state(state)

    table = state.get_table("users")
    assert table is not None
    assert table.indexes == ()


def test_full_cycle_leaves_the_state_matching_the_metadata() -> None:
    """Verifies the FULL CYCLE: metadata → diff → replay → identical state.

    It is the test that would have caught the bug the day it was introduced: the operations are
    replayed onto an empty state and the result must have the SAME indexes as the metadata.
    """
    desired = _table(SnakeIndexInfo(columns=("email",), unique=True))

    state = SchemaState()
    for operation in diff_schema([], [desired]):
        operation.apply_to_state(state)
    for operation in diff_schema(state.tables(), [desired]):
        operation.apply_to_state(state)

    table = state.get_table("users")
    assert table is not None
    assert table.indexes == desired.indexes
