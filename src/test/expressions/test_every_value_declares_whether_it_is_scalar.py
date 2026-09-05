"""Every `SnakeValue` subclass says whether it may stand in a WHERE, or says why it may not.

`SnakeScalar` is the union that types the slot of a composite key, and it exists because NOTHING in
the class hierarchy separates the two kinds. `SnakeExpr`, `SnakeArith`, `SnakeCase`, `SnakeAggregate`
and `SnakeWindow` are FLAT SIBLINGS under `SnakeValue`, so without the union a `count()` reaches
`set()` past both type checkers and the engine is left to refuse it at execution time.

WHICH IS WHY IT NEEDS THIS NET. A union FAILS IN CLOSED: the day somebody adds a scalar node and
forgets to list it, the node is refused while being perfectly valid, and the error blames the caller
for writing something correct. That is the opposite failure from the one the union was built for,
and it is quieter, because nobody writes a test for an expression they were not going to use.

So the check is exhaustive BY CONSTRUCTION, in the shape this repository already uses for migration
operations: it walks the package for `SnakeValue` subclasses and demands that each appear in exactly
one of two places — the union, or the table below of values that CANNOT stand in a WHERE, with the
reason. The reason is not decoration: it is what makes adding a line a decision rather than a way to
silence the test.

The union named five members when it arrived. There are fourteen classes.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import get_args, get_origin

import pytest

import snakeorm
from snakeorm.expressions import SnakeValue
from snakeorm.expressions.keys import SnakeScalar

# Values that may NOT stand in a WHERE, each with the reason. SQL evaluates all three AFTER the row
# filter has already run, so there is nothing for them to filter on.
_NOT_SCALAR: dict[str, str] = {
    "SnakeAggregate": (
        "a bare `COUNT(x)`/`SUM(x)` folds a GROUP, and a WHERE runs before the grouping exists. "
        "Its home is HAVING. This is the one the union was written for: `Fleet.depots.count()` "
        "reads like a value and is not one at this position"
    ),
    "SnakeStringAgg": (
        "`STRING_AGG`/`GROUP_CONCAT` is an aggregate like the ones above — it just returns text, "
        "which is what makes it look assignable to a `str` slot"
    ),
    "SnakeWindow": (
        "a window function is evaluated after WHERE by definition (SQL forbids one there "
        "outright), so it cannot be part of what decides which rows survive"
    ),
}


def _every_value_class() -> dict[str, type]:
    """Every `SnakeValue` subclass in the package, found by walking it rather than by listing.

    Walking is the point. A list is a thing somebody has to remember to extend, which is the exact
    failure this file exists to make impossible.
    """
    found: dict[str, type] = {}
    for module in pkgutil.walk_packages(snakeorm.__path__, "snakeorm."):
        imported = importlib.import_module(module.name)
        for _, obj in vars(imported).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, SnakeValue)
                and obj is not SnakeValue
            ):
                found[obj.__name__] = obj
    return found


def _union_members() -> set[str]:
    """The names in the `SnakeScalar` union, read from the alias itself."""
    return {(get_origin(member) or member).__name__ for member in get_args(SnakeScalar)}


@pytest.mark.parametrize("name", sorted(_every_value_class()))
def test_a_value_is_either_in_the_union_or_declared_unusable_in_a_where(
    name: str,
) -> None:
    """Exactly one of the two places, never both and never neither.

    Parametrised per class so the failure NAMES the node somebody just added, instead of printing a
    set difference that has to be read against the source.
    """
    in_union = name in _union_members()
    declared_unusable = name in _NOT_SCALAR

    assert in_union != declared_unusable, (
        f"{name} is a SnakeValue that is {'in both' if in_union else 'in neither'} the "
        f"`SnakeScalar` union and the `_NOT_SCALAR` table. Put it in exactly one: in the union if "
        f"it may stand in a WHERE, or in the table WITH the reason it may not."
    )


def test_the_table_names_no_class_that_stopped_existing() -> None:
    """The other direction: a reason left behind after its node was renamed or removed.

    Without this the table would silently keep excusing a class nobody can write any more, and the
    day a NEW class took that name it would inherit the exemption.
    """
    stale = sorted(set(_NOT_SCALAR) - set(_every_value_class()))

    assert not stale, f"`_NOT_SCALAR` names classes that no longer exist: {stale}"


def test_every_reason_actually_says_something() -> None:
    """An empty or one-word reason is a silenced test wearing the table's clothes."""
    for name, reason in _NOT_SCALAR.items():
        assert len(reason.split()) >= 8, (
            f"the reason for {name} is too short to be a decision: {reason!r}"
        )
