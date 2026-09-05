"""Tests for SnakePrimaryKeyInfo: simple and composite PK with ONE single structure.

A PK is a tuple of columns: 1 = simple, N = composite. No special cases.
"""

from __future__ import annotations

import dataclasses

import pytest

from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo


def _col(name: str) -> SnakeColumnInfo:
    """Builds a test column (str type) to assemble the keys."""
    return SnakeColumnInfo(name=name, python_type=str)


def test_single_column_is_not_composite() -> None:
    """Checks that a single-column PK is NOT considered composite."""
    pk = SnakePrimaryKeyInfo(columns=(_col("id"),))
    assert pk.is_composite is False
    assert len(pk.columns) == 1


def test_multi_column_is_composite() -> None:
    """Checks that a PK of two or more columns IS composite."""
    pk = SnakePrimaryKeyInfo(columns=(_col("code"), _col("language")))
    assert pk.is_composite is True


def test_preserves_column_order() -> None:
    """Checks that the columns keep the given order (key for the positional FK)."""
    pk = SnakePrimaryKeyInfo(columns=(_col("code"), _col("language")))
    assert [c.name for c in pk.columns] == ["code", "language"]


def test_is_frozen() -> None:
    """Checks that it is immutable: reassigning columns raises FrozenInstanceError."""
    pk = SnakePrimaryKeyInfo(columns=(_col("id"),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        pk.columns = ()  # type: ignore[misc]


def test_uses_slots() -> None:
    """Checks that it uses slots: the instance has no __dict__."""
    pk = SnakePrimaryKeyInfo(columns=(_col("id"),))
    assert not hasattr(pk, "__dict__")
