"""A column INSIDE an aggregate is aggregated, however deep inside it sits.

The guard on a grouped projection says it in its own message — "neither in the GROUP BY nor inside an
aggregate" — and then decides by asking whether the projected node IS an aggregate. So the moment an
aggregate is wrapped in anything at all, its argument reads as a bare column and a valid statement is
refused:

    session.select(query.group_by(Nation.name), Nation.name, snake_coalesce(sum_(Maker.id), 0))
    -> Column 'id' appears in the projection but neither in the GROUP BY nor inside an aggregate

`COALESCE(SUM(x), 0)` is the ordinary way to write "the sum, and zero when there is nothing", and
every engine accepts it. So does `SUM(a) - SUM(b)`, and a `CASE` over two aggregates.

WHY IT IS A WALK AND NOT A LIST OF WRAPPERS. The nodes that can legally wrap an aggregate are not a
closed set: `COALESCE`, `NULLIF`, `CASE`, arithmetic, a cast, and whatever gets added next. A guard
that names them is the same shape as a blacklist — it passes what it does not know about, and here it
would fail the other way round, refusing valid SQL until somebody remembers to extend it. Walking the
node's own fields covers every wrapper that exists and every one that does not exist yet.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.dialects import PostgresDialect
from snakeorm.expressions.conditional import snake_case, snake_coalesce, snake_nullif
from snakeorm.expressions.functions import count, sum_
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Maker

snake_link()


def _grouped(*columns: object) -> str:
    """`SELECT <columns> FROM makers GROUP BY nation_id`, emitted."""
    query = SnakeQuery(Maker).group_by(Maker.nation_id)
    sql, _ = query.to_project_sql(PostgresDialect(), columns)  # type: ignore[arg-type]
    return sql


def test_a_bare_aggregate_is_still_accepted() -> None:
    """The case that always worked: the projected node IS the aggregate."""
    sql = _grouped(Maker.nation_id, sum_(Maker.id))

    assert "SUM(" in sql, sql


def test_an_aggregate_wrapped_in_coalesce_is_accepted() -> None:
    """The one the guard refused. `COALESCE(SUM(x), 0)` aggregates `x` just as much as `SUM(x)` does."""
    sql = _grouped(Maker.nation_id, snake_coalesce(sum_(Maker.id), 0))

    assert "COALESCE(SUM(" in sql, sql


def test_an_aggregate_wrapped_in_nullif_is_accepted() -> None:
    """Same rule through a different wrapper, which is the point of walking rather than listing."""
    sql = _grouped(Maker.nation_id, snake_nullif(sum_(Maker.id), 0))

    assert "NULLIF(SUM(" in sql, sql


def test_arithmetic_between_two_aggregates_is_accepted() -> None:
    """An aggregate on each side of a `-`, and no bare column anywhere.

    The left side is `COALESCE(SUM(x), 0)` rather than a naked `SUM`, and that is the type system
    being right rather than a workaround: `SUM` is `int | None`, and subtracting from something that
    may be NULL is a question the checker is entitled to refuse. It also nests one level deeper,
    which is what this walk is about.
    """
    sql = _grouped(Maker.nation_id, snake_coalesce(sum_(Maker.id), 0) - count())

    assert "SUM(" in sql and "COUNT(" in sql, sql


def test_a_case_over_aggregates_is_accepted() -> None:
    """The deepest of the four: the aggregate sits inside a branch of a `CASE`, two levels down."""
    sql = _grouped(
        Maker.nation_id,
        snake_case((sum_(Maker.id) > 10, "many"), default="few"),
    )

    assert "CASE WHEN (SELECT" not in sql, sql
    assert "SUM(" in sql, sql


def test_a_bare_column_is_STILL_refused() -> None:
    """The guard is not weakened, which is the half that matters.

    Widening "inside an aggregate" must not turn into "inside anything". A column projected next to
    a GROUP BY and not aggregated is the error Postgres would raise anyway, and catching it here is
    the whole reason the guard exists.
    """
    with pytest.raises(SnakeEmitError, match="'name'"):
        _grouped(Maker.nation_id, Maker.name)


def test_a_bare_column_WRAPPED_is_also_still_refused() -> None:
    """The dangerous direction: a wrapper must not launder an ungrouped column into acceptance.

    `COALESCE(name, '')` aggregates nothing. If the walk simply skipped everything under a wrapper
    it would pass — and the statement would then fail at the engine, which is exactly the outcome
    this guard exists to prevent.
    """
    with pytest.raises(SnakeEmitError, match="'name'"):
        _grouped(Maker.nation_id, snake_coalesce(Maker.name, ""))


def test_a_grouped_column_inside_a_wrapper_is_accepted() -> None:
    """And the mirror case: what IS grouped stays fine wherever it appears."""
    sql = _grouped(snake_coalesce(Maker.nation_id, 0))

    assert "COALESCE(" in sql, sql
