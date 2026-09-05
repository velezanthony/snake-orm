"""The EXACT SQL of an explicit `.join()` into a collection (to-many).

What is critical about a JOIN into a collection is the DIRECTION of the ON: the FK lives on the
CHILD, so the ON is `child.fk = parent.pk`, NOT the other way round (the historical inverted-JOIN
bug). Here the full string is pinned down for an INNER, a LEFT, a COMPOSITE FK (an AND of the
pairs) and two chained joins.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.fields import (
    SnakeColumn,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_to_many,
    snake_to_one,
)
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeJoin, SnakeQuery
from test.scenarios.deep_domain import Nation


@snake_model(table="xj_ledgers")
class Ledger(SnakeModel):
    """An accounting ledger with a COMPOSITE PK `(org_id, code)` and a to-many into its entries."""

    org_id: SnakeColumn[int] = snake_int(primary_key=True)
    code: SnakeColumn[int] = snake_int(primary_key=True)
    entries: SnakeToMany[Entry] = snake_to_many("ledger")


@snake_model(table="xj_entries")
class Entry(SnakeModel):
    """An entry with a COMPOSITE FK into Ledger's composite PK (two columns, same order)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    ledger_org_id: SnakeColumn[int] = snake_int()
    ledger_code: SnakeColumn[int] = snake_int()
    amount: SnakeColumn[int] = snake_int()
    ledger: SnakeToOne[Ledger] = snake_to_one(ledger_org_id, ledger_code)


def test_inner_join_to_collection_emits_child_side_on() -> None:
    """Checks the SQL of an INNER join into a collection: the ON is `child.fk = parent.pk`."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers)
    sql, params = joined.to_project_sql(
        PostgresDialect(), [Nation.name, joined.right.name]
    )
    assert sql == (
        'SELECT t0."name", t1."name" FROM "public"."nations" AS t0 '
        'JOIN "public"."makers" AS t1 ON t1."nation_id" = t0."id"'
    )
    assert params == ()


def test_left_join_to_collection_keeps_childless_parents() -> None:
    """Checks that `how=LEFT` emits a `LEFT JOIN` (it keeps the parents that have no children)."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers, how=SnakeJoin.LEFT)
    sql, _ = joined.to_project_sql(PostgresDialect(), [Nation.name, joined.right.name])
    assert sql == (
        'SELECT t0."name", t1."name" FROM "public"."nations" AS t0 '
        'LEFT JOIN "public"."makers" AS t1 ON t1."nation_id" = t0."id"'
    )


def test_composite_fk_join_ands_every_pair() -> None:
    """Checks that a COMPOSITE FK joins by AND-ing both pairs, each one in the right direction."""
    snake_link()
    joined = SnakeQuery(Ledger).join(Ledger.entries)
    sql, _ = joined.to_project_sql(
        PostgresDialect(), [Ledger.org_id, joined.right.amount]
    )
    assert sql == (
        'SELECT t0."org_id", t1."amount" FROM "public"."xj_ledgers" AS t0 '
        'JOIN "public"."xj_entries" AS t1 '
        'ON t1."ledger_org_id" = t0."org_id" AND t1."ledger_code" = t0."code"'
    )


def test_two_chained_joins_accumulate_aliases() -> None:
    """Checks two chained joins: each hop gets its own alias and its ON in the right direction."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers)
    chained = joined.join(joined.right.trucks)
    sql, _ = chained.to_project_sql(
        PostgresDialect(), [Nation.name, chained.right.model]
    )
    assert sql == (
        'SELECT t0."name", t2."model" FROM "public"."nations" AS t0 '
        'JOIN "public"."makers" AS t1 ON t1."nation_id" = t0."id" '
        'JOIN "public"."trucks" AS t2 ON t2."maker_id" = t1."id"'
    )


def test_filter_on_root_qualifies_with_the_root_alias() -> None:
    """Checks that a `.filter()` on the parent is qualified with the root alias (t0) alongside the JOIN."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers).filter(Nation.name == "España")
    sql, params = joined.to_project_sql(
        PostgresDialect(), [Nation.name, joined.right.name]
    )
    assert sql.endswith('WHERE t0."name" = %s')
    assert params == ("España",)
    # Sanity: the JOIN into Maker's collection is still there.
    assert 'JOIN "public"."makers" AS t1 ON t1."nation_id" = t0."id"' in sql
