"""Tests for SnakeTableInfo: the compiled model, root node of the graph.

It aggregates name, columns, primary key and relations. The whole ORM reads from here.
"""

from __future__ import annotations

import dataclasses

import pytest

from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo


def _id_column() -> SnakeColumnInfo:
    """Test PK column (id: int)."""
    return SnakeColumnInfo(name="id", python_type=int)


def _table() -> SnakeTableInfo:
    """Minimal test table with a simple PK over 'id'."""
    id_col = _id_column()
    return SnakeTableInfo(
        name="users",
        columns=(id_col,),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def test_construction() -> None:
    """Checks that it stores name, columns and primary key."""
    table = _table()
    assert table.name == "users"
    assert len(table.columns) == 1
    assert table.primary_key.is_composite is False


def test_defaults() -> None:
    """Checks the defaults: no relations and schema 'public'."""
    table = _table()
    assert table.relationships == ()
    assert table.schema == "public"


def test_get_column_found() -> None:
    """Checks that get_column returns the column when it exists."""
    column = _table().get_column("id")
    assert column is not None
    assert column.name == "id"


def test_get_column_missing_returns_none() -> None:
    """Checks that get_column returns None when the column does not exist."""
    assert _table().get_column("nope") is None


def test_is_frozen() -> None:
    """Checks that it is immutable: reassigning name raises FrozenInstanceError."""
    table = _table()
    with pytest.raises(dataclasses.FrozenInstanceError):
        table.name = "other"  # type: ignore[misc]


def test_uses_slots() -> None:
    """Checks that it uses slots: the instance has no __dict__."""
    assert not hasattr(_table(), "__dict__")


def test_db_comment_default_is_none() -> None:
    """Checks that the table db_comment is None by default."""
    assert _table().db_comment is None


def test_db_comment_can_be_set() -> None:
    """Checks that an SQL table comment can be set (COMMENT ON TABLE)."""
    id_col = _id_column()
    table = SnakeTableInfo(
        name="users",
        columns=(id_col,),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
        db_comment="system users",
    )
    assert table.db_comment == "system users"
