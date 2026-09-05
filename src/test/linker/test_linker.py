"""Tests for the Linker (Phase 2): it resolves relations and pins them into the graph.

The target comes from the annotation; the FK pairs map the local columns to the
target PK, by position.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model, snake_table
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_to_one

from snakeorm.linker import snake_link
from snakeorm.metadata import SnakeFkAction, SnakeRelationshipKind
from snakeorm.model import SnakeModel


@snake_model(prefix="lk")
class Owner(SnakeModel):
    """Target model of the relation."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_model
class House(SnakeModel):
    """Model with an FK to Owner."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    owner_id: SnakeColumn[int] = snake_int()
    owner: SnakeToOne[Owner] = snake_to_one(owner_id, on_delete=SnakeFkAction.CASCADE)


def test_relationship_resolved() -> None:
    """Checks that the linker builds the relation with the right name, target and kind."""
    snake_link()
    relationships = snake_table(House).relationships
    assert len(relationships) == 1
    assert relationships[0].name == "owner"
    assert relationships[0].target == "Owner"
    assert relationships[0].kind is SnakeRelationshipKind.TO_ONE


def test_fk_pairs_mapped_to_target_pk() -> None:
    """Checks that the FK pairs map the local column to the target PK."""
    snake_link()
    foreign_key = snake_table(House).relationships[0].foreign_key
    assert foreign_key.pairs == (("owner_id", "id"),)
    assert foreign_key.on_delete is SnakeFkAction.CASCADE


def test_model_without_relations_stays_empty() -> None:
    """Checks that a model without relations is left with empty relationships."""
    snake_link()
    assert snake_table(Owner).relationships == ()
