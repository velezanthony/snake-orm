"""A relationship whose target only exists under `if TYPE_CHECKING:` links, quoted or not.

This is the layout the type-checking block was invented for, and it is what any project gets the
moment it splits its models over more than one file: `accounts` needs `Note` and `notes` needs
`Account`, so one of the two imports has to go inside the block or the package stops importing.
Measured, with both imports at runtime:

    ImportError: cannot import name 'Account' from partially initialized module

The linker called `get_type_hints(model)` bare, and that evaluates against the module's RUNTIME
globals — where a name imported only under the block never is. So it died with

    NameError: name 'Note' is not defined

which names neither the relationship, nor the model, nor anything the user typed. The only way out
was to inject the whole graph into every model module's globals by hand; `frameworks/shared/models`
does exactly that, and its own comment calls it a seam that "needs this help today".

WHY READING THE BLOCK IS THE RIGHT ANSWER AND NOT A TRICK: the ORM already does it. `through="Tagging"`
resolves through `registry/by_module.py`, which reads the very same block out of the source. Having
one half of a declaration read it and the other half not is two rules on adjacent lines — the exact
thing that module was written to end.

Quoted and unquoted are tested TOGETHER on purpose. With `from __future__ import annotations` they
are the same string by the time anything looks (PEP 563: annotations "are no longer evaluated at
function definition time... preserved in `__annotations__` in string form"), so a fix that worked for
one and not the other would mean the quotes had grown a meaning nobody intended.
"""

from __future__ import annotations

import pytest

from snakeorm.linker import snake_link
from snakeorm.metadata import SnakeRelationshipKind
from test.linker.circular_modules import accounts, circular_registry, notes


@pytest.fixture(scope="module", autouse=True)
def _linked() -> None:
    """Links the pair. Without the fix this is where it blew up, before any assertion ran."""
    snake_link(circular_registry)


@pytest.mark.parametrize(
    ("parent", "child_table"),
    [
        (accounts.Account, "circ_notes"),
        (accounts.QuotedAccount, "circ_quoted_notes"),
    ],
    ids=["unquoted", "quoted"],
)
def test_a_to_many_reaches_a_model_from_the_other_module(
    parent: type, child_table: str
) -> None:
    """THE test: the inverse side resolves across the boundary, with no globals injected anywhere."""
    table = circular_registry.table_of(parent)
    assert table is not None
    relation = next(r for r in table.relationships if r.name == "notes")

    assert relation.kind is SnakeRelationshipKind.TO_MANY
    assert relation.target_table.endswith(child_table)


@pytest.mark.parametrize(
    ("child", "parent_table"),
    [
        (notes.Note, "circ_accounts"),
        (notes.QuotedNote, "circ_quoted_accounts"),
    ],
    ids=["unquoted", "quoted"],
)
def test_a_to_one_reaches_a_model_from_the_other_module(
    child: type, parent_table: str
) -> None:
    """And the owning side too, which is the half that carries the foreign key."""
    table = circular_registry.table_of(child)
    assert table is not None
    relation = next(r for r in table.relationships if r.name == "account")

    assert relation.kind is SnakeRelationshipKind.TO_ONE
    assert relation.target_table.endswith(parent_table)


def test_neither_module_imported_the_other_at_runtime() -> None:
    """The premise, and without it the tests above prove nothing.

    If either import ever moved out of its `if TYPE_CHECKING:` block, the names would be in globals
    and `get_type_hints` would resolve them on its own — the whole file would go green over a
    question it had stopped asking. That is the vacuous-run shape this repository keeps finding, so
    the premise is asserted rather than assumed.
    """
    assert not hasattr(accounts, "Note"), (
        "`accounts` has `Note` in its globals, so this file is no longer testing a type-checking "
        "import at all"
    )
    assert not hasattr(notes, "Account"), (
        "`notes` has `Account` in its globals, so the premise is gone"
    )
