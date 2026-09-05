"""Rendering a `SnakeCondition` to Python code: the piece that enables CHECKs and partial indexes.

A CHECK constraint and a partial index store a CONDITION in the metadata, and a migration is a
Python file that must rebuild it exactly. `build_condition` serializes the boolean AST.

How the round-trip is checked: the AST nodes use equality by IDENTITY (`eq=False`, because their
`__eq__` builds comparisons instead of returning `bool`), so they cannot be compared with `==`.
They are compared by their FINGERPRINT: the `(sql, params)` they emit. Same SQL and same parameters
is structural equivalence, and besides it is the only thing that truly matters.

What is NOT renderable is rejected LOUDLY. It is not a shortcoming: a subquery inside a CHECK is not
accepted by Postgres either, so the rejection is correctness.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.expressions import (
    SnakeCondition,
    SnakeExists,
    SnakeExpr,
    SnakeInSubquery,
    SnakeSubquery,
    SnakeTupleIn,
)
from snakeorm.migration.render import render_condition
from snakeorm.sql.condition import emit_condition

_DIALECT = PostgresDialect()

_AGE = SnakeExpr[int](path=("age",))
_NAME = SnakeExpr[str](path=("name",))
_CITY = SnakeExpr[str](path=("city",))


def _fingerprint(condition: SnakeCondition) -> tuple[str, tuple[object, ...]]:
    """The emittable fingerprint of a condition: `(sql, params)`. The identity that must survive."""
    return emit_condition(condition, _DIALECT)


def _round_trip(condition: SnakeCondition) -> SnakeCondition:
    """Renders the condition to code, executes it and returns the rebuilt condition."""
    source, imports = render_condition(condition)
    namespace: dict[str, object] = {}
    exec(
        compile("\n".join([*imports, f"result = {source}"]), "<cond>", "exec"),
        namespace,
    )  # noqa: S102
    rebuilt = namespace["result"]
    assert isinstance(rebuilt, SnakeCondition)
    return rebuilt


def _assert_round_trips(condition: SnakeCondition) -> None:
    """Demands that the rebuilt condition emit EXACTLY the same SQL and the same params."""
    assert _fingerprint(_round_trip(condition)) == _fingerprint(condition)


def test_comparison_round_trips() -> None:
    """A simple comparison (`age >= 18`) is rebuilt identical."""
    _assert_round_trips(_AGE >= 18)


def test_every_comparison_operator_round_trips() -> None:
    """The six comparison operators survive the journey."""
    for condition in (
        _AGE == 18,
        _AGE != 18,
        _AGE < 18,
        _AGE <= 18,
        _AGE > 18,
        _AGE >= 18,
    ):
        _assert_round_trips(condition)


def test_boolean_composition_round_trips() -> None:
    """Nested AND, OR and NOT are rebuilt with the same structure and the same order."""
    _assert_round_trips((_AGE >= 18) & (_NAME == "Ana"))
    _assert_round_trips((_AGE >= 18) | (_NAME == "Ana"))
    _assert_round_trips(~((_AGE >= 18) & (_NAME == "Ana")))
    _assert_round_trips(((_AGE > 0) & (_AGE < 100)) | (_NAME != "x"))


def test_null_checks_round_trip() -> None:
    """`IS NULL` and `IS NOT NULL` are rebuilt."""
    _assert_round_trips(_NAME.is_null())
    _assert_round_trips(_NAME.is_not_null())


def test_in_list_round_trips() -> None:
    """An `IN (...)` keeps its values and their order (the params are positional)."""
    _assert_round_trips(_CITY.in_(["Bilbao", "Gasteiz", "Donostia"]))


def test_like_round_trips() -> None:
    """A `LIKE` keeps its pattern."""
    _assert_round_trips(_NAME.like("An%"))


def test_arithmetic_inside_a_condition_round_trips() -> None:
    """Arithmetic is a VALUE, and it also has to survive inside the condition."""
    _assert_round_trips((_AGE + 1) > 3)
    _assert_round_trips((_AGE * 2 - 1) <= 99)


def test_literal_kinds_round_trip() -> None:
    """The accepted literals (bool, int, float, str, None) travel without losing their type."""
    _assert_round_trips(_NAME == "text with 'quotes'")
    _assert_round_trips(_AGE == 0)
    _assert_round_trips(_AGE != None)  # noqa: E711 -- on purpose: it produces IS NOT NULL


def test_deep_path_is_preserved() -> None:
    """A deep navigation path is kept whole (the expression indexes need it)."""
    deep: SnakeExpr[str] = SnakeExpr(path=("car", "brand", "name"))
    _assert_round_trips(deep == "Seat")


def test_generated_source_declares_its_imports() -> None:
    """The render returns the imports too: a migration file has to be able to run."""
    source, imports = render_condition(_AGE >= 18)

    assert "SnakeComparison" in source
    assert any("from snakeorm.expressions import" in line for line in imports)


@pytest.mark.parametrize(
    ("name", "node"),
    [
        (
            "EXISTS",
            SnakeExists(
                child_schema="public", child_name="makers", pairs=(("nation_id", "id"),)
            ),
        ),
        (
            "IN (subconsulta)",
            SnakeInSubquery(
                left=_AGE, subquery=SnakeSubquery(schema="public", name="t", column="c")
            ),
        ),
        (
            "constructor de fila",
            SnakeTupleIn(columns=(_AGE, _NAME), rows=((1, "a"),)),
        ),
    ],
)
def test_non_renderable_nodes_are_rejected_loudly(
    name: str, node: SnakeCondition
) -> None:
    """Verifies that what cannot be written to a file fails CLEARLY, not in silence.

    None of these fits in a CHECK: Postgres does not accept subqueries there either. The rejection
    is correctness, not a limitation, and the message has to say which node it was.
    """
    with pytest.raises(SnakeModelDefinitionError, match=type(node).__name__):
        render_condition(node)
