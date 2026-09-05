"""SnakeORM's public exception hierarchy.

Every exception of the ORM hangs off `SnakeError`, so that the user can catch them
without also catching the errors of their own code. Each one ALSO inherits from the
standard exception it replaces (ValueError, TypeError...), so that existing code
doing `except ValueError` keeps working.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import (
    SnakeDialectError,
    SnakeEmitError,
    SnakeError,
    SnakeModelDefinitionError,
    SnakeModelError,
    SnakeNodeError,
    SnakeRegistryError,
    SnakeRelationshipNotLoaded,
    SnakeUnknownColumn,
    SnakeUnknownRelationship,
    SnakeUnlinkedRelationship,
    SnakeUnsupportedFeature,
)


def test_root_is_exception() -> None:
    """`SnakeError` is the common root and descends from Exception."""
    assert issubclass(SnakeError, Exception)


@pytest.mark.parametrize(
    "error_type",
    [
        SnakeDialectError,
        SnakeEmitError,
        SnakeModelDefinitionError,
        SnakeModelError,
        SnakeNodeError,
        SnakeRegistryError,
        SnakeRelationshipNotLoaded,
        SnakeUnknownColumn,
        SnakeUnknownRelationship,
        SnakeUnlinkedRelationship,
        SnakeUnsupportedFeature,
    ],
)
def test_every_error_descends_from_root(error_type: type[SnakeError]) -> None:
    """Any exception of the ORM can be caught with `except SnakeError`."""
    assert issubclass(error_type, SnakeError)


@pytest.mark.parametrize(
    ("error_type", "builtin"),
    [
        (SnakeDialectError, ValueError),
        (SnakeEmitError, ValueError),
        (SnakeModelDefinitionError, ValueError),
        (SnakeModelError, TypeError),
        (SnakeNodeError, TypeError),
        (SnakeRegistryError, ValueError),
        (SnakeRelationshipNotLoaded, AttributeError),
        (SnakeUnknownColumn, ValueError),
        (SnakeUnknownRelationship, ValueError),
        (SnakeUnlinkedRelationship, RuntimeError),
        (SnakeUnsupportedFeature, ValueError),
    ],
)
def test_keeps_builtin_compatibility(
    error_type: type[SnakeError], builtin: type[Exception]
) -> None:
    """Each exception inherits from the builtin it replaces: old code does not break."""
    assert issubclass(error_type, builtin)


def test_catching_root_catches_a_subclass() -> None:
    """Catching the root catches any subclass (the user's use case)."""
    with pytest.raises(SnakeError, match="relationship 'x' does not exist"):
        raise SnakeUnknownRelationship("relationship 'x' does not exist")


def test_root_does_not_catch_foreign_errors() -> None:
    """`SnakeError` does NOT catch the errors of the user's code: that is the whole point."""
    with pytest.raises(ValueError):  # noqa: PT011 - we want the bare ValueError
        try:
            raise ValueError("a user error, not an ORM one")
        except SnakeError:  # pragma: no cover - it must not get in here
            pytest.fail("SnakeError no debería capturar un ValueError ajeno")


def test_message_is_preserved() -> None:
    """The message arrives intact at `str(exc)` (it is not lost when inheriting from two bases)."""
    error = SnakeUnknownColumn("Column 'age' does not exist in 'users'.")
    assert str(error) == "Column 'age' does not exist in 'users'."
