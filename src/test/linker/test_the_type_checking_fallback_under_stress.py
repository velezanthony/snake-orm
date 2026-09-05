"""The type-checking fallback pushed at the places it can plausibly come apart.

`hints_of` reads a module's `if TYPE_CHECKING:` block out of the SOURCE when `get_type_hints` cannot
resolve a name. Reading source instead of evaluating it means every way the block can legitimately
be WRITTEN is a way the reader can legitimately miss it — and missing it does not raise here, it
falls through to the same `NameError` the fallback exists to prevent. So each of these is a
fail-in-the-open shape, which is the kind this repository keeps finding and the kind a test has to
pin down one spelling at a time.

The homonym case is not one more spelling: it is the whole reason the block is read at all. A class
NAME does not identify a model — two apps can each declare an `Item`, and the registry's by-name
index is kept by whichever registered LAST, silently. The block carries the module PATH the author
wrote, and that is an identity. Resolving these two `Item`s to one class would be bug #14 arriving
through the new door.
"""

from __future__ import annotations

import pytest

from snakeorm.linker import snake_link
from snakeorm.metadata import SnakeRelationshipKind
from test.linker.circular_stress import (
    crm_registry,
    shop_registry,
    stress_registry,
    three_registry,
)


@pytest.fixture(scope="module", autouse=True)
def _linked() -> None:
    """Links all four graphs. Any unresolved name blows up here, before a single assertion."""
    from test.linker.circular_stress import aliased, aliased_target  # noqa: F401
    from test.linker.circular_stress.homonyms.crm import items as crm_items  # noqa: F401
    from test.linker.circular_stress.homonyms.crm import orders as crm_orders  # noqa: F401
    from test.linker.circular_stress.homonyms.shop import items as shop_items  # noqa: F401
    from test.linker.circular_stress.homonyms.shop import orders as shop_orders  # noqa: F401
    from test.linker.circular_stress import quoted_only, quoted_only_target  # noqa: F401
    from test.linker.circular_stress.relative import left, right  # noqa: F401
    from test.linker.circular_stress.three import a, b, c  # noqa: F401

    for registry in (stress_registry, shop_registry, crm_registry, three_registry):
        snake_link(registry)


def _relation(registry: object, model: type, name: str) -> object:
    """One named relationship off a linked model."""
    table = registry.table_of(model)  # type: ignore[attr-defined]
    assert table is not None
    return next(r for r in table.relationships if r.name == name)


def test_the_block_spelled_as_an_attribute_is_read() -> None:
    """`if typing.TYPE_CHECKING:` counts, not only the bare name.

    Recognising one spelling would reject a file that is perfectly correct — and reject it with the
    old `NameError`, which says nothing about spellings.
    """
    from test.linker.circular_stress.aliased import Aliaser

    assert _relation(stress_registry, Aliaser, "targets").target_table.endswith(  # type: ignore[attr-defined]
        "stress_aliased_targets"
    )


def test_a_name_bound_under_an_alias_is_read() -> None:
    """`import Target as Aliased` binds `Aliased`, and that is the name the annotation uses.

    Reading `alias.name` instead of `alias.asname` would look up a name the module never bound: it
    finds nothing and says nothing about why.
    """
    from test.linker.circular_stress.aliased import Aliaser

    relation = _relation(stress_registry, Aliaser, "targets")

    assert relation.kind is SnakeRelationshipKind.TO_MANY  # type: ignore[attr-defined]


def test_a_nullable_to_one_survives_the_fallback() -> None:
    """`SnakeToOne[Aliaser | None]` still unwraps to the target once resolved the long way.

    The fallback returns hints, and everything downstream reads them — so an `Optional` that came
    back through the second path has to be indistinguishable from one that came back through the
    first.
    """
    from test.linker.circular_stress.aliased_target import Target

    relation = _relation(stress_registry, Target, "owner")

    assert relation.kind is SnakeRelationshipKind.TO_ONE  # type: ignore[attr-defined]
    assert relation.target_table.endswith("stress_aliased")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("app", "registry", "orders_table", "items_table"),
    [
        ("shop", shop_registry, "stress_shop_orders", "stress_shop_items"),
        ("crm", crm_registry, "stress_crm_orders", "stress_crm_items"),
    ],
    ids=["shop", "crm"],
)
def test_each_app_reaches_its_own_homonym(
    app: str, registry: object, orders_table: str, items_table: str
) -> None:
    """THE test. Two apps, each with an `Order` and an `Item`, and neither crosses into the other.

    This is bug #14 asked of the new door: the by-name index would hand both apps whichever `Item`
    registered last, and it would not fail — it would emit valid SQL against the wrong table.
    """
    import importlib

    orders = importlib.import_module(
        f"test.linker.circular_stress.homonyms.{app}.orders"
    )
    items = importlib.import_module(f"test.linker.circular_stress.homonyms.{app}.items")

    assert _relation(registry, orders.Order, "items").target_table.endswith(items_table)  # type: ignore[attr-defined]
    assert _relation(registry, items.Item, "order").target_table.endswith(orders_table)  # type: ignore[attr-defined]


def test_the_two_apps_really_are_homonyms() -> None:
    """The floor: without two classes called `Item` the test above proves nothing.

    A fixture that quietly stopped colliding would stay green over a question it is no longer
    asking.
    """
    from test.linker.circular_stress.homonyms.crm.items import Item as CrmItem
    from test.linker.circular_stress.homonyms.shop.items import Item as ShopItem

    assert CrmItem.__name__ == ShopItem.__name__
    assert CrmItem is not ShopItem


def test_a_cycle_of_three_modules_links() -> None:
    """a -> b -> c -> a, with no runtime import anywhere in the ring.

    Two modules is the shape everybody pictures; three is where a fallback that resolved only its
    immediate neighbour would come apart.
    """
    from test.linker.circular_stress.three.a import NodeA
    from test.linker.circular_stress.three.b import NodeB
    from test.linker.circular_stress.three.c import NodeC

    for model, table in (
        (NodeA, "stress_three_b"),
        (NodeB, "stress_three_c"),
        (NodeC, "stress_three_a"),
    ):
        assert _relation(three_registry, model, "nxt").target_table.endswith(table)  # type: ignore[attr-defined]


def test_none_of_these_modules_imported_the_other_at_runtime() -> None:
    """The premise for the whole file, asserted rather than assumed.

    If any of these imports ever moved out of its block, `get_type_hints` would resolve on its own
    and every test here would pass without the fallback being involved at all.
    """
    from test.linker.circular_stress import aliased, aliased_target
    from test.linker.circular_stress.three import a, b, c

    assert not hasattr(aliased, "Aliased"), (
        "the alias is in globals: the fallback is not being used"
    )
    assert not hasattr(aliased_target, "Aliaser"), "premise gone on the target side"
    for module, name in ((a, "NodeB"), (b, "NodeC"), (c, "NodeA")):
        assert not hasattr(module, name), f"{module.__name__} has {name} in globals"


def test_a_relative_import_in_the_block_is_read() -> None:
    """`from .right import Right` counts too, and inside a package it is the ordinary way to write it.

    It was left out on the grounds that a relative import "gives no absolute path to import back",
    and that was simply wrong: the module carries its own `__package__`, so resolving `.right`
    against it is arithmetic, not a guess. Left out, the pair failed with the same bare

        NameError: name 'Right' is not defined

    that this whole fallback exists to stop — and it failed for a file written the way the standard
    library writes them.
    """
    from test.linker.circular_stress.relative.left import Left
    from test.linker.circular_stress.relative.right import Right

    assert _relation(stress_registry, Left, "rights").target_table.endswith(  # type: ignore[attr-defined]
        "stress_rel_right"
    )
    assert _relation(stress_registry, Right, "left").target_table.endswith(  # type: ignore[attr-defined]
        "stress_rel_left"
    )


def test_quotes_without_the_future_import_resolve_too() -> None:
    """`SnakeToMany["Quoted"]` in a module with NO `from __future__ import annotations`.

    Every other fixture here carries the future import, so this exact pairing —the one the typing
    spec itself documents— was going untested. It has to work, because the two mechanisms answer
    different questions: `TYPE_CHECKING` keeps the IMPORT from running, and the quotes keep the
    ANNOTATION from being evaluated. Neither substitutes for the other, and a resolver that only
    handled the `__future__` spelling would be one nobody could rely on.
    """
    from test.linker.circular_stress.quoted_only import Quoter
    from test.linker.circular_stress.quoted_only_target import Quoted

    assert _relation(stress_registry, Quoter, "items").target_table.endswith(  # type: ignore[attr-defined]
        "stress_quoted_targets"
    )
    assert _relation(stress_registry, Quoted, "owner").target_table.endswith(  # type: ignore[attr-defined]
        "stress_quoted"
    )


def test_the_quoted_pair_really_has_no_future_import() -> None:
    """The premise: with `from __future__ import annotations` this file tests nothing new.

    That import would make the annotation a string on its own, and the quotes would stop being the
    thing under test — the case would silently become a duplicate of the ones above.
    """
    from test.linker.circular_stress import quoted_only, quoted_only_target

    # The BINDING and not the source text: `from __future__ import annotations` binds the name
    # `annotations` in the module, and asking for it cannot be fooled the way a text search can.
    # Measured: searching the source matched this file's own docstring and failed on a module that
    # does not have the import — a premise check with a false positive is worse than none.
    for module in (quoted_only, quoted_only_target):
        assert not hasattr(module, "annotations"), (
            f"{module.__name__} grew the future import, so the quotes are no longer what is "
            f"being tested"
        )
