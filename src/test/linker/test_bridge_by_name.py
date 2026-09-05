"""`through="Tagging"` resolves in the module that DECLARED it, not in a global name index.

The class form of `through=` was fixed when the bridge learned to take a class. The STRING form was
left going through `registry.table_by_name` — the index `register()` overwrites in silence — and the
string is the USUAL form, because a bridge is normally declared after the model that crosses it.

Measured before the fix, with two apps each declaring their own `Tagging`:

    catalogue (bn_cat) -> bridge resolved: public.bn_arc_taggings
    archive   (bn_arc) -> bridge resolved: public.bn_arc_taggings

Both cross through the same one. The SELECT comes out valid, because the `via`/`to` pair matches on
both bridges, so half the application reads the wrong table and nothing says a word. And the FK does
not fail either: both tables exist —the ORM manages them— so the `ALTER TABLE ... REFERENCES` is
applied without complaint and leaves referential integrity pointing at the wrong table. That is
`test_model_name_collision.py`'s own account of bug #14, happening again in the half the class fix
did not reach.

WHY THE MODULE IS THE RIGHT ANSWER, and it is not a new mechanism: the ANNOTATION half of the very
same declaration already resolves that way. `SnakeToOne["Post"]` goes through `get_type_hints`,
which evaluates against the MODULE's globals, so each file resolves its own `Post`. Two rules for
one thing, on adjacent lines — with only one of them correct.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.linker import snake_link
from test.linker.bridge_by_name import archive, bridge_registry, catalogue


@pytest.fixture(autouse=True)
def _linked() -> None:
    """The two apps linked in their own registry."""
    snake_link(bridge_registry)


@pytest.mark.parametrize(
    ("app", "table"),
    [(catalogue, "bn_cat_taggings"), (archive, "bn_arc_taggings")],
    ids=["catalogue", "archive"],
)
def test_each_app_crosses_its_own_bridge(app: object, table: str) -> None:
    """THE test. Each `Post` reaches the `Tagging` of ITS module, not whichever registered last."""
    compiled = bridge_registry.table_of(app.Post)  # type: ignore[attr-defined]
    assert compiled is not None
    relation = next(r for r in compiled.relationships if r.name == "tags")

    assert relation.through is not None
    assert relation.through.table.endswith(table), (
        f"crossed {relation.through.table} instead of {table}: the name was resolved through the "
        f"global by-name index instead of the module that wrote it"
    )


def test_the_two_bridges_really_are_homonyms() -> None:
    """The floor: without two classes called `Tagging` the test above proves nothing.

    A fixture that quietly stopped colliding would leave it green over a question it is no longer
    asking — which is the failure this whole audit keeps finding.
    """
    assert catalogue.Tagging.__name__ == archive.Tagging.__name__
    assert bridge_registry.table_of(catalogue.Tagging) is not bridge_registry.table_of(
        archive.Tagging
    )


def test_a_name_the_module_cannot_see_is_refused() -> None:
    """A bridge nobody declared blows up naming it — it never falls back to a global lookup.

    Failing closed is the whole point: the old behaviour took whatever the global index happened to
    hold, which is how a valid `ALTER` ends up pointing at a stranger's table.
    """
    from test.linker.bridge_by_name import missing

    with pytest.raises(SnakeRegistryError, match="Nope"):
        snake_link(missing.orphan_registry)
