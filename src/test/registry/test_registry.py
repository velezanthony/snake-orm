"""Tests for the SnakeRegistry: the store of compiled models (class → SnakeTableInfo).

@snake_model populates it as each model is defined; the linker reads it to resolve relations.
"""

from __future__ import annotations

import pytest

from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.registry import SnakeRegistry


def _table(name: str) -> SnakeTableInfo:
    """Builds a minimal test table."""
    column = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name=name,
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=(column,)),
    )


class _ModelA:
    """Test model A."""


class _ModelB:
    """Test model B."""


def test_register_and_retrieve_by_class() -> None:
    """Checks that a model is registered and its table is retrieved by the class."""
    registry = SnakeRegistry()
    registry.register(_ModelA, _table("a"))
    table = registry.table_of(_ModelA)
    assert table is not None
    assert table.name == "a"


def test_unknown_model_returns_none() -> None:
    """Checks that an unregistered model returns None."""
    assert SnakeRegistry().table_of(_ModelA) is None


def test_lists_registered_models() -> None:
    """Checks that models() lists the registered models."""
    registry = SnakeRegistry()
    registry.register(_ModelA, _table("a"))
    registry.register(_ModelB, _table("b"))
    assert set(registry.models()) == {_ModelA, _ModelB}


def test_register_overwrites_previous_table() -> None:
    """Checks that re-registering the SAME model with the same name is allowed (linker)."""
    registry = SnakeRegistry()
    registry.register(_ModelA, _table("a"))
    registry.register(_ModelA, _table("a"))
    table = registry.table_of(_ModelA)
    assert table is not None
    assert table.name == "a"


def test_collision_on_same_table_name_raises() -> None:
    """Checks the guard: two DIFFERENT models with the same table name → error."""
    registry = SnakeRegistry()
    registry.register(_ModelA, _table("brands"))
    with pytest.raises(ValueError, match="Table collision"):
        registry.register(_ModelB, _table("brands"))


def test_different_table_names_do_not_collide() -> None:
    """Checks that two models with different table names (e.g. via prefix) do not clash."""
    registry = SnakeRegistry()
    registry.register(_ModelA, _table("shop_brands"))
    registry.register(_ModelB, _table("billing_brands"))
    assert {
        t.name for t in (registry.table_of(_ModelA), registry.table_of(_ModelB)) if t
    } == {
        "shop_brands",
        "billing_brands",
    }
