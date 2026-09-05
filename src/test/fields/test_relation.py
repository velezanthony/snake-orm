"""The SnakeToOne descriptor and the snake_to_one specifier (to-one relation).

Class access → type[M] (navigation/queries); instance access → the object itself (M). It keeps the
local FK columns and the referential actions (as constants, never as strings).
"""

from __future__ import annotations

from typing import Any

from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_to_one

from snakeorm.fields.relationship import attach_relationship
from snakeorm.metadata import SnakeFkAction


class User:
    """Target model for the tests."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


class Casa:
    """Model with an FK to User (no @snake_model, so the descriptor is tested in isolation)."""

    owner_id: SnakeColumn[int] = snake_int()
    owner: SnakeToOne[User] = snake_to_one(owner_id, on_delete=SnakeFkAction.CASCADE)


def _relation(name: str) -> Any:
    """Returns the raw relation descriptor."""
    return Casa.__dict__[name]


def test_instance_access_returns_related_object() -> None:
    """Instance access returns the related object that was stored.

    It is hung with `attach_relationship`: assigning the relation raises ever since `__set__`
    was closed.
    """
    house = Casa()
    user = User()
    attach_relationship(house, "owner", user)
    assert house.owner is user


def test_captures_local_fk_columns() -> None:
    """snake_to_one captures the names of the local FK columns."""
    assert _relation("owner").local_column_names() == ("owner_id",)


def test_stores_referential_actions() -> None:
    """snake_to_one stores the referential actions as constants."""
    assert _relation("owner").on_delete is SnakeFkAction.CASCADE
    assert _relation("owner").on_update is SnakeFkAction.NO_ACTION
