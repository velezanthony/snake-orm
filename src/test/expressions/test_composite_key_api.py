"""The typed composite `IN`: `snake_keys(M).in_([snake_key(M).set(col, value), ...])`.

The query the API could not express. A caller wanting the pairs `(7, 3)` and `(9, 1)` had one `in_()`
per column available, which asks for the CARTESIAN PRODUCT — it also answers `(7, 1)` and `(9, 3)` —
and in a small fixture the two look identical. The node and the emitter were already here
(`SnakeTupleIn`, with its OR-of-ANDs fallback for an engine that declares no row constructor); what
was missing was a way for anybody outside the prefetch to build one.

WHY A BUILDER AND NOT A POSITIONAL TUPLE. `snake_tuple(a, b).in_([(7, 3)])` was measured and
rejected: with two columns of the SAME type a swapped pair passes mypy AND pyright and comes back
with the wrong rows in silence. It also needs one overload per arity, so it has a CEILING — and the
identifying relationships this ORM is built for widen their key one level at a time. Pairing each
column with its own value is what lets the checker bind the type per slot, at any width.

What the checker CANNOT know is how many slots a key has: a two-column key and a three-column one
are both `SnakeKey[M]`. Those failures are checked here, and they RAISE — a warning would be
followed by wrong rows, which is the outcome this ORM exists not to produce.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    PostgresDialect,
    SnakeColumn,
    SnakeCondition,
    SnakeModel,
    snake_int,
    snake_key,
    snake_keys,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions import SnakeExpr, SnakeTupleIn
from snakeorm.expressions.scalar import snake_upper
from snakeorm.sql import emit_condition


@snake_model(table="ck_stock")
class KeyedStock(SnakeModel):
    """A composite key plus two columns that are not part of it."""

    warehouse_id: SnakeColumn[int] = snake_int(primary_key=True)
    product_id: SnakeColumn[int] = snake_int(primary_key=True)
    city: SnakeColumn[str] = snake_str()
    units: SnakeColumn[int] = snake_int()


@snake_model(table="ck_depots")
class KeyedDepot(SnakeModel):
    """A DIFFERENT model, so that mixing the two has something to be refused against."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    code: SnakeColumn[str] = snake_str()


def _sql(condition: SnakeCondition) -> tuple[str, list[object]]:
    """The emitted SQL and its params, on a dialect that has the row constructor."""
    sql, params = emit_condition(condition, PostgresDialect())
    return sql, list(params)


def test_two_keys_emit_one_row_constructor_with_the_values_parametrised() -> None:
    """The shape SQL asks for, and not a value in the string: `(a, b) IN ((.., ..), (.., ..))`."""
    condition = snake_keys(KeyedStock).in_(
        [
            snake_key(KeyedStock)
            .set(KeyedStock.warehouse_id, 7)
            .set(KeyedStock.product_id, 3),
            snake_key(KeyedStock)
            .set(KeyedStock.warehouse_id, 9)
            .set(KeyedStock.product_id, 1),
        ]
    )

    sql, params = _sql(condition)

    assert sql == '("warehouse_id", "product_id") IN ((%s, %s), (%s, %s))'
    assert params == [7, 3, 9, 1]


def test_it_builds_the_node_the_emitter_already_knew() -> None:
    """A `SnakeTupleIn` and not a new node: the fallback for an engine without the row constructor
    already exists on that one, and a second node would have to grow its own copy."""
    condition = snake_keys(KeyedStock).in_(
        [
            snake_key(KeyedStock)
            .set(KeyedStock.warehouse_id, 7)
            .set(KeyedStock.product_id, 3)
        ]
    )

    assert isinstance(condition, SnakeTupleIn)


def test_the_order_of_the_columns_is_the_model_and_not_the_chaining() -> None:
    """Two keys chained in OPPOSITE orders emit the same SQL. This is correctness, not tidiness.

    The values of every tuple have to line up with the column list, and the caller chains in
    whatever order they like. An emitter that trusted each key's insertion order would put
    `(warehouse, product)` on the first row and `(product, warehouse)` on the second, and the engine
    would compare a warehouse against a product without a word — both are integers.
    """
    forwards = snake_keys(KeyedStock).in_(
        [
            snake_key(KeyedStock)
            .set(KeyedStock.warehouse_id, 7)
            .set(KeyedStock.product_id, 3)
        ]
    )
    backwards = snake_keys(KeyedStock).in_(
        [
            snake_key(KeyedStock)
            .set(KeyedStock.product_id, 3)
            .set(KeyedStock.warehouse_id, 7)
        ]
    )

    assert _sql(forwards) == _sql(backwards)


def test_the_canonical_order_is_declaration_order_and_not_alphabetical() -> None:
    """Pinned down explicitly: `warehouse_id` is declared first, and comes first, though `p` < `w`.

    Without this the test above would pass on an implementation that sorted by NAME, which agrees
    with declaration order in this model by luck and stops agreeing on the next one.
    """
    condition = snake_keys(KeyedStock).in_(
        [
            snake_key(KeyedStock)
            .set(KeyedStock.product_id, 3)
            .set(KeyedStock.warehouse_id, 7)
        ]
    )

    sql, params = _sql(condition)

    assert sql.startswith('("warehouse_id", "product_id")')
    assert params == [7, 3]


def test_columns_outside_the_key_work_just_as_well() -> None:
    """Nothing here is about PRIMARY keys: any tuple of columns is a legal row constructor."""
    condition = snake_keys(KeyedStock).in_(
        [snake_key(KeyedStock).set(KeyedStock.city, "Bilbao").set(KeyedStock.units, 4)]
    )

    sql, params = _sql(condition)

    assert sql == '("city", "units") IN ((%s, %s))'
    assert params == ["Bilbao", 4]


def test_a_scalar_expression_may_stand_in_a_slot_and_follows_the_columns() -> None:
    """A slot takes any scalar value, not only a bare column: `UPPER(city)` is a legal left side.

    It has NO declared position — it is not a column of the model — so the rule is written down
    here rather than left to be discovered: declared columns go in declaration order, and anything
    else follows them in the order it was chained. `units` therefore comes FIRST, though it was
    chained second. What matters is not which rule it is but that every key obeys the same one; the
    shape check refuses any list where they would not line up.

    The SAME expression object is reused across the two keys on purpose, and the guard further down
    explains what happens when it is not.
    """
    upper = snake_upper(KeyedStock.city)
    condition = snake_keys(KeyedStock).in_(
        [
            snake_key(KeyedStock).set(upper, "BILBAO").set(KeyedStock.units, 4),
            snake_key(KeyedStock).set(upper, "GIRONA").set(KeyedStock.units, 5),
        ]
    )

    sql, params = _sql(condition)

    assert sql.startswith('("units", UPPER("city")) IN'), sql
    assert params == [4, "BILBAO", 5, "GIRONA"]


def test_three_and_four_columns_widen_without_a_new_overload() -> None:
    """The width the positional tuple could not have: no arity limit, because there are no overloads."""
    wide = (
        snake_key(KeyedStock)
        .set(KeyedStock.warehouse_id, 1)
        .set(KeyedStock.product_id, 2)
        .set(KeyedStock.city, "Vigo")
        .set(KeyedStock.units, 3)
    )

    sql, params = _sql(snake_keys(KeyedStock).in_([wide]))

    assert (
        sql == '("warehouse_id", "product_id", "city", "units") IN ((%s, %s, %s, %s))'
    )
    assert params == [1, 2, "Vigo", 3]


# -- What the type system cannot count, and therefore has to raise ------------------------------


def test_a_key_with_no_slots_is_refused_and_says_which_model() -> None:
    """An empty key would emit `() IN (())`, which is not SQL on any of the three."""
    with pytest.raises(SnakeEmitError, match="KeyedStock"):
        snake_keys(KeyedStock).in_([snake_key(KeyedStock)])


def test_an_empty_list_of_keys_is_refused() -> None:
    """There is no `IN ()`. Refused where the caller is, not four layers down in the emitter."""
    with pytest.raises(SnakeEmitError, match="at least one"):
        snake_keys(KeyedStock).in_([])


def test_the_same_column_twice_is_refused_instead_of_letting_the_last_one_win() -> None:
    """Ambiguity stops. `(a, a) IN ((1, 2))` is answerable and is never what anybody meant.

    Letting the second `set` overwrite the first would be the ORM choosing between two things the
    caller asked for, which is the one behaviour this project refuses everywhere else too.
    """
    with pytest.raises(SnakeEmitError, match="warehouse_id"):
        snake_key(KeyedStock).set(KeyedStock.warehouse_id, 7).set(
            KeyedStock.warehouse_id, 9
        )


def test_keys_of_different_widths_in_the_same_list_are_refused() -> None:
    """Two columns on one key and three on another emits SQL no engine will parse.

    The checker cannot see this: both are `SnakeKey[KeyedStock]`, because a type does not count.
    """
    with pytest.raises(SnakeEmitError, match="2.*3|3.*2"):
        snake_keys(KeyedStock).in_(
            [
                snake_key(KeyedStock)
                .set(KeyedStock.warehouse_id, 7)
                .set(KeyedStock.product_id, 3),
                snake_key(KeyedStock)
                .set(KeyedStock.warehouse_id, 9)
                .set(KeyedStock.product_id, 1)
                .set(KeyedStock.units, 2),
            ]
        )


def test_keys_of_the_same_width_over_different_columns_are_refused() -> None:
    """The sharper half of the same failure, and the one a width check alone would miss.

    Both keys are two columns wide, so the shapes agree — and the second row's values would be
    compared against the FIRST row's columns. `units` against `product_id`: both integers, no
    complaint from anywhere, wrong rows back.
    """
    with pytest.raises(SnakeEmitError, match="units|product_id"):
        snake_keys(KeyedStock).in_(
            [
                snake_key(KeyedStock)
                .set(KeyedStock.warehouse_id, 7)
                .set(KeyedStock.product_id, 3),
                snake_key(KeyedStock)
                .set(KeyedStock.warehouse_id, 9)
                .set(KeyedStock.units, 1),
            ]
        )


def test_a_key_built_for_another_model_is_refused_at_runtime_too() -> None:
    """Both checkers already refuse this (`SnakeKey[M]` is invariant); the runtime says so as well.

    The type is the real guard, and it only guards whoever runs a checker. What a mixed list would
    otherwise emit is a column of one table inside a filter over another.
    """
    with pytest.raises(SnakeEmitError, match="KeyedDepot|KeyedStock"):
        snake_keys(KeyedStock).in_(
            [
                snake_key(KeyedStock)
                .set(KeyedStock.warehouse_id, 7)
                .set(KeyedStock.product_id, 3),
                snake_key(KeyedDepot).set(KeyedDepot.id, 9).set(KeyedDepot.code, "x"),  # type: ignore[list-item]
            ]
        )


def test_two_separately_built_expressions_are_refused_rather_than_assumed_equal() -> (
    None
):
    """A non-column slot is matched across keys by IDENTITY, and the refusal says so.

    Two `snake_upper(...)` calls build two objects the ORM cannot prove are the same expression —
    comparing them by shape would call `SUBSTRING(code, 1, 3)` and `SUBSTRING(code, 2, 4)` equal,
    which is a FALSE match and emits wrong SQL in silence. So it refuses, and the message says to
    bind the expression to a name and reuse it. It fails in closed, on purpose: the alternative
    fails in open.
    """
    with pytest.raises(SnakeEmitError, match="same expression object"):
        snake_keys(KeyedStock).in_(
            [
                snake_key(KeyedStock)
                .set(snake_upper(KeyedStock.city), "A")
                .set(KeyedStock.units, 1),
                snake_key(KeyedStock)
                .set(snake_upper(KeyedStock.city), "B")
                .set(KeyedStock.units, 2),
            ]
        )


def test_setting_a_slot_does_not_mutate_the_key_it_came_from() -> None:
    """`set` returns a NEW key. A shared prefix is a natural thing to write, and mutation would make
    the second branch either overwrite the first or trip the duplicate guard for no reason."""
    base = snake_key(KeyedStock).set(KeyedStock.warehouse_id, 7)
    left = base.set(KeyedStock.product_id, 3)
    right = base.set(KeyedStock.product_id, 4)

    _, left_params = _sql(snake_keys(KeyedStock).in_([left]))
    _, right_params = _sql(snake_keys(KeyedStock).in_([right]))

    assert left_params == [7, 3]
    assert right_params == [7, 4]


def test_a_column_of_another_model_in_a_slot_is_refused() -> None:
    """The hole the TYPE cannot close: `SnakeExpr` carries no model, only the column's type.

    `SnakeKey[M]`'s invariance guards the KEY's model, which is what stops a whole key of the wrong
    table joining the list. It says nothing about where each SLOT came from: `KeyedDepot.code` is a
    `SnakeExpr[str]` and so is `KeyedStock.city`, so both checkers accept either in a key of either
    model. What would come out is a column of one table inside a filter over another.

    Putting the model into the expression would close it and cost too much — a `join()` returns
    `SnakeJoinedQuery[T, M]` and is bi-rooted on purpose, so expressions of two models in one
    condition are legitimate there. The check is here instead, where the model IS known, and it is
    limited to a bare column name: a navigated path and a compound expression are resolved by the
    emitter and guarding them would need the linker.
    """
    with pytest.raises(SnakeEmitError, match="code"):
        snake_key(KeyedStock).set(KeyedDepot.code, "x")


def test_a_navigated_path_is_left_for_the_emitter_to_resolve() -> None:
    """The guard above is about a BARE column, and must not refuse what it cannot judge.

    A path with more than one element navigates a relationship, and whether the first hop exists is
    the linker's question, not this module's. Refusing it here would forbid a legal filter on the
    grounds that a check written for something else could not understand it.

    What is asserted is that it BUILDS, and nothing about the SQL. `emit_condition` on its own gets
    no `qualify`, so it resolves the path to its last element; the joins that give a navigated path
    its meaning are collected by `SnakeQuery.filter`, which reads `SnakeTupleIn`'s paths through
    `expressions/paths.py`. Asserting the bare emission here would be pinning down the answer to a
    question this call is not asking.
    """
    navigated: SnakeExpr[str] = SnakeExpr(path=("warehouse", "city"))

    key = snake_key(KeyedStock).set(navigated, "Bilbao").set(KeyedStock.units, 4)

    assert isinstance(snake_keys(KeyedStock).in_([key]), SnakeTupleIn)
