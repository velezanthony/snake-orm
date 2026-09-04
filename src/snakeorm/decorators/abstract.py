"""`@snake_abstract`: a base that contributes columns and is NOT a table.

It does not change the behaviour (inheritance already works via `collect_inherited`): it only
DECLARES that the class is a base, so that using it as a table gives a useful error instead of the
generic "is @snake_model missing?".
"""

from __future__ import annotations

from typing import TypeVar

from snakeorm.helpers.inheritance import ABSTRACT_MARKER as _BRAND
from snakeorm.helpers.inheritance import is_abstract as is_abstract

T = TypeVar("T")


def snake_abstract(cls: type[T]) -> type[T]:
    """Mark a class as an abstract BASE: it contributes columns to its children, and is no table.

    Each child gets the base's columns IN ITS OWN TABLE; the base never shows up in migrations (it
    is not registered). If the child redefines an attribute, the child's wins. There is no
    parametric form: there is nothing to configure.
    """
    setattr(cls, _BRAND, True)
    return cls
