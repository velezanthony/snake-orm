"""Tests for SnakeColumnInfo: immutable metadata of a column.

The type comes from Python (`python_type`); everything else only adds SQL info.
"""

from __future__ import annotations

import dataclasses

import pytest

from snakeorm.metadata import SnakeColumnInfo


def test_minimal_construction() -> None:
    """Checks that it is built with a name and a type, and exposes them as they are."""
    col = SnakeColumnInfo(name="id", python_type=int)
    assert col.name == "id"
    assert col.python_type is int


def test_default_values() -> None:
    """Checks the default values: NOT NULL, not unique, no default, no index."""
    col = SnakeColumnInfo(name="id", python_type=int)
    assert col.nullable is False
    assert col.unique is False
    assert col.default is None
    assert col.index is False


def test_is_frozen() -> None:
    """Checks that it is immutable: reassigning a field raises FrozenInstanceError."""
    col = SnakeColumnInfo(name="id", python_type=int)
    with pytest.raises(dataclasses.FrozenInstanceError):
        col.name = "other"  # type: ignore[misc]


def test_uses_slots() -> None:
    """Checks that it uses slots: the instance has no __dict__ (memory and rigidity)."""
    col = SnakeColumnInfo(name="id", python_type=int)
    assert not hasattr(col, "__dict__")


def test_equality_by_value() -> None:
    """Checks that two columns with the same values are equal (frozen dataclass)."""
    a = SnakeColumnInfo(name="id", python_type=int, unique=True)
    b = SnakeColumnInfo(name="id", python_type=int, unique=True)
    assert a == b


def test_db_comment_default_is_none() -> None:
    """Checks that db_comment is None by default (a column with no SQL comment)."""
    col = SnakeColumnInfo(name="id", python_type=int)
    assert col.db_comment is None


def test_db_comment_can_be_set() -> None:
    """Checks that an SQL column comment can be set (COMMENT ON COLUMN)."""
    col = SnakeColumnInfo(name="id", python_type=int, db_comment="clave primaria")
    assert col.db_comment == "clave primaria"
