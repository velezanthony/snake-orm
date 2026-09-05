"""A migration file that uses a name and does not import it is worth nothing, and it failed silently.

`imports_block()` filters the used names through three known sets (metadata, expressions,
operations) and writes the ones it finds. Whatever is in none of them **is not written and nothing
is said**: the file is generated whole, looking fine, and blows up with a `NameError` on import —
that is, while applying the migration, which is the worst possible moment.

It really happened. `SnakeDateTimeParams` was born with the date family and nobody put it in
`_META_CLASSES`, so ANY migration with a date column —which is nearly all of them— generated a file
that would not load. No test caught it because the render ones check the generated TEXT, and the
text was perfect: what it lacked was a line nobody was looking at.

It is closed from both sides:

1. The type parameters come from the `SnakeTypeParams` union, not from a hand-written list. A new
   family joins on its own; forgetting stops being possible.
2. A used name that falls into no set **raises**. That covers what the derivation cannot: any other
   class somebody starts rendering tomorrow.

And the check is to EXECUTE the file, not to read it. It is the same lesson already written down in
`test_render_completeness.py`: a test that measures the source code measures the source code.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import get_args

import pytest

from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDateTimeParams,
    SnakeDecimalParams,
    SnakeIntParams,
    SnakeJsonParams,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
    SnakeTypeParams,
)
from snakeorm.migration import CreateTable
from snakeorm.migration.render import _META_CLASSES, render_migration

_FAMILIES: tuple[SnakeTypeParams, ...] = (
    SnakeIntParams(),
    SnakeStrParams(max_length=20),
    SnakeDecimalParams(precision=12, scale=2),
    SnakeJsonParams(),
    SnakeDateTimeParams(tz=True),
    SnakeDateTimeParams(tz=False),
)

_TYPES: dict[str, type] = {
    "SnakeIntParams": int,
    "SnakeStrParams": str,
    "SnakeDecimalParams": Decimal,
    "SnakeJsonParams": dict,
    "SnakeDateTimeParams": datetime,
}


def _migration_with_every_family() -> str:
    """The text of a migration that creates a table with one column of EACH family."""
    pk = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    columns = [pk]
    columns.extend(
        SnakeColumnInfo(
            name=f"c{index}",
            python_type=_TYPES[type(params).__name__],
            nullable=True,
            type_params=params,
        )
        for index, params in enumerate(_FAMILIES)
    )
    table = SnakeTableInfo(
        name="todas_las_familias",
        columns=tuple(columns),
        primary_key=SnakePrimaryKeyInfo(columns=(pk,)),
    )
    return render_migration("0001_todas", [CreateTable(table)])


def test_the_rendered_migration_actually_runs() -> None:
    """Verifies that the generated file EXECUTES and rebuilds its operations.

    It is the check that was missing: the render tests looked at the text, and the text was fine —
    what was missing was an import line that no `assert "..." in source` ever felt the lack of.
    Executing it is the only thing that resolves every name.
    """
    namespace: dict[str, object] = {}

    exec(compile(_migration_with_every_family(), "<migracion>", "exec"), namespace)  # noqa: S102

    assert namespace["version"] == "0001_todas"
    assert len(namespace["operations"]) == 1  # type: ignore[arg-type]


def test_every_type_param_family_is_importable_in_a_migration() -> None:
    """Verifies that EVERY family of the union is in the imports block.

    The list comes from `SnakeTypeParams`, not from this file: a new family joins the test on its
    own, which is exactly what did not happen with the date one.
    """
    missing = [
        family.__name__
        for family in get_args(SnakeTypeParams)
        if family.__name__ not in _META_CLASSES
    ]

    assert missing == [], (
        f"families a migration can render and does not know how to import: {missing}"
    )


def test_a_name_the_renderer_cannot_import_is_reported() -> None:
    """Verifies that using a name that falls into no set RAISES, instead of quietly falling over.

    This is the general half of the fix. The derivation covers the parameter families; this covers
    whatever comes tomorrow: any class somebody starts rendering without registering ends up in a
    `NameError` when the migration is applied, and the place to find out is when generating it.
    """
    from snakeorm.migration.render import _Renderer

    renderer = _Renderer()
    renderer._used.add("SnakeClaseQueNadieRegistro")  # noqa: SLF001

    with pytest.raises(SnakeEmitError, match="SnakeClaseQueNadieRegistro"):
        renderer.imports_block()
