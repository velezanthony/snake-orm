"""@snake_result: it compiles a typed result container and validates its shape.

The decorator turns a class of ordinary annotations into a dataclass (so `dataclass_transform`
types its `__init__`), separates the base row (a @snake_model) from the scalars, and fails at
decoration time if the shape is ambiguous (two models) or empty (no base row at all).
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import SnakeResult, snake_model, snake_result
from snakeorm.decorators.result import snake_result_info
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel


@snake_model(table="result_realms")
class _ResultRealm(SnakeModel):
    """Test model: the base row of a @snake_result."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="result_forges")
class _ResultForge(SnakeModel):
    """Another model, to prove the generic parameter has to match the base field."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_result
class _RealmStats(SnakeResult[_ResultRealm]):
    """Typed container: the base row plus two scalars."""

    realm: _ResultRealm
    forge_count: int
    avg_size: float


def test_result_is_constructible_with_base_and_scalars() -> None:
    """@snake_result generates an __init__ accepting the base row and the scalars (dataclass)."""
    realm = _ResultRealm(id=1, name="Nornia")
    stats = _RealmStats(realm=realm, forge_count=3, avg_size=2.5)
    assert stats.realm is realm
    assert stats.forge_count == 3
    assert stats.avg_size == 2.5


def test_result_stores_compiled_metadata() -> None:
    """It keeps the base row and the (name, type) list of scalars, in declaration order."""
    info = snake_result_info(_RealmStats)
    assert info.base_field == "realm"
    assert info.base_model is _ResultRealm
    assert info.scalars == (("forge_count", int), ("avg_size", float))


def test_two_base_models_is_rejected() -> None:
    """Two base models is ambiguous: it fails at decoration time with SnakeModelDefinitionError."""
    with pytest.raises(SnakeModelDefinitionError, match="declares 2 base models"):

        @snake_result
        class _TwoBases(SnakeResult[_ResultRealm]):
            first: _ResultRealm
            second: _ResultRealm
            forge_count: int


def test_no_base_model_is_rejected() -> None:
    """With no base model at all (only aggregates) there is no row to annotate: it fails."""
    with pytest.raises(
        SnakeModelDefinitionError, match="declares not a single base model"
    ):

        @snake_result
        class _NoBase(SnakeResult[_ResultRealm]):
            forge_count: int
            avg_size: float


def test_non_result_class_has_no_info() -> None:
    """snake_result_info over a class that is not a @snake_result fails loudly."""
    with pytest.raises(SnakeModelDefinitionError, match="is not a @snake_result"):
        snake_result_info(_ResultRealm)


def test_class_without_snakeresult_base_is_rejected() -> None:
    """A result class that does not inherit from SnakeResult[Model] fails loudly at decoration."""
    with pytest.raises(
        SnakeModelDefinitionError, match="does not inherit from SnakeResult"
    ):

        @snake_result
        class _NoBaseClass:  # does not inherit SnakeResult
            realm: _ResultRealm
            forge_count: int


def test_bare_snakeresult_base_is_rejected() -> None:
    """Inheriting from a bare SnakeResult (no model) fails too: the base type is missing."""
    with pytest.raises(
        SnakeModelDefinitionError, match="inherits SnakeResult without the base model"
    ):

        @snake_result
        class _BareBase(SnakeResult):  # type: ignore[type-arg]  # SnakeResult[Model] is missing
            realm: _ResultRealm
            forge_count: int


def test_generic_parameter_must_match_base_field() -> None:
    """The generic parameter SnakeResult[X] must match the model of the declared base field."""
    with pytest.raises(SnakeModelDefinitionError, match="they do not match"):

        @snake_result
        class _Mismatched(SnakeResult[_ResultForge]):  # parameter _ResultForge...
            realm: _ResultRealm  # ...but the base field is _ResultRealm
            forge_count: int
