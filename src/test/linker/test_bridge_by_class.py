"""`snake_to_many_through(through=...)` accepts the bridge CLASS, not only its name.

The linker's own docstring says the m2m is resolved there "because here the classes are right in
front of us; storing names and looking them up again produced bug #14". That is true of the target
and FALSE of the bridge: `through=` took a `str`, and the linker resolved it with
`reg.model_by_name(...)` — the index `register()` overwrites in silence, which is precisely the
index bug #14 was about.

The consequence is worse than the JOIN one, because the metadata is compiled ONCE: the wrong bridge
ends up frozen inside `SnakeThroughInfo`, and since the `via`/`to` pair usually matches on both
homonyms, the SELECT comes out valid and reads the table that is not.

The string stays, and stays the normal way to write it: the bridge is usually declared AFTER the
model that points through it, so there is no class to hand over yet. The class is the escape hatch
for whoever has two bridges with one name — which is the situation the collision guard's own message
tells you to create with `prefix=`.

`bridge_cls = reg.model_by_name(...)` was also DEAD: it asked the ambiguous index and used the
answer for nothing but a `None` check.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.linker import snake_link
from snakeorm.registry import SnakeRegistry
from test.linker.bridge_apps import bridge_registry, catalogue

_REG: SnakeRegistry = bridge_registry


def test_a_bridge_given_as_a_class_resolves_to_its_own_table() -> None:
    """The class is unambiguous by construction: there is no name to look up.

    `catalogue.Tagging` and `archive.Tagging` share a class name and have different tables. The
    by-name index keeps whichever registered last, so the string form used to hand the linker the
    wrong one and freeze it into the compiled metadata.
    """
    snake_link(_REG)

    table = _REG.table_of(catalogue.Post)
    assert table is not None
    relation = next(r for r in table.relationships if r.name == "tags")

    assert relation.through is not None
    assert relation.through.table.endswith("br_cat_taggings"), (
        "the m2m crossed the wrong bridge: it resolved `through` by class NAME"
    )


def test_the_class_name_really_is_ambiguous_here() -> None:
    """The floor under the test above: without two homonyms it proves nothing.

    A fixture that quietly stopped having a collision would leave the test green over a question it
    is no longer asking, which is the failure mode this whole audit keeps finding.
    """
    from test.linker.bridge_apps import archive

    assert catalogue.Tagging.__name__ == archive.Tagging.__name__
    assert _REG.table_of(catalogue.Tagging) is not _REG.table_of(archive.Tagging)


def test_an_unregistered_bridge_still_says_so() -> None:
    """The error path keeps working, and it names what the USER wrote.

    Not `bridge_table.name`: somebody who wrote `through="Nope"` is looking for that word, and a
    message naming a table they never typed sends them hunting. The string form has to keep failing
    exactly as before — widening `through=` to accept a class must not soften what it says about a
    name that resolves to nothing.
    """
    from test.linker.bridge_apps import broken

    with pytest.raises(SnakeRegistryError, match="Nope"):
        snake_link(broken.broken_registry)
