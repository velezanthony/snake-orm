"""BUG #14 — two models with the SAME class name in different modules.

It showed up on its own, and in the worst possible way: adding a `Customer` model to a test file made
the example domain migration start emitting the `shop_orders` FK pointing at the test table. It
was not broken by a change in the linker — it was broken by declaring a class with a common name
somewhere else.

The registry kept two indexes and treated them differently:

    self._table_owner[qualified] = model    # TABLE collision -> SnakeRegistryError, loud
    self._by_name[model.__name__] = table   # CLASS collision -> overwrites IN SILENCE

And the target of a relation was resolved through that second index. The last one to register won,
so the foreign key **depended on the order of the imports**: in one order it came out right and in
the other wrong. A bug that gets it right half of the time is the one that reaches production.

And it did not fail: both tables exist —we manage them—, so the `ALTER TABLE ... REFERENCES` was
applied without complaint and left referential integrity pointing at the wrong table.

The serious part was how you got there. By default both `Customer` go to the `customers` table, they
clash, and the guard fires loudly — you are protected. But the message says *"disambiguate with
prefix= or table="*, you comply, the tables stop clashing, the guard goes quiet... and you walk into
the silent failure. The tool itself handed you the instruction that put you there.

The models live in REAL modules (`collision_apps/`) and not in classes inside a function: the
compiler resolves the annotations with `get_type_hints`, which looks at the module globals, so a
local class would not resolve and this test would fail for a reason other than the one it measures.
"""

from __future__ import annotations

from snakeorm import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.migration.autodetect import current_schema
from snakeorm.migration.diff import diff_schema
from test.registry.collision_apps import apps_registry, crm, billing


def _emitted_foreign_keys() -> list[str]:
    """The FKs the autogen would emit for `col_invoices`, with both apps registered."""
    snake_link(apps_registry)
    operations = diff_schema(
        [],
        current_schema(apps_registry),
        apps_registry.table_by_name,
        apps_registry.table_by_qualified,
    )
    return [
        sql
        for operation in operations
        for sql in operation.up_sql(PostgresDialect())
        if "FOREIGN KEY" in sql and "col_invoices" in sql
    ]


def test_the_foreign_key_points_at_the_referenced_model() -> None:
    """The FK must point at the table of the REFERENCED model, not at the last one named the same."""
    fks = _emitted_foreign_keys()

    assert fks, "the relationship should produce an FK"
    assert "col_fact_customers" in fks[0], f"it points at the wrong table: {fks[0]}"
    assert "col_crm_customers" not in fks[0]


def test_both_apps_keep_their_own_table() -> None:
    """Checks the starting point: they are two DIFFERENT models, each with its own table.

    If this failed, the test above would be measuring something else: there would be no two models
    to confuse, and getting the target right would prove nothing.
    """
    fact = apps_registry.table_of(billing.Customer)
    crm_customer = apps_registry.table_of(crm.Customer)

    assert fact is not None and crm_customer is not None
    assert fact.name == "col_fact_customers"
    assert crm_customer.name == "col_crm_customers"
    assert billing.Customer.__name__ == crm.Customer.__name__ == "Customer"


def test_the_relation_carries_its_resolved_target() -> None:
    """The linker stores the target already RESOLVED and qualified: that is where the bug is fixed.

    It is the piece that makes the ambiguous lookup unnecessary: when the linker links, it has the
    target CLASS right in front of it. Before, it reduced it to `__name__` and threw the identity away.
    """
    snake_link(apps_registry)
    invoice = apps_registry.table_of(billing.Invoice)
    assert invoice is not None

    relation = next(rel for rel in invoice.relationships if rel.name == "customer")
    assert relation.target == "Customer", (
        "the name is kept for the replay of old migrations"
    )
    assert relation.target_table == "public.col_fact_customers"


def test_without_the_qualified_resolution_the_bug_comes_back() -> None:
    """Checks that the fix is what MAKES the difference, and not that the test passes by a miracle.

    The same diff is emitted without the qualified resolver, that is, with the old resolution by
    class name. If the FK still comes out right in that mode, this file would be measuring nothing:
    the registration order would have got it right by chance and the test would go green forever
    while watching absolutely nothing.
    """
    snake_link(apps_registry)
    operations = diff_schema(
        [],
        current_schema(apps_registry),
        apps_registry.table_by_name,  # without `resolve_qualified`: the old path
    )
    fks = [
        sql
        for operation in operations
        for sql in operation.up_sql(PostgresDialect())
        if "FOREIGN KEY" in sql and "col_invoices" in sql
    ]

    assert fks
    assert "col_crm_customers" in fks[0], (
        "without qualified resolution the FK should point WRONG (the last registered one wins); "
        "if it points right, this test is not measuring the fix"
    )
