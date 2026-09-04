"""Migrations of VIEWS: CreateView / DropView / AlterView, their diff and their render round-trip.

A view is created AFTER the tables (it depends on them) and emits neither FKs nor columns: if its
definition changes it is REPLACED whole (AlterView). The diff detects a new view (CreateView), a
dropped one (DropView) and one with a changed definition (AlterView); views are not mixed into the
column diff of the tables. The render of the three operations round-trips (identical up/down).
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTableKind,
)
from snakeorm.migration import (
    AlterView,
    CreateView,
    DropView,
    Migration,
    SchemaState,
    SnakeMigrationOperation,
    SnakeOperation,
    diff_schema,
    emit_create_view,
    render_migration,
)


def _view(name: str, definition: str) -> SnakeTableInfo:
    """Minimal view (one column) with the given definition, of kind VIEW."""
    column = SnakeColumnInfo(name="user_id", python_type=int)
    return SnakeTableInfo(
        name=name,
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=()),
        kind=SnakeTableKind.VIEW,
        view_definition=definition,
    )


def _table(name: str) -> SnakeTableInfo:
    """Minimal real table (for the table → view order)."""
    column = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name=name, columns=(column,), primary_key=SnakePrimaryKeyInfo(columns=(column,))
    )


_DIALECT = PostgresDialect()


def test_create_view_up_and_down() -> None:
    """CreateView emits `CREATE VIEW ... AS <def>` and its reverse `DROP VIEW`."""
    op = CreateView(_view("user_classes", "SELECT user_id FROM enrollments"))
    assert op.up_sql(_DIALECT) == [
        'CREATE VIEW "public"."user_classes" AS SELECT user_id FROM enrollments'
    ]
    assert op.down_sql(_DIALECT) == ['DROP VIEW "public"."user_classes"']


def test_drop_view_up_and_down() -> None:
    """DropView emits `DROP VIEW` and its reverse recreates the view with its original def."""
    op = DropView(_view("user_classes", "SELECT user_id FROM enrollments"))
    assert op.up_sql(_DIALECT) == ['DROP VIEW "public"."user_classes"']
    assert op.down_sql(_DIALECT) == [
        'CREATE VIEW "public"."user_classes" AS SELECT user_id FROM enrollments'
    ]


def test_alter_view_replaces_the_definition() -> None:
    """AlterView emits `CREATE OR REPLACE VIEW` with the new def; its reverse restores the old."""
    old = _view("user_classes", "SELECT user_id FROM enrollments")
    new = _view("user_classes", "SELECT user_id, class_id FROM enrollments")
    op = AlterView(old, new)
    assert op.up_sql(_DIALECT) == [
        'CREATE OR REPLACE VIEW "public"."user_classes" AS '
        "SELECT user_id, class_id FROM enrollments"
    ]
    assert op.down_sql(_DIALECT) == [
        'CREATE OR REPLACE VIEW "public"."user_classes" AS SELECT user_id FROM enrollments'
    ]


def test_view_operations_mutate_the_state() -> None:
    """apply_to_state adds/removes/replaces the view in the state, marked as a view."""
    state = SchemaState()
    CreateView(_view("v", "SELECT 1")).apply_to_state(state)
    stored = state.get_table("v")
    assert (
        stored is not None
        and stored.is_view is True
        and stored.view_definition == "SELECT 1"
    )

    AlterView(_view("v", "SELECT 1"), _view("v", "SELECT 2")).apply_to_state(state)
    assert state.get_table("v").view_definition == "SELECT 2"  # type: ignore[union-attr]

    DropView(_view("v", "SELECT 2")).apply_to_state(state)
    assert state.get_table("v") is None


def test_diff_detects_a_new_view() -> None:
    """A view that was not in the previous state produces a CreateView."""
    operations = diff_schema([], [_view("v", "SELECT 1")])
    assert len(operations) == 1
    assert isinstance(operations[0], CreateView)
    assert operations[0].view.name == "v"


def test_diff_detects_a_removed_view() -> None:
    """A view from the previous state that is no longer there produces a DropView."""
    operations = diff_schema([_view("v", "SELECT 1")], [])
    assert len(operations) == 1
    assert isinstance(operations[0], DropView)


def test_diff_detects_a_changed_definition() -> None:
    """A view whose definition changed produces an AlterView (replaced whole, not by columns)."""
    operations = diff_schema([_view("v", "SELECT 1")], [_view("v", "SELECT 2")])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterView)
    assert operations[0].new.view_definition == "SELECT 2"


def test_diff_no_change_for_identical_view() -> None:
    """An identical view (same definition) produces no operation at all (it converges)."""
    assert diff_schema([_view("v", "SELECT 1")], [_view("v", "SELECT 1")]) == []


def test_views_are_created_after_tables() -> None:
    """The diff emits the tables BEFORE the views (a view depends on its tables)."""
    operations = diff_schema([], [_view("v", "SELECT * FROM t"), _table("t")])
    kinds = [type(op).__name__ for op in operations]
    assert kinds.index("CreateTable") < kinds.index("CreateView")


def _reconstruct(source: str) -> list[SnakeMigrationOperation]:
    """Executes the generated code in a clean namespace and returns its operations."""
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated-migration>", "exec"), namespace)  # noqa: S102
    migration = namespace["migration"]
    assert isinstance(migration, Migration)
    return list(migration.operations)


def _sql(
    operations: Sequence[SnakeMigrationOperation],
) -> list[tuple[list[str], list[str]]]:
    """The SQL signature (up/down) of each operation: what the round-trip must preserve."""
    signatures: list[tuple[list[str], list[str]]] = []
    for op in operations:
        assert isinstance(op, SnakeOperation)
        signatures.append((op.up_sql(_DIALECT), op.down_sql(_DIALECT)))
    return signatures


def test_render_round_trip_of_view_operations() -> None:
    """Render of CreateView/AlterView/DropView: re-running produces the SAME up/down SQL."""
    operations: list[SnakeOperation] = [
        CreateView(_view("v1", "SELECT a FROM t")),
        AlterView(_view("v1", "SELECT a FROM t"), _view("v1", "SELECT a, b FROM t")),
        DropView(_view("v2", "SELECT c FROM t")),
    ]
    source = render_migration("003", operations)
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_emit_create_view_standalone() -> None:
    """The DDL emitter `emit_create_view` generates the qualified CREATE VIEW."""
    ddl = emit_create_view(
        _view("user_classes", "SELECT user_id FROM enrollments"), _DIALECT
    )
    assert (
        ddl == 'CREATE VIEW "public"."user_classes" AS SELECT user_id FROM enrollments'
    )
