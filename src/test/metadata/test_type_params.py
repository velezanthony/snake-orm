"""Tests for `SnakeTypeParams`: the SQL parameters of a column, typed BY FAMILY.

Before, `SnakeColumnInfo` carried five flat, optional fields (`int_size`, `max_length`,
`json_storage`, `precision`, `scale`). Nothing stopped a column from carrying `max_length` AND
`precision` at the same time: the compiled graph —which is "the metadata exists ONCE and is the
truth"— admitted states no engine can represent.

With one object per family, that combination cannot even be built. And the dialect receives ONE
parameter instead of five, which closes along the way the structural hole `precision` had: it did
not go through `map_type`, it was concatenated onto the type from outside, and so nobody validated it.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDecimalParams,
    SnakeIntParams,
    SnakeIntSize,
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakeStrParams,
)


def test_each_family_carries_only_its_own_parameters() -> None:
    """Checks that each family exposes ONLY its own parameters, not those of the others."""
    assert SnakeIntParams(size=SnakeIntSize.SMALLINT).size is SnakeIntSize.SMALLINT
    assert SnakeStrParams(max_length=50).max_length == 50
    assert SnakeDecimalParams(precision=12, scale=2).scale == 2
    assert (
        SnakeJsonParams(storage=SnakeJsonStorage.JSON).storage is SnakeJsonStorage.JSON
    )
    for params in (SnakeIntParams(), SnakeStrParams(), SnakeJsonParams()):
        assert not hasattr(params, "precision")


def test_params_are_frozen_like_the_rest_of_the_graph() -> None:
    """Checks that they are immutable: they are part of the compiled graph, which never changes."""
    params = SnakeDecimalParams(precision=10, scale=2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.precision = 4  # type: ignore[misc]


def test_each_family_declares_the_python_type_it_belongs_to() -> None:
    """Checks that the family KNOWS which Python type it belongs to.

    That is what allows ONE structural guard in the compiler instead of one per knob: comparing
    `params.python_type` with the annotation covers all four, and will cover the fifth one added
    without touching the compiler. That `precision` was left without a guard was exactly the failure
    of having one hand-written guard per knob.
    """
    assert SnakeIntParams().python_type is int
    assert SnakeStrParams().python_type is str
    assert SnakeDecimalParams(precision=8).python_type is Decimal
    assert SnakeJsonParams().python_type is dict


def test_column_info_exposes_the_parameters_of_its_family() -> None:
    """Checks that `SnakeColumnInfo` is still read by knob name.

    The graph stores ONE typed object, but the ~60 places reading `column.max_length` have no reason
    to know it: the properties translate. What disappears is the possibility of WRITING an
    impossible combination.
    """
    column = SnakeColumnInfo(
        name="price", python_type=Decimal, type_params=SnakeDecimalParams(12, 2)
    )
    assert (column.precision, column.scale) == (12, 2)
    assert column.max_length is None
    assert column.json_storage is SnakeJsonStorage.JSONB


def test_a_column_without_parameters_reports_the_family_defaults() -> None:
    """Checks that without `type_params` each knob returns its usual default.

    If it diverged, a column declared with `snake_column()` would change its DDL and the migration
    diff would see it as a real change that nobody asked for.
    """
    column = SnakeColumnInfo(name="flag", python_type=bool)
    assert column.int_size is SnakeIntSize.BIGINT
    assert column.json_storage is SnakeJsonStorage.JSONB
    assert column.max_length is None
    assert (column.precision, column.scale) == (None, None)


def test_two_families_cannot_coexist_in_one_column() -> None:
    """Checks that the illegal state is UNBUILDABLE, not merely rejected.

    This is the point of the change: before, `SnakeColumnInfo(max_length=50, precision=12)` was
    built quite happily and described a column no engine can create.
    """
    with pytest.raises(TypeError):
        SnakeColumnInfo(  # type: ignore[call-arg]
            name="bad", python_type=str, max_length=50, precision=12
        )
