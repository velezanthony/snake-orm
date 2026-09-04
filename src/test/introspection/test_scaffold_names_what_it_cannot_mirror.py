"""The scaffold validates the name it WRITES, not only the one it reads.

`_mirrors_as_class` asked `_mirrors(table.name)` — the raw database name — and `_class_name`
capitalises AFTERWARDS. So a table called `none` passed the check (`none` is not a keyword), came
out as `None`, and the generated file did not parse. `unrepresentable()` reported nothing, which
contradicts its own docstring: its whole reason to exist is that the file must not fail to parse
without a word.

Measured, five real cases and they fail three different ways:

    none / true / false   -> None / True / False   SyntaxError
    _                     -> ""                    `class (SnakeModel):`, SyntaxError
    snake_model           -> SnakeModel            IT PARSES, and that is the worst one

The last is the dangerous one. `SnakeModel` is what the generated file IMPORTS, so the mirror
shadows it and every class declared after it inherits from the mirror instead of from the base.
The file imports clean, `snake_link()` runs, and nothing anywhere says a word.

The check goes where `_to_one_refusal` already put this pattern — the neighbour that had solved it.
"""

from __future__ import annotations

import pytest

from snakeorm.introspection.models import (
    SnakeMirrorNames,
    render_models,
    unrepresentable,
)
from snakeorm.metadata import SnakePrimaryKeyInfo, SnakeTableInfo

_NAMES = SnakeMirrorNames(include_schema=False, capwords=True)


def _table(name: str) -> SnakeTableInfo:
    """A table with only its name, which is all these checks look at."""
    return SnakeTableInfo(
        name=name,
        schema="public",
        columns=(),
        primary_key=SnakePrimaryKeyInfo(columns=()),
    )


@pytest.mark.parametrize(
    "name",
    ["none", "true", "false", "_", "snake_model", "snake_column"],
)
def test_a_name_that_only_goes_wrong_once_it_is_derived_is_reported(name: str) -> None:
    """Every one of these passed the incoming check and broke the outgoing file."""
    complaints = unrepresentable([_table(name)], _NAMES)

    assert complaints, (
        f"'{name}' derives a class name that cannot be written, and the scaffold said nothing"
    )
    assert any(name in complaint for complaint in complaints), (
        "the complaint has to name the TABLE, which is the thing the user can rename"
    )


@pytest.mark.parametrize("name", ["orders", "customer", "line_items", "Nation"])
def test_an_ordinary_name_is_still_mirrored(name: str) -> None:
    """The floor: the check must not start refusing the names that work.

    Without this, "refuse what derives badly" could be implemented as "refuse everything" and every
    assertion above would be delighted.
    """
    assert unrepresentable([_table(name)], _NAMES) == []


def test_the_generated_file_parses_for_every_name_it_accepted() -> None:
    """The property behind all of the above, asked directly: what is rendered COMPILES.

    Written with `compile()` rather than by pattern-matching the output, because the failure being
    prevented is precisely a file that does not parse — and a regex over the source would have to
    guess at the same rules the renderer uses.
    """
    tables = [_table(name) for name in ("orders", "none", "snake_model", "_")]
    kept = [
        table
        for table in tables
        if not any(
            table.name in complaint for complaint in unrepresentable(tables, _NAMES)
        )
    ]

    source = render_models(kept, names=_NAMES)

    compile(source, "<scaffold>", "exec")


def test_a_mirror_never_shadows_what_the_file_imports() -> None:
    """`snake_model` derives `SnakeModel`, and that one PARSES — which is why it needs saying.

    A file where the mirror shadows the base class imports cleanly and links cleanly, and every
    class after it silently inherits from the wrong thing. It is the only one of the five that a
    "does it compile?" test cannot catch.
    """
    complaints = unrepresentable([_table("snake_model")], _NAMES)

    assert complaints
    assert "SnakeModel" in complaints[0], (
        "the complaint has to name the collision, or the reader cannot tell what is wrong with a "
        "class name that looks perfectly fine"
    )
