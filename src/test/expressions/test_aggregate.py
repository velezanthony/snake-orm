"""The AST aggregate node: typed constructors, path propagation and COUNT(*).

An aggregate is a `SnakeValue` (comparable, composable), not a condition. The public constructors
(`count`, `sum_`, `avg`, `min_`, `max_`) return the node with its function and its argument;
`paths()` propagates the argument's own so the aggregate plans its own JOINs.
"""

from __future__ import annotations

from snakeorm.expressions import SnakeAggFunc, SnakeValue
from snakeorm.expressions.functions import avg, count, max_, min_, sum_
from test.scenarios.deep_domain import Truck


def test_count_without_argument_is_count_star() -> None:
    """`count()` with no argument represents `COUNT(*)`: its `arg` is None."""
    node = count()
    assert node.func is SnakeAggFunc.COUNT
    assert node.arg is None
    assert node.distinct is False


def test_count_with_column_keeps_the_argument() -> None:
    """`count(col)` keeps the column as its argument (it is not COUNT(*))."""
    node = count(Truck.id)
    assert node.func is SnakeAggFunc.COUNT
    assert isinstance(node.arg, SnakeValue)


def test_count_distinct_flag() -> None:
    """`count(col, distinct=True)` flags the DISTINCT on the node."""
    node = count(Truck.id, distinct=True)
    assert node.distinct is True


def test_sum_min_max_carry_their_function() -> None:
    """`sum_`, `min_`, `max_` produce the node carrying the matching function."""
    assert sum_(Truck.id).func is SnakeAggFunc.SUM
    assert min_(Truck.id).func is SnakeAggFunc.MIN
    assert max_(Truck.id).func is SnakeAggFunc.MAX


def test_avg_carries_its_function() -> None:
    """`avg` produces the node carrying the AVG function."""
    assert avg(Truck.id).func is SnakeAggFunc.AVG


def test_paths_of_count_star_are_empty() -> None:
    """`COUNT(*)` references no columns: `paths()` is empty (it forces no JOIN)."""
    assert count().paths() == ()


def test_paths_propagate_from_the_argument() -> None:
    """The aggregate propagates its argument's paths: that is how it plans its own JOINs."""
    from snakeorm.linker import snake_link

    snake_link()  # enables class navigation for Truck.maker.nation_id
    node = sum_(Truck.maker.nation_id)
    assert node.paths() == (("maker", "nation_id"),)


def test_aggregate_is_a_value() -> None:
    """An aggregate inherits from `SnakeValue`: comparable and composable like any column."""
    assert isinstance(count(), SnakeValue)
    assert isinstance(sum_(Truck.id), SnakeValue)


def test_aggregate_is_comparable_yielding_a_condition() -> None:
    """Comparing an aggregate produces a condition (the basis of HAVING): `count() > 3`."""
    from snakeorm.expressions import SnakeComparison

    assert isinstance(count() > 3, SnakeComparison)
