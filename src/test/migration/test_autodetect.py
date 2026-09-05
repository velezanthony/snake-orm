"""Tests of the Django-style autogen: replay of migrations → state, diff vs current metadata.

The "previous state" is NOT read from the database nor from a snapshot: it is rebuilt by
applying the operations of the migrations onto a SchemaState (like Django's ProjectState).
Autodetect diffs that state against the current metadata and yields the new operations.
"""

from __future__ import annotations

from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    CreateTable,
    DropTable,
    Migration,
    autodetect,
    current_schema,
    replay,
)
from snakeorm.registry import SnakeRegistry


def _table(name: str) -> SnakeTableInfo:
    """Minimal table with the given name."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name=name, columns=(id_col,), primary_key=SnakePrimaryKeyInfo(columns=(id_col,))
    )


def test_replay_builds_state_from_operations() -> None:
    """Verifies that replaying CreateTable leaves the tables in the state."""
    state = replay(
        [Migration("001", (CreateTable(_table("a")), CreateTable(_table("b"))))]
    )
    assert {table.name for table in state.tables()} == {"a", "b"}


def test_replay_applies_drop() -> None:
    """Verifies that a later DropTable removes the table from the rebuilt state."""
    state = replay(
        [
            Migration("001", (CreateTable(_table("a")),)),
            Migration("002", (DropTable(_table("a")),)),
        ]
    )
    assert state.tables() == ()


def test_autodetect_initial_migration() -> None:
    """Verifies that with no history, autodetect proposes creating every current table."""
    operations = autodetect([], [_table("users")])
    assert len(operations) == 1
    assert isinstance(operations[0], CreateTable)


def test_autodetect_only_new_table_after_history() -> None:
    """Verifies that after a history that already created `users`, only the new table is caught."""
    history = [Migration("001", (CreateTable(_table("users")),))]
    operations = autodetect(history, [_table("users"), _table("posts")])
    assert len(operations) == 1
    assert isinstance(operations[0], CreateTable)
    assert operations[0].table.name == "posts"


def test_autodetect_detects_removed_table() -> None:
    """Verifies that a table from the history no longer in the metadata produces a DropTable."""
    history = [Migration("001", (CreateTable(_table("a")), CreateTable(_table("b"))))]
    operations = autodetect(history, [_table("a")])
    assert len(operations) == 1
    assert isinstance(operations[0], DropTable)
    assert operations[0].table.name == "b"


def test_autodetect_no_changes() -> None:
    """Verifies that if the metadata matches the history, there are no operations."""
    history = [Migration("001", (CreateTable(_table("users")),))]
    assert autodetect(history, [_table("users")]) == []


def test_current_schema_reads_registered_tables() -> None:
    """Verifies that current_schema returns the tables of the models of a registry."""

    class _Model:
        pass

    reg = SnakeRegistry()
    reg.register(_Model, _table("widgets"))
    assert [table.name for table in current_schema(reg)] == ["widgets"]
