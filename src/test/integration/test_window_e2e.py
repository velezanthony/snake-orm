"""Window functions EXECUTED on the THREE engines, not merely emitted.

Emission tests check that the string is the expected one. That does not prove the engine accepts
it nor that it returns what one believes: the difference between `RANK` and `DENSE_RANK`, or the
fact that a `SUM(...) OVER (ORDER BY ...)` accumulates instead of totalling, is only seen with
real rows.

All three have had window functions for years —Postgres always, MySQL since 8.0, SQLite since
3.25— so there is nothing to declare in `Cap` here: this is a case where the three really do agree
and the only way to know was to ask them.

The numbers are coerced before comparing. MySQL answers a `SUM` as a `Decimal` and the other two as
an integer, which is a difference of TYPE and not of value — asserting it raw would turn a correct
running total into a red for the wrong reason.

Skips gracefully if an engine is not reachable.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
    sum_,
)
from snakeorm.expressions import dense_rank, lag, rank, row_number
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="win_employees")
class Employee(SnakeModel):
    """Employees with department and salary: the canonical domain of window functions."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    departamento: SnakeColumn[str] = snake_str(max_length=30)
    salario: SnakeColumn[int] = snake_int()


_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three sessions with the table populated: two departments, with a TIE on purpose."""
    with three_sessions([Employee]) as sessions:
        for session in sessions.values():
            # The tie in 'ventas' (two at 100) is what separates RANK from DENSE_RANK.
            session.add_all(
                [
                    Employee(id=1, departamento="ventas", salario=100),
                    Employee(id=2, departamento="ventas", salario=100),
                    Employee(id=3, departamento="ventas", salario=50),
                    Employee(id=4, departamento="taller", salario=70),
                ]
            )
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_row_number_ranks_within_each_partition(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Verifies that the partition RESTARTS the numbering within each department."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Employee).order_by(Employee.departamento.asc(), Employee.id.asc()),
        Employee.departamento,
        row_number().over(
            partition_by=[Employee.departamento], order_by=[Employee.id.asc()]
        ),
    )
    assert [(name, int(number)) for name, number in rows] == [
        ("taller", 1),
        ("ventas", 1),
        ("ventas", 2),
        ("ventas", 3),
    ]


@pytest.mark.parametrize("engine", _ENGINES)
def test_rank_and_dense_rank_differ_on_a_tie(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """THE proof that emission cannot give: with a tie, RANK skips ahead and DENSE_RANK does not.

    Two employees at 100 and one at 50. RANK gives 1, 1, 3 —it eats the 2—; DENSE_RANK gives 1, 1,
    2. That the names are so alike and the results are not, is exactly why this had to be executed.
    """
    session = engines[engine]

    query = (
        SnakeQuery(Employee)
        .filter(Employee.departamento == "ventas")
        .order_by(Employee.salario.desc(), Employee.id.asc())
    )
    order = [Employee.salario.desc()]

    with_rank = session.select(query, rank().over(order_by=order))
    with_dense = session.select(query, dense_rank().over(order_by=order))

    assert [int(row[0]) for row in with_rank] == [1, 1, 3]
    assert [int(row[0]) for row in with_dense] == [1, 1, 2]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_sum_over_a_window_accumulates_instead_of_totalling(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Verifies the running total: the same SUM that with GROUP BY would collapse, here accumulates.

    It is the practical difference between aggregating and windowing, and it shows in that FOUR
    rows come out —one per employee— instead of two, one per department.
    """
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Employee)
        .filter(Employee.departamento == "ventas")
        .order_by(Employee.id.asc()),
        Employee.id,
        sum_(Employee.salario).over(
            partition_by=[Employee.departamento], order_by=[Employee.id.asc()]
        ),
    )
    # A `SUM` is typed nullable, and a NULL turning into 0 still fails the comparison below, so the
    # coercion narrows without hiding anything.
    running = [(row_id, 0 if total is None else int(total)) for row_id, total in rows]

    assert running == [(1, 100), (2, 200), (3, 250)], (
        "a running total, not the total repeated"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_lag_returns_null_on_the_first_row(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Verifies that `LAG` gives NULL where there is no previous row: hence its optional type."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Employee)
        .filter(Employee.departamento == "ventas")
        .order_by(Employee.id.asc()),
        lag(Employee.salario).over(order_by=[Employee.id.asc()]),
    )
    previous = [row[0] for row in rows]

    assert [None if value is None else int(value) for value in previous] == [
        None,
        100,
        100,
    ]
