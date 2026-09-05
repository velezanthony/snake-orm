"""Reaching a to-many THROUGH a to-one: `Contract.owner.memberships.any(...)`.

Class access already promises this. `SnakeToOne.__get__` is typed `type[M]`, so the checker reads
`Contract.owner.memberships` as the `SnakeCollection[Membership]` the descriptor of `User` hands
back, and both mypy and pyright accept the line. Only the runtime refused it, and the refusal LIED:

    AttributeError: 'tenancy_users' has no column or relation called 'memberships'

The table has it. `SnakeToOne._target_table` was captured during the linker's FIRST pass, and the
to-many relationships are added by the SECOND, so the proxy navigates a snapshot taken before the
collections existed. That is the trap `snake_link()` already warns about — every link builds NEW
frozen tables — landing on the linker itself.

WHAT IS ASSERTED IS THE EMITTED SQL, and it has to be, because the correlation is the whole defect:
with one hop in front, the child of the subquery no longer correlates with the root but with the
JOINed alias. A row count cannot tell those two apart on any data where the owner is the only user.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.fields.relationship import SnakeCollection
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.tenancy_domain import Contract, Membership, User

snake_link()

_POSTGRES = PostgresDialect()


def test_a_to_one_gives_back_a_collection_and_not_a_navigable_proxy() -> None:
    """`Contract.owner.memberships` is a `SnakeCollection`, which is what the type already says.

    A `SnakePathProxy` would be the other bug: it exposes the target's COLUMNS, so
    `Contract.owner.memberships.role` would emit SQL that answers a question about a different
    cardinality instead of failing.
    """
    collection = Contract.owner.memberships

    assert isinstance(collection, SnakeCollection)
    with pytest.raises(AttributeError):
        collection.role  # type: ignore[attr-defined]


def test_the_exists_correlates_with_the_joined_owner_and_not_with_the_root() -> None:
    """The multi-tenancy predicate: `e0."user_id"` has to equal `t1."id"`, the owner's alias.

    `t0` is the contract. Correlating there would compare a membership's user against a CONTRACT id
    — valid SQL, real rows, and on any fixture where the ids happen to line up, the right answer.
    """
    query = SnakeQuery(Contract).filter(
        Contract.owner.memberships.any(Membership.organization_id == 20)
    )

    sql, params = query.to_sql(_POSTGRES)

    assert 'JOIN "public"."tenancy_users" AS t1 ON t0."owner_id" = t1."id"' in sql, sql
    assert (
        'EXISTS (SELECT 1 FROM "public"."tenancy_memberships" AS e0 '
        'WHERE e0."user_id" = t1."id" AND e0."organization_id" = %s)' in sql
    ), sql
    assert params == (20,)


def test_the_condition_of_the_any_may_navigate_the_child_from_there() -> None:
    """Two hops out and one more in: `owner.memberships.any(Membership.organization.name == ...)`.

    The JOIN inside the EXISTS is the child's own, with its own alias space, so it must not collide
    with the `t1` the outer query allocated for the owner.
    """
    query = SnakeQuery(Contract).filter(
        Contract.owner.memberships.any(Membership.organization.name == "Globex")
    )

    sql, _ = query.to_sql(_POSTGRES)

    assert (
        'EXISTS (SELECT 1 FROM "public"."tenancy_memberships" AS e0 '
        'JOIN "public"."tenancy_organizations" AS e1 ON e0."organization_id" = e1."id" '
        'WHERE e0."user_id" = t1."id" AND e1."name" = %s)' in sql
    ), sql


def test_an_aggregate_of_that_collection_projects_against_the_same_alias() -> None:
    """`count()` through a to-one is the same correlation in the column list.

    The projection is where the capability already lived for a collection reached from the root; a
    hop in front must not change anything but the reference back to the parent.
    """
    query = SnakeQuery(Contract)

    sql, _ = query.to_project_sql(
        _POSTGRES, (Contract.alias, Contract.owner.memberships.count())
    )

    assert (
        'SELECT t0."alias", (SELECT COUNT(*) FROM "public"."tenancy_memberships" AS e0 '
        'WHERE e0."user_id" = t1."id") FROM "public"."tenancy_contracts" AS t0 '
        'JOIN "public"."tenancy_users" AS t1 ON t0."owner_id" = t1."id"' == sql
    ), sql


def test_a_collection_reached_from_the_root_is_untouched() -> None:
    """The shape that already worked keeps correlating with the table, with no JOIN and no alias."""
    query = SnakeQuery(User).filter(User.memberships.any(Membership.role == "OWNER"))

    sql, _ = query.to_sql(_POSTGRES)

    assert (
        'EXISTS (SELECT 1 FROM "public"."tenancy_memberships" AS e0 '
        'WHERE e0."user_id" = "tenancy_users"."id" AND e0."role" = %s)' in sql
    ), sql
    assert " JOIN " not in sql, sql


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect(), SQLiteDialect()],
    ids=["postgres", "mysql", "sqlite"],
)
def test_it_is_the_same_shape_on_the_three_engines(dialect: object) -> None:
    """Nothing here depends on a capability: only the quoting and the placeholder change."""
    query = SnakeQuery(Contract).filter(
        Contract.owner.memberships.any(Membership.organization_id == 20)
    )

    sql, _ = query.to_sql(dialect)  # type: ignore[arg-type]

    assert "EXISTS (SELECT 1 FROM " in sql, sql
    assert "= t1." in sql, sql


def test_two_hops_before_the_collection_correlate_with_the_last_one() -> None:
    """`Membership.user.memberships` is one hop; the alias of the parent is the one it JOINed.

    Written from the other side of the same graph so the assertion cannot be satisfied by a rule
    that only ever works for `owner`.
    """
    query = SnakeQuery(Membership).filter(
        Membership.user.memberships.any(Membership.role == "OWNER")
    )

    sql, _ = query.to_sql(_POSTGRES)

    assert 'JOIN "public"."tenancy_users" AS t1 ON t0."user_id" = t1."id"' in sql, sql
    assert 'WHERE e0."user_id" = t1."id" AND' in sql, sql


def test_loading_that_collection_is_still_refused_in_plain_words() -> None:
    """The new door is for FILTERING and AGGREGATING; `include()` keeps its own answer.

    Reaching the collection made a shape reachable that used to die at attribute access, so the
    guard below is now the only thing between the caller and an include that loads nothing. It is
    checked here because that is exactly the kind of silence this change could have introduced.
    """
    query = SnakeQuery(Contract).include(Contract.owner.memberships)

    with pytest.raises(SnakeUnsupportedFeature) as raised:
        query.to_many_includes()

    assert "SnakePrefetch" in str(raised.value)


def test_the_organization_side_reaches_its_members_through_a_to_one_too() -> None:
    """The far end of the same predicate, so the fix is not read off one relationship's shape."""
    query = SnakeQuery(Membership).filter(
        Membership.organization.memberships.any(Membership.role == "OWNER")
    )

    sql, _ = query.to_sql(_POSTGRES)

    assert (
        'JOIN "public"."tenancy_organizations" AS t1 ON t0."organization_id" = t1."id"'
        in sql
    ), sql
    assert 'WHERE e0."organization_id" = t1."id" AND' in sql, sql
