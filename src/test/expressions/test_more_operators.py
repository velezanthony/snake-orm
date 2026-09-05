"""The operators that were missing: BETWEEN, ILIKE, startswith/endswith/contains and NOT IN.

All of them are SUGAR over nodes that already exist, and that is on purpose: every new AST node is
one more place where the emitter, the renderer and `condition_paths` can forget something. `between`
is an AND of two comparisons; `startswith` is a LIKE with the pattern properly escaped. Zero new
nodes, zero places to forget.

The exception is `ILIKE`, which is a node of its own (it carries a flag): case-insensitivity cannot
be expressed with the ones already there without losing the intent.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeUnsupportedFeature, SnakeValueError
from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.fields import SnakeColumn, snake_int, snake_json
from snakeorm.model import SnakeModel
from snakeorm.sql.condition import emit_condition

_DIALECT = PostgresDialect()
_AGE = SnakeExpr[int](path=("age",))
_NAME = SnakeExpr[str](path=("name",))


def _sql(condition: object) -> tuple[str, tuple[object, ...]]:
    """Emits the condition down to `(sql, params)`."""
    return emit_condition(condition, _DIALECT)  # type: ignore[arg-type]


def test_between_is_two_comparisons() -> None:
    """Checks that `between` emits the inclusive range, with both ends parameterised."""
    sql, params = _sql(_AGE.between(18, 65))
    assert sql == '("age" >= %s AND "age" <= %s)'
    assert params == (18, 65)


def test_not_in_negates_the_membership() -> None:
    """Checks that `not_in` is the negation of IN, not a node of its own."""
    sql, params = _sql(_NAME.not_in(["Ana", "Iker"]))
    assert sql == 'NOT ("name" IN (%s, %s))'
    assert params == ("Ana", "Iker")


def test_ilike_is_case_insensitive() -> None:
    """Checks that `ilike` emits ILIKE: the only one that really does need its own node."""
    sql, params = _sql(_NAME.ilike("an%"))
    assert sql == '"name" ILIKE %s'
    assert params == ("an%",)


def test_startswith_escapes_the_wildcards_of_the_value() -> None:
    """THE DETAIL THAT MATTERS: a `%` inside the value is DATA, not a wildcard.

    `startswith("100%")` has to look for a literal "100%", not "100" followed by anything at all.
    Without escaping, the filter would return too much and nobody would notice.
    """
    sql, params = _sql(_NAME.startswith("100%"))
    assert (
        sql == "\"name\" LIKE %s ESCAPE '\\'"
    )  # with ESCAPE or SQLite ignores the `\`
    assert params == ("100\\%%",)


def test_startswith_endswith_and_contains_anchor_the_pattern() -> None:
    """Checks where the wildcard goes in each one: at the end, at the front, and on both sides."""
    assert _sql(_NAME.startswith("an"))[1] == ("an%",)
    assert _sql(_NAME.endswith("ez"))[1] == ("%ez",)
    assert _sql(_NAME.contains("nd"))[1] == ("%nd%",)


def test_the_case_insensitive_variants_use_ilike() -> None:
    """Checks that the `i` variants of all three use ILIKE (Postgres) with the same anchoring and ESCAPE."""
    assert _sql(_NAME.istartswith("an"))[0] == "\"name\" ILIKE %s ESCAPE '\\'"
    assert _sql(_NAME.icontains("nd"))[0] == "\"name\" ILIKE %s ESCAPE '\\'"


def test_an_underscore_in_the_value_is_escaped_too() -> None:
    """Checks that `_` (SQL's ONE-character wildcard) gets escaped too."""
    assert _sql(_NAME.contains("a_b"))[1] == ("%a\\_b%",)


def test_between_requires_a_sane_range() -> None:
    """Checks that an inverted range is rejected: no rows sit between 65 and 18, and it is not what you meant."""
    with pytest.raises(ValueError, match="between range is inverted"):
        _AGE.between(65, 18)


def test_the_new_operators_compose_with_and_or() -> None:
    """Checks that they are still plain conditions: they compose like everything else."""
    sql, params = _sql(_AGE.between(18, 65) & _NAME.istartswith("an"))
    assert sql == '(("age" >= %s AND "age" <= %s) AND "name" ILIKE %s ESCAPE \'\\\')'
    assert params == (18, 65, "an%")


def test_between_over_an_unordered_type_is_refused_by_the_orm() -> None:
    """A BETWEEN over a JSON column gets a `SnakeError`, not a bare `TypeError` from Python.

    `T` carries no bound —and cannot: bounding it would break `SnakeColumn[dict]`, which is a real
    column type— so `low > high` on two dicts raises `TypeError: '>' not supported`. That is
    Python's message about Python's operators, in the middle of building a query, and it leaves the
    reader working out which of their columns it was about.

    `json_get()` twelve lines above already translates its own refusal. This is the same move.
    """
    with pytest.raises(SnakeUnsupportedFeature, match="between"):
        _Doc.payload.between({"a": 1}, {"b": 2})


def test_an_inverted_between_range_is_a_snake_error_too() -> None:
    """The inverted range raised a bare `ValueError`, which no `except SnakeError` catches.

    `SnakeValueError` inherits from `ValueError`, so anybody already catching the old one keeps
    working — the change widens what can catch it and narrows nothing.
    """
    with pytest.raises(SnakeValueError, match="inverted"):
        _Doc.n.between(10, 1)

    with pytest.raises(ValueError, match="inverted"):
        _Doc.n.between(10, 1)


@snake_model(table="mo_docs")
class _Doc(SnakeModel):
    """A model with an ORDERABLE column and an unorderable one, for the two halves above."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    n: SnakeColumn[int] = snake_int()
    payload: SnakeColumn[dict[str, object]] = snake_json()
