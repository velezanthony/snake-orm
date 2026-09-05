"""Tests of to-many relations (snake_to_many): the linker resolves them, the query classifies them.

`Nation.makers = snake_to_many("nation")` is the inverse of `Maker.nation` (FK). The linker (pass 2)
creates a to_many relation reusing the child's FK. The query separates to-one includes (JOIN) from
to-many ones (select-in). Accessing without loading blows up with SnakeRelationshipNotLoaded (the
anti-N+1 lock).
"""

from __future__ import annotations

import pytest

from snakeorm.fields import SnakeRelationshipNotLoaded
from snakeorm.linker import snake_link
from snakeorm.metadata.relationship_kind import SnakeRelationshipKind
from snakeorm.query import SnakeQuery
from snakeorm.registry import registry
from test.scenarios.deep_domain import Nation


def test_linker_resolves_to_many() -> None:
    """Checks that the linker creates the to_many relation 'makers' by reversing the FK 'nation'."""
    snake_link()
    table = registry.table_of(Nation)
    assert table is not None
    makers = next(rel for rel in table.relationships if rel.name == "makers")
    assert makers.kind is SnakeRelationshipKind.TO_MANY
    assert makers.target == "Maker"
    assert makers.foreign_key.pairs == (("nation_id", "id"),)  # reuses the child's FK


def test_query_classifies_to_many_include() -> None:
    """Checks that .include(Nation.makers) is classified as to-many, not as a JOIN."""
    snake_link()
    query = SnakeQuery(Nation).include(Nation.makers)
    assert query.to_one_includes() == ()
    assert [rel.name for rel in query.to_many_includes()] == ["makers"]


def test_unloaded_to_many_raises() -> None:
    """Checks the anti-N+1 lock on to-many: accessing the list without loading it blows up."""
    snake_link()
    nation = Nation(id=1, name="España")
    with pytest.raises(SnakeRelationshipNotLoaded, match="Relation 'makers' was not"):
        _ = nation.makers
