"""Tests of .include(): eager loading of to-one relations (LEFT JOIN + SELECT of the related rows).

`.include(Truck.maker)` adds a LEFT JOIN and also projects the related table's columns, so that the
session can rebuild `truck.maker`. Without `.include()`, touching the relation blows up with
`SnakeRelationshipNotLoaded` (the anti-N+1 lock). LEFT (not INNER) so rows with a null FK are not lost.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.fields import SnakeRelationshipNotLoaded
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Truck


def test_include_generates_left_join_and_selects_related() -> None:
    """Checks that .include() adds a LEFT JOIN and also projects the related table's columns."""
    snake_link()
    sql, params = (
        SnakeQuery(Truck).include(Truck.maker).to_include_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT t0."id", t0."model", t0."maker_id", t1."id", t1."name", t1."nation_id" '
        'FROM "public"."trucks" AS t0 '
        'LEFT JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id"'
    )
    assert params == ()


def test_include_deep_chain_selects_all_levels() -> None:
    """Checks that .include(Truck.maker.nation) loads maker AND nation (every prefix)."""
    snake_link()
    sql, _ = (
        SnakeQuery(Truck).include(Truck.maker.nation).to_include_sql(PostgresDialect())
    )
    assert 'LEFT JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id"' in sql
    assert 'LEFT JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id"' in sql
    assert 't2."name"' in sql  # nation's columns make it into the SELECT


def test_include_preserves_filter() -> None:
    """Checks that .include() coexists with .filter(): the WHERE is kept and gets qualified."""
    snake_link()
    query = SnakeQuery(Truck).filter(Truck.model == "Ibiza").include(Truck.maker)
    sql, params = query.to_include_sql(PostgresDialect())
    assert sql.endswith('WHERE t0."model" = %s')
    assert params == ("Ibiza",)


def test_include_segments_cover_root_and_relation() -> None:
    """Checks that the segments go root + relation, in order, each with its model and table."""
    snake_link()
    segments = SnakeQuery(Truck).include(Truck.maker).include_segments()
    prefixes = [prefix for prefix, _model, _table in segments]
    assert prefixes == [(), ("maker",)]
    assert segments[1][1].__name__ == "Maker"


def test_accessing_unloaded_relation_raises() -> None:
    """Checks the anti-N+1 lock: touching an unloaded relation blows up with SnakeRelationshipNotLoaded."""
    snake_link()
    truck = Truck(id=1, model="Ibiza", maker_id=1)  # type: ignore[call-arg]
    with pytest.raises(SnakeRelationshipNotLoaded, match="Relation 'maker' was not"):
        _ = truck.maker
