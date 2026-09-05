"""Tests for SnakeForeignKeyInfo: simple and composite FK with ONE single structure.

An FK is a target model + pairs (source_column, target_column): 1 pair = simple,
N pairs = composite. The join is assembled by AND-ing the pairs.
"""

from __future__ import annotations

import dataclasses

import pytest

from snakeorm.metadata import SnakeFkAction, SnakeForeignKeyInfo


def test_construction() -> None:
    """Checks that it stores the target model and the column pairs as they are."""
    fk = SnakeForeignKeyInfo(target="Country", pairs=(("country_code", "code"),))
    assert fk.target == "Country"
    assert fk.pairs == (("country_code", "code"),)


def test_single_pair_is_not_composite() -> None:
    """Checks that a single-column FK is NOT composite."""
    fk = SnakeForeignKeyInfo(target="User", pairs=(("user_id", "id"),))
    assert fk.is_composite is False


def test_multi_pair_is_composite() -> None:
    """Checks that an FK of two or more columns IS composite."""
    fk = SnakeForeignKeyInfo(
        target="Country",
        pairs=(("country_code", "code"), ("language", "language")),
    )
    assert fk.is_composite is True


def test_is_frozen() -> None:
    """Checks that it is immutable: reassigning target raises FrozenInstanceError."""
    fk = SnakeForeignKeyInfo(target="User", pairs=(("user_id", "id"),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        fk.target = "Other"  # type: ignore[misc]


def test_uses_slots() -> None:
    """Checks that it uses slots: the instance has no __dict__."""
    fk = SnakeForeignKeyInfo(target="User", pairs=(("user_id", "id"),))
    assert not hasattr(fk, "__dict__")


def test_default_fk_actions() -> None:
    """Checks that on_delete and on_update are NO_ACTION by default (the SQL default)."""
    fk = SnakeForeignKeyInfo(target="User", pairs=(("user_id", "id"),))
    assert fk.on_delete is SnakeFkAction.NO_ACTION
    assert fk.on_update is SnakeFkAction.NO_ACTION


def test_fk_actions_can_be_set() -> None:
    """Checks that actions are set with constants (ON DELETE CASCADE, ON UPDATE SET NULL)."""
    fk = SnakeForeignKeyInfo(
        target="User",
        pairs=(("user_id", "id"),),
        on_delete=SnakeFkAction.CASCADE,
        on_update=SnakeFkAction.SET_NULL,
    )
    assert fk.on_delete is SnakeFkAction.CASCADE
    assert fk.on_update is SnakeFkAction.SET_NULL


def test_action_carries_sql_fragment() -> None:
    """Checks that each action carries its SQL fragment (a constant, not a magic string)."""
    assert SnakeFkAction.SET_NULL.value == "SET NULL"
