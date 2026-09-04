"""Collecting descriptors along the MRO (inheritance from abstract models).

A model inherits columns/relations from a base that is NOT a table; looking only at `vars(cls)`
would lose whatever was inherited, so the compiler, the generated `__init__` and the linker walk the
MRO with this helper.
"""

from __future__ import annotations

from typing import TypeVar

D = TypeVar("D")


def collect_inherited(cls: type, descriptor_type: type[D]) -> dict[str, D]:
    """Collects the descriptors of the given type across the whole MRO, from BASE to CHILD.

    It walks `reversed(cls.__mro__)` so that two rules fall out: the parent's columns come BEFORE
    the child's (DDL order), and if the child redefines an attribute its descriptor WINS (same key).
    """
    collected: dict[str, D] = {}
    for klass in reversed(cls.__mro__):
        for attr, value in vars(klass).items():
            if isinstance(value, descriptor_type):
                collected[attr] = value
    return collected


ABSTRACT_MARKER = "__snake_abstract__"
"""The attribute `@snake_abstract` marks a base that contributes columns and is NOT a table with."""


def is_abstract(cls: type) -> bool:
    """Is this class marked as an abstract base?

    It looks at the OWN dictionary (not `getattr`): the mark must not be inherited, or a
    `@snake_model` child would still look abstract. It lives here (and not next to the decorator) to
    avoid a cycle: `query.py` needs it and the decorators package drags in `view.py`, which imports
    `snakeorm.query`.
    """
    return cls.__dict__.get(ABSTRACT_MARKER, False) is True
