"""A mirror carries its FOREIGN KEYS, or the shared queries cannot be written against it.

Measured before this existed: the generator emitted 70 tables and ZERO relationships, while the
demo's shared query layer uses 23 `include(...)` and 175 `Model.rel.field` navigations. So a
generated `models.py` could not serve one single one of them — not for any packaging reason, but
because `Post.author` was not there to be written.

The information was never missing. The introspector already returns
`foreign_key.pairs = (('brand_id', 'id'),)`; the generator was throwing it away.

WHAT THE NAME COMES FROM is the local COLUMN and not the target table, because that is the
convention the hand-written models keep:

    owner_id: SnakeColumn[int] = snake_int(index=True)
    owner:    SnakeToOne[User] = snake_to_one(owner_id)

The field the introspector fills in is called `name` and holds `'brands'` — the target table — so
using it would have produced `cars.brands` where a person writes `cars.brand`.
"""

from __future__ import annotations


from snakeorm.introspection.models import (
    SnakeMirrorNames,
    render_models,
    unrepresentable,
)
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
)

_ID = SnakeColumnInfo(name="id", python_type=int, attr_name="id")


def _fk(target: str, *pairs: tuple[str, str]) -> SnakeRelationshipInfo:
    """A to-one exactly as the introspector hands it over."""
    return SnakeRelationshipInfo(
        name=target,
        target=target,
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(target=target, pairs=pairs),
    )


def _child(*columns: SnakeColumnInfo, rel: SnakeRelationshipInfo) -> SnakeTableInfo:
    """A table that points at another one."""
    return SnakeTableInfo(
        name="cars",
        columns=(_ID, *columns),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        relationships=(rel,),
    )


def _target(name: str) -> SnakeTableInfo:
    """The table a relationship points at, present in the batch.

    Passed alongside the child in every case but one, because a to-one whose target is NOT being
    generated is its own failure — and a test that let it happen by accident would be asserting two
    things and telling you about the wrong one.
    """
    return SnakeTableInfo(
        name=name, columns=(_ID,), primary_key=SnakePrimaryKeyInfo(columns=(_ID,))
    )


def test_a_foreign_key_becomes_a_typed_to_one() -> None:
    """The column keeps its `_id` and the relationship drops it, as a person would write it."""
    brand_id = SnakeColumnInfo(name="brand_id", python_type=int, attr_name="brand_id")
    table = _child(brand_id, rel=_fk("brands", ("brand_id", "id")))

    source = render_models([table, _target("brands")])

    assert "brand_id: SnakeColumn[int]" in source
    assert "brand: SnakeToOne[PublicBrands] = snake_to_one(brand_id)" in source


def test_the_generated_file_links_what_it_declares() -> None:
    """`snake_link()` at the end, and the symbol on the IMPORT line.

    The compiler is two-phase on purpose — columns first, relations after — so a file that declares
    relations and never links them imports cleanly and fails at the first query.

    The import half is asserted because leaving it out is the bug this test let through the first
    time: `snake_link()` was emitted while the symbol reached `snake_symbols` after the
    `from snakeorm import ...` line had already been built. The file PARSED — `compile()` was
    perfectly happy — and raised `NameError` the moment anything RAN it.

    Running it is `test_scaffold_e2e.py`'s half, and it is the one that caught this: it writes the
    file and imports it for real, which is what forward references need. Checking the text here and
    the behaviour there is the split; checking only the text was the mistake.
    """
    brand_id = SnakeColumnInfo(name="brand_id", python_type=int, attr_name="brand_id")

    source = render_models(
        [_child(brand_id, rel=_fk("brands", ("brand_id", "id"))), _target("brands")]
    )

    imports = next(
        line for line in source.splitlines() if line.startswith("from snakeorm import")
    )

    assert "snake_link()" in source
    assert "snake_link" in imports, "emitted AND imported, not only called"


def test_a_composite_key_takes_the_prefix_the_two_columns_share() -> None:
    """`stock_warehouse_id` + `stock_sku_id` is ONE relationship called `stock`.

    Naming it after either column would be arbitrary, and after the target table would give
    `stocks`. The shared prefix is what the hand-written model calls it, and it is derivable.
    """
    a = SnakeColumnInfo(
        name="stock_warehouse_id", python_type=int, attr_name="stock_warehouse_id"
    )
    b = SnakeColumnInfo(name="stock_sku_id", python_type=int, attr_name="stock_sku_id")
    table = _child(
        a,
        b,
        rel=_fk(
            "warehouse_stock",
            ("stock_warehouse_id", "warehouse_id"),
            ("stock_sku_id", "sku_id"),
        ),
    )

    source = render_models([table, _target("warehouse_stock")])

    assert (
        "stock: SnakeToOne[PublicWarehouseStock] = "
        "snake_to_one(stock_warehouse_id, stock_sku_id)" in source
    )


def test_the_suffix_stripping_is_a_switch() -> None:
    """Off, the relationship keeps the column's whole name — which then COLLIDES, and is reported.

    A database whose FK columns carry no `_id` at all is the case the switch is for: there,
    stripping does nothing and the collision below is what you get either way. Turning it off makes
    that visible instead of surprising.
    """
    brand_id = SnakeColumnInfo(name="brand_id", python_type=int, attr_name="brand_id")
    table = _child(brand_id, rel=_fk("brands", ("brand_id", "id")))

    complaints = unrepresentable(
        [table, _target("brands")], SnakeMirrorNames(strip_id_suffix=False)
    )

    assert len(complaints) == 1
    assert "brand_id" in complaints[0]


def test_a_relationship_that_would_shadow_a_column_is_reported() -> None:
    """An FK column named `owner` with no suffix: the to-one would take the column's own name.

    Emitting both would leave a class where one attribute silently replaces the other, which is the
    shape this generator has been bitten by twice already. It is named and left out instead.
    """
    owner = SnakeColumnInfo(name="owner", python_type=int, attr_name="owner")
    table = _child(owner, rel=_fk("users", ("owner", "id")))

    complaints = unrepresentable([table, _target("users")])

    assert len(complaints) == 1
    assert "owner" in complaints[0]


def test_a_derived_name_that_python_refuses_is_reported() -> None:
    """`class_id` is a fine column and `class` is a keyword: the DERIVATION creates the problem.

    Found by running the generator against a real database, which is the only place a column called
    `class_id` existed. The column itself passes every check — it is the name computed FROM it that
    Python will not take, so the check has to be made after the derivation and not before.
    """
    class_id = SnakeColumnInfo(name="class_id", python_type=int, attr_name="class_id")
    table = _child(class_id, rel=_fk("classes", ("class_id", "id")))
    batch = [table, _target("classes")]

    source = render_models(batch)
    complaints = unrepresentable(batch)

    compile(source, "generated", "exec")
    assert "SnakeToOne" not in source
    assert len(complaints) == 1 and "'class'" in complaints[0]


def test_a_relationship_pointing_outside_the_batch_is_dropped_and_reported() -> None:
    """The target class has to be IN the file, or the file does not import.

    The generator resolves nothing: it RECOMPUTES the target's class name with the same rule that
    named it, which is what makes the two sides agree without a lookup or a second pass. The cost is
    this — if the target table is not in the batch, the name is computed all the same and points at
    a class nobody declared.

    It is not hypothetical: `--schema` is a documented flag, and a schema whose tables reference
    another one produces exactly this. The file COMPILED, because `from __future__ import
    annotations` makes the reference a string, and then failed at import with `NameError`. A
    generator whose output does not import has failed at the only thing it does.
    """
    brand_id = SnakeColumnInfo(name="brand_id", python_type=int, attr_name="brand_id")
    orphan = _child(brand_id, rel=_fk("brands", ("brand_id", "id")))

    source = render_models([orphan])
    complaints = unrepresentable([orphan])

    assert "SnakeToOne" not in source, "the target is not in the file"
    assert len(complaints) == 1
    assert "brands" in complaints[0] and "cars" in complaints[0]
