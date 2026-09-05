"""A model NAME means what the module that wrote it means by it.

Asking the registry's by-name index is bug #14: it is kept by whichever model registered last, so a
name shared by two apps answers about the wrong one — and it does not fail, it returns a valid answer
about a stranger's table.

Two layers, and they cover different cases:

1. The module's globals — the FORWARD DECLARATION, where the class comes later in the same file.
   `snake_link()` runs at the end, so by then the name is there. Costs the user nothing.
2. The `if TYPE_CHECKING:` block, read from the source — the REAL circular import between modules,
   where the runtime import never happens. Measured: `get_type_hints` raises `NameError` on those,
   so layer 1 genuinely cannot reach them and this is not belt-and-braces.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
from collections.abc import Iterator

import pytest

from snakeorm.registry.by_module import resolve_in_module


@pytest.fixture
def circular() -> Iterator[type]:
    """A module whose only reference to a class lives under `if TYPE_CHECKING:`.

    Written to a temporary directory rather than added to the suite as a fixture package: the point
    is a runtime import that NEVER happens, and a package the suite imports would defeat it.
    """
    directory = pathlib.Path(tempfile.mkdtemp())
    (directory / "far_side.py").write_text("class Faraway:\n    pass\n")
    (directory / "near_side.py").write_text(
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from far_side import Faraway\n"
        "class Holder:\n"
        "    pass\n"
    )
    sys.path.insert(0, str(directory))
    try:
        import near_side

        yield near_side.Holder
    finally:
        sys.path.remove(str(directory))
        for name in ("near_side", "far_side"):
            sys.modules.pop(name, None)


def test_a_name_in_the_modules_globals_resolves(circular: type) -> None:
    """The ordinary case: the class is right there in the module."""
    assert resolve_in_module(circular, "Holder") is circular


def test_a_name_only_imported_under_type_checking_resolves(circular: type) -> None:
    """The case layer 1 cannot reach, and the reason the second layer exists.

    `TYPE_CHECKING` is `False` at runtime, so the import never happens and the name is not in the
    module. Reading it from the source is the only way — and importing it HERE is safe in a way it
    was not at declaration time: the cycle that made the author write the guard is long over.
    """
    assert not hasattr(sys.modules["near_side"], "Faraway"), (
        "the fixture stopped being a real circular import: the name is in globals after all"
    )

    found = resolve_in_module(circular, "Faraway")

    assert found is not None
    assert found.__name__ == "Faraway"


def test_a_name_the_module_cannot_see_answers_nothing(circular: type) -> None:
    """`None`, so the CALLER complains — it is the one that knows what the name was for.

    Never a fallback to the global index: that is what turns a typo into a valid statement against
    somebody else's table.
    """
    assert resolve_in_module(circular, "NotAnywhere") is None
