"""Tests for SnakePrefetch: the object that declares a nested loading chain (deep to-many).

A collection (to-many) does NOT expose the child's relations (a phase 2 decision), so
`Nation.makers.trucks` does not exist: the chain is declared with `SnakePrefetch(Nation.makers).then(...)`.
What is tested here is that `.then(...)` accumulates the path hop by hop, chains several levels, and
allows mixing to-many with to-one. EXECUTION (one query per level) is tested in test/session/.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.fields import SnakePrefetch
from snakeorm.fields.relationship import SnakePathProxy
from snakeorm.linker import snake_link
from snakeorm.metadata import SnakeRelationshipKind
from snakeorm.registry import registry
from test.scenarios.deep_domain import Maker, Nation, Truck


def test_prefetch_root_is_a_single_to_many_hop() -> None:
    """Checks that SnakePrefetch(Nation.makers) starts out with a single to-many hop (nations->makers)."""
    snake_link()
    hops = SnakePrefetch(Nation.makers).hops()
    assert [(h.name, h.kind) for h in hops] == [
        ("makers", SnakeRelationshipKind.TO_MANY)
    ]
    assert hops[0].parent_table.name == "nations"
    assert hops[0].child_table.name == "makers"


def test_then_accumulates_a_second_to_many_hop() -> None:
    """Checks that .then(Maker.trucks) adds a second to-many hop (makers->trucks)."""
    snake_link()
    hops = SnakePrefetch(Nation.makers).then(Maker.trucks).hops()
    assert [(h.name, h.kind) for h in hops] == [
        ("makers", SnakeRelationshipKind.TO_MANY),
        ("trucks", SnakeRelationshipKind.TO_MANY),
    ]
    assert hops[1].parent_table.name == "makers"
    assert hops[1].child_table.name == "trucks"


def test_then_chains_several_levels() -> None:
    """Checks that several .then() calls can be chained: the chain grows in root->leaf order."""
    snake_link()
    chain = (
        SnakePrefetch(Nation.makers)
        .then(Maker.trucks)
        .then(Truck.maker)
        .then(Maker.nation)
    )
    assert [(h.name, h.kind) for h in chain.hops()] == [
        ("makers", SnakeRelationshipKind.TO_MANY),
        ("trucks", SnakeRelationshipKind.TO_MANY),
        ("maker", SnakeRelationshipKind.TO_ONE),
        ("nation", SnakeRelationshipKind.TO_ONE),
    ]


def test_then_mixes_to_one_and_to_many() -> None:
    """Checks that the chain mixes to-many and to-one: Nation->makers (many)->nation (one)."""
    snake_link()
    hops = SnakePrefetch(Nation.makers).then(Maker.nation).hops()
    assert [(h.name, h.kind) for h in hops] == [
        ("makers", SnakeRelationshipKind.TO_MANY),
        ("nation", SnakeRelationshipKind.TO_ONE),
    ]
    assert hops[1].child_table.name == "nations"


def test_then_is_immutable_and_returns_a_new_prefetch() -> None:
    """Checks that .then() does not mutate the original prefetch: it returns a new one (like the query)."""
    snake_link()
    base = SnakePrefetch(Nation.makers)
    extended = base.then(Maker.trucks)
    assert len(base.hops()) == 1  # the original did not change
    assert len(extended.hops()) == 2
    assert extended is not base


def test_then_rejects_a_to_many_reached_through_a_proxy_path() -> None:
    """Checks the guard: a to-many hidden inside a proxy path (not an explicit .then) is rejected.

    A to-one class access arrives as a `SnakePathProxy`; if its path were to cross a to-many relation,
    `.then` rejects it -nesting a to-many demands another explicit `.then()`, so as not to break the
    'one query per level' rule-. The proxy is built by hand because normal navigation, thanks to the
    type system, already prevents it.
    """
    snake_link()
    # After a to-one hop the frontier is Nation (a fresh table from the registry, with its 'makers' reverse).
    chain = SnakePrefetch(Nation.makers).then(Maker.nation)
    nations_table = registry.table_of(Nation)
    assert nations_table is not None
    proxy = SnakePathProxy(
        nations_table, ("makers",), registry
    )  # "makers" is to-many over nations
    with pytest.raises(SnakeUnsupportedFeature, match="to-many"):
        chain.then(proxy)  # type: ignore[call-overload]
