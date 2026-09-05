"""Tests of the diff engine (autodetection): two schema states → operations.

The heart of code-first: it compares the PREVIOUS state against the CURRENT one (metadata) and
derives the operations. Slice 1: created tables (CreateTable) and dropped ones (DropTable). The
column-level diff arrives with the AddColumn/DropColumn operations.
"""

from __future__ import annotations

from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import CreateTable, DropTable, diff_schema


def _table(name: str) -> SnakeTableInfo:
    """Minimal test table with the given name."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name=name, columns=(id_col,), primary_key=SnakePrimaryKeyInfo(columns=(id_col,))
    )


def test_new_table_yields_create() -> None:
    """Verifies that a table present only in the current state produces a CreateTable."""
    operations = diff_schema([], [_table("users")])
    assert len(operations) == 1
    assert isinstance(operations[0], CreateTable)
    assert operations[0].table.name == "users"


def test_removed_table_yields_drop() -> None:
    """Verifies that a table that is no longer there produces a DropTable."""
    operations = diff_schema([_table("legacy")], [])
    assert len(operations) == 1
    assert isinstance(operations[0], DropTable)
    assert operations[0].table.name == "legacy"


def test_unchanged_table_yields_nothing() -> None:
    """Verifies that a table present in both states produces no operations (slice 1)."""
    assert diff_schema([_table("users")], [_table("users")]) == []


def test_mixed_creates_and_drops_are_deterministic() -> None:
    """Verifies created + dropped together, in deterministic order (creates before drops)."""
    operations = diff_schema([_table("a"), _table("b")], [_table("b"), _table("c")])
    assert len(operations) == 2
    create, drop = operations
    assert isinstance(create, CreateTable) and create.table.name == "c"
    assert isinstance(drop, DropTable) and drop.table.name == "a"
