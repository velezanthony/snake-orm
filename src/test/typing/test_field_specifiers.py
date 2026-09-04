"""Guard for the `field_specifiers`: the FOUR `@dataclass_transform` must agree.

The real problem: `SnakeModel`, `SnakeView`, `@snake_model` and `@snake_view` each declare their own
tuple of field specifiers. PEP 681 DEMANDS a literal tuple at every site —mypy rejects it with
"field_specifiers argument must be a tuple literal" if you try to pass a constant—, so the
duplication is imposed by the language and cannot be removed.

What can be done is making it impossible to drift. Adding a new specifier (`snake_enum`, for
instance) and forgetting it in one of the four produces NO error at all: that path simply stops
typing the `__init__`, silently, and only whoever declares a model over there finds out. These tests
turn that silence into a loud failure.

Precedent that the risk is real: the `@dataclass_transform` of `snake_view` hung off
`_dependency_name` (a helper returning `str`, where it did absolutely nothing) and nobody noticed,
precisely because this failure cannot be seen.
"""

from __future__ import annotations

from typing import Any

from snakeorm.decorators.view import snake_view
from snakeorm.fields import snake_column
from snakeorm.fields import SNAKE_FIELD_SPECIFIERS


# The four places where the project declares the transform, with a readable name for the failure.
def _declarations() -> list[tuple[str, object]]:
    """Every `@dataclass_transform` in the package, DISCOVERED rather than listed.

    PEP 681 marks each site at runtime with a `__dataclass_transform__` attribute, so the sites can
    be found instead of remembered — and remembering was the problem. This used to be a tuple of
    four written by hand, and the package has five: `@snake_db_first` was never in it, so it drifted
    to seven specifiers out of thirteen while every test stayed green. Scaffolded models silently
    stopped typing their `__init__`, and the scaffolder emits `snake_decimal()` among others.
    """
    import snakeorm
    from snakeorm import decorators

    found: list[tuple[str, object]] = []
    for module in (snakeorm, snakeorm.model, decorators):
        for name in dir(module):
            target = getattr(module, name)
            transform = getattr(target, "__dataclass_transform__", None)
            if transform is None or any(target is existing for _, existing in found):
                continue
            # The MODEL family, told apart by what it declares and not by a second list:
            # `snake_row`/`snake_result` are read-only row shapes, positional and with no
            # specifiers of their own, so they answer this question differently on purpose.
            if snake_column in transform["field_specifiers"]:
                found.append((f"{module.__name__}.{name}", target))
    return found


def _spec(target: object) -> dict[str, Any]:
    """The `__dataclass_transform__` PEP 681 leaves at runtime on the class or function."""
    transform = getattr(target, "__dataclass_transform__", None)
    assert isinstance(transform, dict), (
        f"{target!r} has no @dataclass_transform: without it, mypy and pyright do not type the "
        f"__init__ generated along that path."
    )
    return transform


def test_every_declaration_shares_the_same_field_specifiers() -> None:
    """EVERY `@dataclass_transform` in the package uses EXACTLY the same specifiers.

    "Every" and not "the four": the count was the bug. See `_declarations`.
    """
    for name, target in _declarations():
        assert _spec(target)["field_specifiers"] == SNAKE_FIELD_SPECIFIERS, (
            f"{name} does not match SNAKE_FIELD_SPECIFIERS. Adding a field specifier means "
            f"touching EVERY @dataclass_transform site: PEP 681 demands a literal tuple at each "
            f"one and does not take a constant. Missing: "
            f"{sorted(s.__name__ for s in SNAKE_FIELD_SPECIFIERS if s not in _spec(target)['field_specifiers'])}"
        )


def test_the_four_declarations_share_kw_only_default() -> None:
    """Checks that the four are keyword-only: a model is not built positionally."""
    for name, target in _declarations():
        assert _spec(target)["kw_only_default"] is True, f"{name} no es kw_only"


def test_snake_view_carries_the_transform_not_a_helper() -> None:
    """Checks that the view transform lives on `snake_view`, not on some random helper.

    It hung off `_dependency_name`, which takes a `type` and returns a `str`: it transformed nothing
    there. This test anchors the decorator to the right function.
    """
    from snakeorm.decorators import view

    assert not hasattr(view._dependency_name, "__dataclass_transform__")
    assert hasattr(snake_view, "__dataclass_transform__")
