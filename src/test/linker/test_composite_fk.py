"""Tests for the linker validation of POSITIONAL pairing in a composite FK.

`snake_to_one(col_a, col_b)` maps its columns to the target PK BY POSITION. If the user passes them
in the wrong order, the mapping would come out crossed in silence. The linker catches it loudly:
(1) the number of local columns must equal that of the target PK; (2) the Python types must match
pair by pair. The correct case produces the expected `pairs`.

The models do NOT carry @snake_model (they must not pollute the global registry, which uses
`snake_link()` across the whole suite): they are compiled by hand and registered in a local
`SnakeRegistry` on which `_to_one_relationships` is invoked directly.
"""

from __future__ import annotations

import pytest

from snakeorm.compiler import compile_model
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_str, snake_to_one

from snakeorm.linker.linker import _to_one_relationships
from snakeorm.registry import SnakeRegistry


class Parent:
    """Target with a COMPOSITE PK (region: str, code: int), in that order."""

    region: SnakeColumn[str] = snake_str(primary_key=True)
    code: SnakeColumn[int] = snake_int(primary_key=True)


class ChildOk:
    """Child with a composite FK in the correct ORDER: (p_region → region, p_code → code)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    p_region: SnakeColumn[str] = snake_str()
    p_code: SnakeColumn[int] = snake_int()
    parent: SnakeToOne[Parent] = snake_to_one(p_region, p_code)


class ChildSwapped:
    """Child with the FK columns in the wrong ORDER: (p_code → region, p_region → code)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    p_region: SnakeColumn[str] = snake_str()
    p_code: SnakeColumn[int] = snake_int()
    parent: SnakeToOne[Parent] = snake_to_one(p_code, p_region)


class ChildTooFew:
    """Child with FEWER FK columns than the target PK has columns (1 against 2)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    p_region: SnakeColumn[str] = snake_str()
    parent: SnakeToOne[Parent] = snake_to_one(p_region)


def _registry_with(*models: type) -> SnakeRegistry:
    """Compiles and registers the given models in a LOCAL registry (isolated from the global)."""
    reg = SnakeRegistry()
    for model in models:
        reg.register(model, compile_model(model))
    return reg


def test_correct_order_produces_expected_pairs() -> None:
    """The correct order produces the pairs (p_region→region, p_code→code), by position."""
    reg = _registry_with(Parent, ChildOk)
    relationships = _to_one_relationships(ChildOk, reg)
    assert len(relationships) == 1
    assert relationships[0].foreign_key.pairs == (
        ("p_region", "region"),
        ("p_code", "code"),
    )
    assert relationships[0].foreign_key.is_composite is True


def test_swapped_order_is_caught_by_type_mismatch() -> None:
    """The crossed order matches p_code (int) with region (str): SnakeModelDefinitionError by types."""
    reg = _registry_with(Parent, ChildSwapped)
    with pytest.raises(SnakeModelDefinitionError) as excinfo:
        _to_one_relationships(ChildSwapped, reg)
    message = str(excinfo.value)
    assert "p_code" in message and "region" in message
    assert "int" in message and "str" in message
    assert "snake_to_one" in message  # points at the fix: the ORDER of the arguments


def test_wrong_number_of_columns_is_caught() -> None:
    """Fewer FK columns than the target PK: SnakeModelDefinitionError with the count, not a bare zip."""
    reg = _registry_with(Parent, ChildTooFew)
    with pytest.raises(SnakeModelDefinitionError) as excinfo:
        _to_one_relationships(ChildTooFew, reg)
    message = str(excinfo.value)
    assert "1" in message and "2" in message  # 1 local column against 2 of the PK
    assert "snake_to_one" in message
