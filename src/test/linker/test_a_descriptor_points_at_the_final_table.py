"""What a relation descriptor navigates has to be the table the LAST pass registered.

`_target_table` is written while the passes run, and every pass registers NEW frozen tables
(`dataclasses.replace`). So pass 1 left every to-one holding a snapshot taken before pass 2 had
added a single collection, and the proxy built from it answered about a table that no longer
existed anywhere:

    AttributeError: 'tenancy_users' has no column or relation called 'memberships'

Among the to-manys the same hole is decided by ITERATION ORDER, which is worse: whether a
descriptor is stale depends on where its target sits in `reg.models()`.

This is asserted against the REGISTRY's table, not against a list of names, because the defect is
identity: two tables can carry the same relationships and still be two objects, and the one the
descriptor holds is the one navigation reads.
"""

from __future__ import annotations

from snakeorm.fields.relationship import SnakePathProxy
from snakeorm.linker import snake_link
from snakeorm.registry import registry_of
from test.scenarios.tenancy_domain import Contract, Membership, User

snake_link()


def test_a_to_one_navigates_the_table_the_second_pass_left_behind() -> None:
    """`Contract.owner` reaches the `User` that HAS its collections, not pass 1's snapshot."""
    proxy = Contract.owner
    assert isinstance(proxy, SnakePathProxy)

    live = registry_of(User).table_of(User)

    assert proxy._table is live
    assert any(rel.name == "memberships" for rel in proxy._table.relationships)


def test_a_to_many_holds_the_final_child_table_too() -> None:
    """The second pass reads its children as it goes, so its own targets can be stale as well.

    Measured: this one is GREEN without the third pass, and only because of where these models fall
    in `reg.models()`. That is the reason it is written down — the invariant it pins is the one that
    a reordering, or a model declared in another file, turns red for no reason anybody would connect
    to a registration order.
    """
    collection = User.memberships

    live = registry_of(Membership).table_of(Membership)

    assert collection._child_table is live


def test_linking_twice_leaves_the_descriptors_on_the_new_tables() -> None:
    """`snake_link()` is idempotent, and every run BUILDS new tables: the descriptors must follow.

    Without the third pass this is the shape that rots silently — the registry moves on and the
    descriptors keep the previous run's objects, so navigation reads a graph nobody can see.
    """
    snake_link()

    proxy = Contract.owner
    assert isinstance(proxy, SnakePathProxy)

    assert proxy._table is registry_of(User).table_of(User)
