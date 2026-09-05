"""BUG #14, the half that was never fixed: the JOIN still resolved by CLASS NAME.

`test_model_name_collision.py` next door fixed the MIGRATION path — the foreign key stopped pointing
at the wrong table. The query path was left behind, and it is the one a running application uses on
every request.

`JoinPlan` did `self._resolve(relationship.target)`, and `.target` is the class name. The qualified
name the linker had just computed, `relationship.target_table`, sits on the SAME object and nobody
read it. The five call sites in `query.py` handed it `registry.table_by_name` raw — the index
`register()` overwrites in silence, right next to the loud guard that protects the qualified one.

So with `billing.Customer` and `crm.Customer` in one process, a filter through
`Invoice.customer.nif` emitted:

    SELECT ... FROM "col_invoices" AS t0
    JOIN "col_crm_customers" AS t1 ON t0."customer_id" = t1."id" WHERE t1."nif" = $1

Valid SQL. It runs. It reads a table that has no `nif` column, or worse, one that does and holds
somebody else's rows. No exception, no warning.

`registry.resolve_relationship` already existed and already preferred the qualified name, and its
docstring says it exists "so that fixing the wrong target is ONE change and not twelve copies".
Twelve places used it. These did not.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from snakeorm import PostgresDialect
from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.sql.joins import JoinPlan

# `crm` is imported for its SIDE EFFECT and ruff is told so: importing it is what registers the
# second `Customer` and makes the class name ambiguous. Without it this file would exercise a
# registry with one Customer in it and pass over the bug it exists for.
from test.registry.collision_apps import apps_registry, billing, crm  # noqa: F401

_DIALECT = PostgresDialect()


@pytest.fixture(autouse=True)
def _linked() -> None:
    """The two apps linked in their own registry, as the sibling test does."""
    snake_link(apps_registry)


def test_a_join_lands_on_the_table_the_relation_declares() -> None:
    """The whole bug in one assertion: the SQL names `col_fact_customers`, not the CRM one.

    `billing.Invoice.customer` points at `billing.Customer` (`col_fact_customers`). `crm.Customer`
    registered last, so it owns the name "Customer" in the by-name index — and that index is what
    the JOIN used to ask.
    """
    query = SnakeQuery(billing.Invoice, registry=apps_registry).filter(
        billing.Invoice.customer.nif == "B123"
    )

    sql, _ = query.to_sql(_DIALECT)

    assert "col_fact_customers" in sql, (
        "the JOIN went to the wrong table: it resolved the target by CLASS NAME"
    )
    assert "col_crm_customers" not in sql


def test_the_linker_had_the_right_answer_all_along() -> None:
    """The metadata was never wrong, which is what makes this a resolution bug and not a linker one.

    Worth pinning separately: it stops anybody 'fixing' this in the linker, where nothing is broken.
    """
    table = apps_registry.table_of(billing.Invoice)
    assert table is not None
    relation = next(r for r in table.relationships if r.name == "customer")

    assert relation.target_table == "public.col_fact_customers"
    assert relation.target == "Customer", "the class name really is ambiguous here"


def test_the_join_plan_refuses_a_target_it_cannot_resolve_unambiguously() -> None:
    """Resolving through the relation means an unresolvable target now RAISES rather than guessing.

    The old shape had one failure mode —silence— because a missing name simply came back `None` and
    a wrong one came back wrong. Asking through `resolve_relationship` means the registry answers
    for the pair it knows, and there is a place for the complaint to come from.
    """
    table = apps_registry.table_of(billing.Invoice)
    assert table is not None
    relation = next(r for r in table.relationships if r.name == "customer")
    orphan = replace(relation, target="Nowhere", target_table="public.nowhere")
    broken = replace(table, relationships=(orphan,))

    with pytest.raises(SnakeRegistryError, match="Nowhere"):
        JoinPlan(broken, (("customer", "nif"),), _DIALECT, apps_registry)


def test_without_the_qualified_resolution_the_bug_comes_back() -> None:
    """The negative twin of the sibling file's: resolve by class name and the wrong table returns.

    A fix nobody can demonstrate breaking is a fix nobody can trust. This re-runs the OLD resolution
    —by `__name__`, through the index the collision guard does not protect— and DEMANDS the wrong
    answer, so the day somebody reintroduces it this test is the one that objects.
    """
    wrong = apps_registry.table_by_name("Customer")

    assert wrong is not None
    assert wrong.name == "col_crm_customers", (
        "the by-name index no longer prefers the last registration, so this test is watching "
        "something that has moved: check what replaced it before deleting it"
    )
