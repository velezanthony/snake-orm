"""Tests of the `SnakeJoinedQuery` builder: the explicit JOIN towards a collection.

`.join()` returns a type DIFFERENT from `SnakeQuery`, immutable, that only knows how to project.
What is checked here is its RUNTIME behaviour: which type it returns, that it does not mutate, that
it chains, and —the touchiest part— that `joined.right.<col>` produces the path PREFIXED with the
JOIN hop (not the path relative to the child, which would be qualified with the wrong alias).
"""

from __future__ import annotations

from snakeorm.expressions import SnakeExpr
from snakeorm.linker import snake_link
from snakeorm.query import SnakeJoin, SnakeJoinedQuery, SnakeQuery
from test.scenarios.deep_domain import Nation


def test_join_returns_a_joined_query() -> None:
    """Checks that `.join()` on a SnakeQuery returns a SnakeJoinedQuery, not a SnakeQuery."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers)
    assert isinstance(joined, SnakeJoinedQuery)
    assert not isinstance(joined, SnakeQuery)


def test_joined_query_exposes_the_root_model() -> None:
    """Checks that the joined query's `.model` is the ROOT model (Nation), for qualifying/coercing."""
    snake_link()
    assert SnakeQuery(Nation).join(Nation.makers).model is Nation


def test_right_is_a_prefixed_path_proxy() -> None:
    """Checks that `joined.right.<col>` produces a SnakeExpr whose path is PREFIXED by the hop.

    `Maker.name` would give `("name",)` (qualified with the root alias → bad SQL). The `right` proxy
    prefixes it with the JOIN hop → `("makers", "name")`, which is qualified with the JOIN's alias.
    This is the piece that makes projecting child columns correct in a query rooted at the parent.
    """
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers)
    expr = joined.right.name
    assert isinstance(expr, SnakeExpr)
    assert expr.path == ("makers", "name")


def test_filter_is_immutable_and_chains() -> None:
    """Checks that `.filter()` returns a NEW joined query (it does not mutate the original)."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers)
    filtered = joined.filter(Nation.name == "España")
    assert filtered is not joined
    assert isinstance(filtered, SnakeJoinedQuery)


def test_order_limit_offset_distinct_return_joined_queries() -> None:
    """Checks that order_by/limit/offset/distinct still return SnakeJoinedQuery (chainable)."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers)
    assert isinstance(joined.order_by(Nation.name.asc()), SnakeJoinedQuery)
    assert isinstance(joined.limit(3), SnakeJoinedQuery)
    assert isinstance(joined.offset(2), SnakeJoinedQuery)
    assert isinstance(joined.distinct(), SnakeJoinedQuery)


def test_two_joins_accumulate_and_right_tracks_the_last() -> None:
    """Checks that chaining two `.join()` accumulates the hops and `right` points at the LAST child.

    The second `.join()` starts from `joined.right.trucks`; its `right` must expose the accumulated
    prefix `("makers", "trucks")`, not reset itself to the first hop's child.
    """
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers)
    chained = joined.join(joined.right.trucks)
    assert chained.right.model.path == ("makers", "trucks", "model")


def test_left_join_is_recorded_as_left() -> None:
    """Checks that `how=SnakeJoin.LEFT` marks the hop as LEFT (which later shows up in the SQL)."""
    snake_link()
    joined = SnakeQuery(Nation).join(Nation.makers, how=SnakeJoin.LEFT)
    # The SQL is the observable proof that the LEFT travelled all the way to the emitter.
    from snakeorm.dialects import PostgresDialect

    sql, _ = joined.to_project_sql(PostgresDialect(), [Nation.name, joined.right.name])
    assert "LEFT JOIN" in sql
