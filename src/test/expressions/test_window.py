"""Window functions: `<func> OVER (PARTITION BY ... ORDER BY ...)`.

A window does NOT group: it computes one value per row by looking at a set of neighbouring rows. It
is what separates "how much does each department sell" (a GROUP BY, which collapses rows) from "what
rank does each employee hold within their department" (a window, which keeps every one of them).
Without them, that last one is solved with a per-row correlated subquery - the N+1 written in SQL.

It fits in as just another `SnakeValue`: it is projected like any column and the emitter dispatches
it by type. Nothing had to change shape, which was exactly the bet when this was planned.

What IS needed is forbidding it where SQL forbids it: in WHERE, GROUP BY and HAVING. A window is
evaluated AFTER those clauses, so filtering by it is not "hard", it is impossible.
"""

from __future__ import annotations

import pytest

from snakeorm import PostgresDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import (
    SnakeExpr,
    dense_rank,
    lag,
    lead,
    rank,
    row_number,
    sum_,
)
from snakeorm.sql.value import emit_value

_DIALECT = PostgresDialect()
_SALARIO = SnakeExpr[int](path=("salario",))
_DEPTO = SnakeExpr[str](path=("departamento",))
_ANIO = SnakeExpr[int](path=("anio",))


def _sql(value: object) -> tuple[str, list[object]]:
    """Emits a value and returns its SQL along with the parameters it consumed."""
    params: list[object] = []
    return emit_value(value, _DIALECT, params), params


def test_row_number_without_a_window_is_over_everything() -> None:
    """Checks that an empty `OVER ()` is emitted: it is the window over ALL the rows, and it is legal."""
    sql, params = _sql(row_number())
    assert sql == "ROW_NUMBER() OVER ()"
    assert params == []


def test_partition_by_and_order_by_land_in_the_over() -> None:
    """Checks the complete window: it partitions by a value and sorts within the partition."""
    sql, _ = _sql(row_number().over(partition_by=[_DEPTO], order_by=[_SALARIO.desc()]))
    assert (
        sql == 'ROW_NUMBER() OVER (PARTITION BY "departamento" ORDER BY "salario" DESC)'
    )


def test_rank_and_dense_rank_are_distinct_functions() -> None:
    """Checks that they are emitted as different functions: they do not agree on a tie."""
    assert _sql(rank())[0].startswith("RANK()")
    assert _sql(dense_rank())[0].startswith("DENSE_RANK()")


def test_lag_and_lead_carry_their_offset_as_a_parameter() -> None:
    """Checks that the offset travels PARAMETERISED, not interpolated into the string.

    It is a number, so the temptation to drop it into the f-string is huge. The project rule admits
    no exceptions by type: values are never interpolated.
    """
    sql, params = _sql(lag(_SALARIO, offset=2))
    assert sql == 'LAG("salario", %s) OVER ()'
    assert params == [2]

    sql, params = _sql(lead(_SALARIO))
    assert sql == 'LEAD("salario", %s) OVER ()'
    assert params == [1], "the default offset is 1, and it is parametrised too"


def test_an_aggregate_becomes_a_window_with_over() -> None:
    """Checks the running total: an aggregate with `.over(...)` stops collapsing rows.

    `SUM(x)` with GROUP BY returns ONE row per group. `SUM(x) OVER (...)` returns EVERY row with its
    running total next to it. Same function, opposite semantics, and the difference is just the OVER.
    """
    sql, _ = _sql(sum_(_SALARIO).over(partition_by=[_DEPTO], order_by=[_SALARIO.asc()]))
    assert (
        sql
        == 'SUM("salario") OVER (PARTITION BY "departamento" ORDER BY "salario" ASC)'
    )


def test_nulls_placement_survives_into_the_window() -> None:
    """Checks that the `NULLS FIRST/LAST` of the ordering makes it inside the OVER too."""
    sql, _ = _sql(row_number().over(order_by=[_SALARIO.desc().nulls_last()]))
    assert sql == 'ROW_NUMBER() OVER (ORDER BY "salario" DESC NULLS LAST)'


def test_a_window_is_refused_inside_a_where() -> None:
    """Checks that filtering by a window is rejected WITH its reason, not with invalid SQL.

    SQL evaluates windows AFTER the WHERE, so `WHERE ROW_NUMBER() OVER () <= 3` is not hard: it is
    impossible. Postgres rejects it, but its message does not explain what to do. The right path
    -wrapping the query and filtering outside- has to be said here.
    """
    from snakeorm.sql.condition import emit_condition

    with pytest.raises(
        SnakeEmitError, match="A window function cannot be used in a WHERE"
    ):
        emit_condition(row_number() <= 3, _DIALECT)


def test_a_window_is_refused_inside_a_group_by() -> None:
    """Checks that grouping BY a window is rejected here, not by the engine.

    A GROUP BY is not a condition -it is a list of values-, so it slipped past the condition guard
    even though its docstring promised to cover it. Postgres caught it, but a doc that promises more
    than it delivers is a way of lying: the promise gets kept instead of watered down.
    """
    from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
    from snakeorm.sql.aggregate import emit_project

    column = SnakeColumnInfo(name="salario", python_type=int)
    table = SnakeTableInfo(
        name="win_probe",
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=(column,)),
    )

    with pytest.raises(SnakeEmitError, match="GROUP BY"):
        emit_project(table, _DIALECT, [_SALARIO], group_by=[row_number()])


def test_a_window_partitions_and_sorts_by_more_than_one_key() -> None:
    """Two keys are a LIST in SQL, and a list needs the comma the single-key case never shows.

    "Rank within the department AND the year, most senior first, ties broken by salary" is the
    ordinary shape of a window; one key is the degenerate case. With the keys run together the
    statement is not a narrower window, it is a syntax error or — where the engine parses it — a
    different partition entirely.
    """
    sql, _ = _sql(
        row_number().over(
            partition_by=[_DEPTO, _ANIO],
            order_by=[_ANIO.desc(), _SALARIO.asc()],
        )
    )

    assert sql == (
        'ROW_NUMBER() OVER (PARTITION BY "departamento", "anio" '
        'ORDER BY "anio" DESC, "salario" ASC)'
    )
