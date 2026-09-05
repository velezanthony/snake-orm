"""JSONB and arrays: the two Postgres types a real project starts missing right away.

`dict` → `JSONB` (not `JSON`): jsonb is indexed, normalized and it is what 99% of the cases want;
`json` stores the text as is and is only useful if you need to preserve the original formatting.

Arrays carried the risk the roadmap had written down: `list[int]` is NOT a `type`, it is a generic
alias, and `map_type` assumed it received classes. It is solved by looking at the alias's origin and
argument instead of looking it up in the dictionary.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeDialectError

_DIALECT = PostgresDialect()


def test_a_dict_maps_to_jsonb() -> None:
    """Verifies that a `dict` is JSONB, not JSON: indexable and normalized."""
    assert _DIALECT.map_type(dict) == "JSONB"


def test_a_list_of_scalars_maps_to_an_array_of_its_element() -> None:
    """Verifies that the array preserves its element's type (the generic alias risk)."""
    # BIGINT[], not INTEGER[]: the `int` element inherits the default width (the widest one).
    assert _DIALECT.map_type(list[int]) == "BIGINT[]"
    assert _DIALECT.map_type(list[str]) == "TEXT[]"
    assert _DIALECT.map_type(list[Decimal]) == "NUMERIC[]"


def test_a_nested_list_maps_to_a_multidimensional_array() -> None:
    """Verifies that an array of arrays does not give up: Postgres accepts multidimensional ones."""
    assert _DIALECT.map_type(list[list[int]]) == "BIGINT[][]"


def test_a_bare_list_is_refused() -> None:
    """Verifies that a `list` WITHOUT an element type is refused: there is no untyped array in SQL.

    Guessing `TEXT[]` would be exactly the kind of silent assumption this project avoids.
    """
    with pytest.raises(SnakeDialectError, match="does not declare its element type"):
        _DIALECT.map_type(list)


def test_a_list_of_something_unmappable_is_refused() -> None:
    """Verifies that the element's error surfaces, instead of a made-up array."""

    class Weird:
        """A type the dialect does not know."""

    with pytest.raises(
        SnakeDialectError,
        match="If it is a type of your own, or a Postgres one the ORM does",
    ):
        _DIALECT.map_type(list[Weird])
