"""Tests for SnakeRelationshipInfo: the navigation view over an FK.

`kind` tells to_one (returns M) apart from to_many (inverse relation, list[M]).
"""

from __future__ import annotations

import dataclasses

import pytest

from snakeorm.metadata import (
    SnakeForeignKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
)


def _fk() -> SnakeForeignKeyInfo:
    """Test FK (owner_id -> User.id) to back the relation."""
    return SnakeForeignKeyInfo(target="User", pairs=(("owner_id", "id"),))


def test_construction() -> None:
    """Checks that it stores name, target, kind and the FK backing it."""
    rel = SnakeRelationshipInfo(
        name="owner",
        target="User",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=_fk(),
    )
    assert rel.name == "owner"
    assert rel.target == "User"
    assert rel.kind is SnakeRelationshipKind.TO_ONE
    assert rel.foreign_key == _fk()


def test_supports_to_many_kind() -> None:
    """Checks that it supports the to_many kind (inverse relation returning list[M])."""
    rel = SnakeRelationshipInfo(
        name="cities",
        target="City",
        kind=SnakeRelationshipKind.TO_MANY,
        foreign_key=_fk(),
    )
    assert rel.kind is SnakeRelationshipKind.TO_MANY


def test_is_frozen() -> None:
    """Checks that it is immutable: reassigning name raises FrozenInstanceError."""
    rel = SnakeRelationshipInfo(
        name="owner",
        target="User",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=_fk(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rel.name = "other"  # type: ignore[misc]


def test_uses_slots() -> None:
    """Checks that it uses slots: the instance has no __dict__."""
    rel = SnakeRelationshipInfo(
        name="owner",
        target="User",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=_fk(),
    )
    assert not hasattr(rel, "__dict__")
