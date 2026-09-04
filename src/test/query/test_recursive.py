"""`WITH RECURSIVE`: walking an entire hierarchy with ONE query.

The last piece of 2.9, and the only one that brings a NEW capability. The non-recursive CTE would be
sugar over something the ORM already knows how to do -scalar subqueries, `IN (SELECT ...)`,
correlated `EXISTS`, correlated aggregates-, so it does not get built just for the sake of building.

Recursion is another matter: "every descendant of this category" cannot be written with subqueries.
Either you make N+1 queries going down level by level, or you need `WITH RECURSIVE`. There is no
third option, and that is why this one is worth paying for.

It fits in like the compound queries do: the same contract as a query (`model`, `has_includes`,
`to_sql`), so the session runs it down the usual path. And the params are again concatenated in
TEXTUAL ORDER, which with positional placeholders is correctness, not a convenience.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    PostgresDialect,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeToOne,
    snake_int,
    snake_model,
    snake_str,
    snake_to_one,
)
from snakeorm.core.exceptions import SnakeEmitError

_DIALECT = PostgresDialect()


@snake_model(table="rec_categories")
class Category(SnakeModel):
    """The classic tree: every row points at its parent in the SAME table."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    parent_id: SnakeColumn[int | None] = snake_int()
    name: SnakeColumn[str] = snake_str()
    parent: SnakeToOne["Category | None"] = snake_to_one(parent_id)


@snake_model(table="rec_ajena")
class Ajena(SnakeModel):
    """Another model, to prove the hop demands columns from the table that recurses."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    category_id: SnakeColumn[int] = snake_int()


def _descendientes(root: int = 1) -> object:
    """Every descendant of a category, at any depth."""
    return (
        SnakeQuery(Category)
        .filter(Category.id == root)
        .recursive(on=(Category.parent_id, Category.id))
    )


def test_it_emits_a_recursive_cte() -> None:
    """Checks the shape: `WITH RECURSIVE ... UNION ALL ...` and a final SELECT over the CTE."""
    sql, _ = _descendientes().to_sql(_DIALECT)  # type: ignore[attr-defined]

    assert sql.startswith("WITH RECURSIVE")
    assert " UNION ALL " in sql, "the recursive step accumulates without deduplicating"
    assert sql.rstrip().endswith('FROM "snake_rec"')


def test_the_step_joins_the_table_against_the_accumulated_rows() -> None:
    """The recursive step joins the table to itself THROUGH the CTE: that is where the recursion lives."""
    sql, _ = _descendientes().to_sql(_DIALECT)  # type: ignore[attr-defined]

    assert 'JOIN "snake_rec" ON' in sql
    assert '"snake_src"."parent_id" = "snake_rec"."id"' in sql
    # The alias is not cosmetic: the CTE has the SAME columns as the table, so a bare name would be
    # ambiguous and Postgres would reject the query. The test against the real engine caught it.
    assert 'AS "snake_src"' in sql


def test_the_anchor_parameters_come_first() -> None:
    """The ANCHOR params come first: they are the ones that appear earlier in the string.

    With positional `%s`, the database matches parameters by position. A different order would not
    give an error: it would give a different query, with the filter applied to something else.
    """
    query = (
        SnakeQuery(Category)
        .filter(Category.id == 7)
        .recursive(on=(Category.parent_id, Category.id))
        .limit(50)
    )
    sql, params = query.to_sql(_DIALECT)

    assert params == (7, 50)
    assert sql.index("%s") < sql.rindex("%s")


def test_it_carries_the_model_like_any_query() -> None:
    """It honours the session contract: that is why it runs with no special path of its own."""
    query = _descendientes()

    assert query.model is Category  # type: ignore[attr-defined]
    assert query.has_includes is False  # type: ignore[attr-defined]


def test_ordering_and_limit_apply_to_the_result() -> None:
    """The ordering and the limiting belong to the RESULT, not to the anchor nor to the step."""
    sql, _ = (
        _descendientes()
        .order_by(Category.name.asc())  # type: ignore[attr-defined]
        .limit(10)
        .to_sql(_DIALECT)
    )

    assert sql.index('FROM "snake_rec"') < sql.index("ORDER BY")
    assert sql.index("ORDER BY") < sql.index("LIMIT")


def test_an_anchor_with_includes_is_refused() -> None:
    """Same reason as in a UNION: loaded relations do not survive the CTE."""
    from snakeorm.linker import snake_link

    snake_link()
    with pytest.raises(SnakeEmitError, match="include"):
        SnakeQuery(Category).include(Category.parent).recursive(
            on=(Category.parent_id, Category.id)
        )


def test_a_narrowed_anchor_is_refused() -> None:
    """The CTE's columns are the TABLE's, so an anchor that narrows them cannot line up.

    The step selects every column of the table and the anchor would select two: the `UNION` inside
    the CTE has a different width on each side and the engine rejects it. Refusing at build time
    says which knob caused it, which the engine's message cannot.
    """
    narrowed = SnakeQuery(Category).only(Category.name)

    with pytest.raises(SnakeEmitError, match="only"):
        narrowed.recursive(on=(Category.parent_id, Category.id))


def test_the_join_columns_must_belong_to_the_model() -> None:
    """Checks that the hop columns belong to THIS table: otherwise the recursion never closes.

    A recursion is a table joining ITSELF through what has already been accumulated. A column from
    another model would be emitted all the same -the name exists- and would produce a JOIN against a
    column that is not in that table: an engine error, or worse, a name collision and absurd results.
    """
    with pytest.raises(SnakeEmitError, match="rec_categories"):
        SnakeQuery(Category).recursive(on=(Ajena.category_id, Category.id))


def test_by_default_the_step_still_accumulates_with_union_all() -> None:
    """The default does not move: with no `distinct`, the step is joined with `UNION ALL`.

    It is the assertion that guards everybody who was already calling `recursive()`. The operator
    is what decides whether a walk ends, so a change of default would be a change of behaviour
    dressed up as a new parameter.
    """
    sql, _ = _descendientes().to_sql(_DIALECT)  # type: ignore[attr-defined]

    assert " UNION ALL " in sql


def test_distinct_joins_the_step_with_a_plain_union() -> None:
    """`distinct=True` emits `UNION` (which in SQL is `UNION DISTINCT`) instead of `UNION ALL`.

    That is the whole mechanism: every step drops the rows already accumulated, so a lap that
    repeats contributes nothing and the recursion stops on its own.
    """
    sql, _ = (
        SnakeQuery(Category)
        .filter(Category.id == 1)
        .recursive(on=(Category.parent_id, Category.id), distinct=True)
        .to_sql(_DIALECT)
    )

    assert " UNION " in sql
    assert "UNION ALL" not in sql, (
        "`UNION ALL` is exactly what `distinct=True` asked to drop"
    )


def test_the_operator_survives_the_chaining_that_comes_after() -> None:
    """`order_by()`/`limit()` return a NEW recursion, and the operator has to travel with it.

    They are `replace()` on a frozen dataclass, so a field left out of the copy would silently
    revert to the default -back to `UNION ALL`- on the very calls that read most naturally.
    """
    sql, params = (
        SnakeQuery(Category)
        .filter(Category.id == 1)
        .recursive(on=(Category.parent_id, Category.id), distinct=True)
        .order_by(Category.name.asc())
        .limit(10)
        .to_sql(_DIALECT)
    )

    assert "UNION ALL" not in sql
    assert " UNION " in sql
    assert params == (1, 10)
    assert sql.index("ORDER BY") < sql.index("LIMIT")


def test_ordering_a_recursion_by_a_relationship_is_refused() -> None:
    """`order_by(Category.parent.name)` is refused: the CTE's SELECT has no table to JOIN to.

    The same defect as the compound's, and the same guard. The `SELECT ... FROM cte` the ordering
    hangs off carries only the CTE's columns, so the hop was dropped and the key was written as the
    bare `"name"` — which is a column this very model owns. Valid SQL, wrong rows, no error.
    """
    with pytest.raises(SnakeEmitError, match="parent.name"):
        (
            SnakeQuery(Category)
            .filter(Category.id == 1)
            .recursive(on=(Category.parent_id, Category.id))
            # A nullable to-one reads as `type[Category] | type[None]` at class access.
            .order_by(Category.parent.name)  # type: ignore[union-attr]
        )
