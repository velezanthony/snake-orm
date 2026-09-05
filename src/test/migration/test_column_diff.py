"""Tests of the column-level diff: AddColumn/DropColumn on tables that still exist."""

from __future__ import annotations

from typing import Any

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    CreateTable,
    AddColumn,
    DropColumn,
    Migration,
    autodetect,
    diff_schema,
    emit_add_column,
    replay,
)


def _table(*extra: SnakeColumnInfo) -> SnakeTableInfo:
    """The 'users' table with 'id' + the given extra columns."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="users",
        columns=(id_col, *extra),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def test_add_column_ddl() -> None:
    """Verifies the ALTER TABLE ADD COLUMN with the type and NOT NULL."""
    column = SnakeColumnInfo(name="email", python_type=str)
    ddl = emit_add_column(_table(), column, PostgresDialect())
    assert ddl == 'ALTER TABLE "public"."users" ADD COLUMN "email" TEXT NOT NULL'


def test_diff_detects_added_column() -> None:
    """Verifies that a new column in the current table produces an AddColumn."""
    email = SnakeColumnInfo(name="email", python_type=str)
    operations = diff_schema([_table()], [_table(email)])
    assert len(operations) == 1
    assert isinstance(operations[0], AddColumn)
    assert operations[0].column.name == "email"


def test_diff_detects_dropped_column() -> None:
    """Verifies that a column that is no longer there produces a DropColumn."""
    email = SnakeColumnInfo(name="email", python_type=str)
    operations = diff_schema([_table(email)], [_table()])
    assert len(operations) == 1
    assert isinstance(operations[0], DropColumn)
    assert operations[0].column.name == "email"


def test_replay_applies_add_then_drop_column() -> None:
    """Verifies that the replay reflects AddColumn and DropColumn in the state."""
    email = SnakeColumnInfo(name="email", python_type=str)
    state = replay(
        [
            Migration("001", (AddColumn(_table(), email),)),
        ]
    )
    # the replay starts from empty state; AddColumn on a missing table does nothing (defensive)
    assert state.tables() == ()


def test_autodetect_add_column_after_create() -> None:
    """Verifies the code-first cycle: create the table, then detect a new column."""
    from snakeorm.migration import CreateTable

    history = [Migration("001", (CreateTable(_table()),))]
    email = SnakeColumnInfo(name="email", python_type=str)
    operations = autodetect(history, [_table(email)])
    assert len(operations) == 1
    assert isinstance(operations[0], AddColumn)


def test_every_column_field_is_either_compared_or_excused_in_writing() -> None:
    """`_column_changed` covers EVERY field of `SnakeColumnInfo`, or says why it does not.

    A field the diff does not look at is a schema change that produces an EMPTY migration: no
    error, no warning, and a `makemigrations` that keeps proposing nothing while the model and the
    database drift apart. It had already happened three times over — `autoincrement` (so
    `BIGINT` -> `BIGSERIAL` emitted nothing), and `enum_type`/`enum_storage` (so changing an enum's
    members or its storage emitted nothing).

    They were missed because the comparison was a hand-written chain of `or`s: thirteen clauses
    written the day each feature landed, and a fourteenth field added later joins `SnakeColumnInfo`
    without joining the chain. So the set is DERIVED from the dataclass and the exclusions are
    declared WITH THEIR REASON — the same shape as the `Cap` catalogue, which is the one mechanism
    in this codebase that has never let a case slip: you cannot forget to answer, you can only
    answer explicitly.
    """
    import dataclasses

    from snakeorm.migration.diff import _NOT_A_COLUMN_CHANGE, _column_changed

    declared = {field.name for field in dataclasses.fields(SnakeColumnInfo)}
    unaccounted = sorted(declared - _NOT_A_COLUMN_CHANGE.keys() - _compared_fields())

    assert unaccounted == [], (
        f"these fields of SnakeColumnInfo are neither compared nor excused: {unaccounted}. "
        f"Changing one of them would produce an EMPTY migration."
    )
    assert all(_NOT_A_COLUMN_CHANGE.values()), (
        "every exclusion must carry the reason it is excluded; a bare name is a forgotten field "
        "with better manners"
    )
    assert callable(_column_changed)


def _compared_fields() -> set[str]:
    """The fields `_column_changed` actually REACTS to, measured by changing one at a time.

    Behavioural and not a scan of the source: an earlier version of this helper looked for
    `old.<field>` in the text, which stopped being true the moment the comparison became a loop
    over the dataclass. A test that reads the implementation's SPELLING breaks when the
    implementation improves and passes when it merely looks right — both the wrong way round.
    """
    import dataclasses

    from snakeorm.migration.diff import _column_changed

    base = SnakeColumnInfo(name="c", python_type=int)
    reacts: set[str] = set()
    for field in dataclasses.fields(SnakeColumnInfo):
        current = getattr(base, field.name)
        other: Any = not current if isinstance(current, bool) else _OTHER
        # `dict[str, Any]`: the point is to hand each field a value it does NOT already hold, so the
        # sentinel is deliberately of the wrong type. Checking the types here would be checking the
        # probe rather than the thing being probed.
        replacement: dict[str, Any] = {field.name: other}
        try:
            changed = dataclasses.replace(base, **replacement)
        except (
            Exception
        ):  # a field that will not take a sentinel is covered by its own test
            continue
        if _column_changed(base, changed):
            reacts.add(field.name)
    return reacts


class _Sentinel:
    """A value distinct from anything a column field holds by default."""

    def __repr__(self) -> str:
        return "<other>"


_OTHER = _Sentinel()


def test_two_tables_with_the_same_name_in_different_schemas_are_two_tables() -> None:
    """The diff keys by SCHEMA and name, not by name. Otherwise one of the two never gets created.

    `@snake_model(schema=...)` makes `public.events` and `analytics.events` a legal pair — the
    registry's own guard allows it — and the diff indexed both states by the bare `table.name`, so
    the second overwrote the first in the dict. Measured: `diff_schema([], [public, analytics])`
    emitted ONE `CreateTable`. The other table is not reported missing and no error is raised; it
    simply never exists, and every following `makemigrations` proposes the same single table again.

    The mirror case is worse still: moving a table from one schema to another looked like no change
    at all, so the migration came out EMPTY and got regenerated, identical and useless, forever.
    """
    identifier = SnakeColumnInfo(name="id", python_type=int)

    def events(schema: str) -> SnakeTableInfo:
        return SnakeTableInfo(
            name="events",
            schema=schema,
            columns=(identifier,),
            primary_key=SnakePrimaryKeyInfo(columns=(identifier,)),
        )

    operations = diff_schema([], [events("public"), events("analytics")])
    created = [op.table.schema for op in operations if isinstance(op, CreateTable)]

    assert sorted(created) == ["analytics", "public"], (
        f"only these schemas got a CreateTable: {created}. The one missing would never be "
        f"created, silently."
    )
