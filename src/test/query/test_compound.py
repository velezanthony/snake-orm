"""Set operations: `UNION`, `UNION ALL`, `EXCEPT`, `INTERSECT`.

This is the piece of 2.9 that DOES change the shape. Windows fitted in as just another value; a
`UNION` is not a clause you add to a SELECT, it is the COMPOSITION of two entire SELECTs, and until
now there was no object representing "a query already compiled and composable": `to_sql()` returned
`(str, params)` and that was the end of it.

`SnakeCompound` is that object, and it turns out to be the minimal honest IR: every node knows how to
produce `(sql, params)` and composing is concatenating in TEXTUAL ORDER. With Postgres's positional
`%s` placeholder that is not a convenience, it is correctness: the params list has to run in the same
order the `%s` appear in the string.

The type guarantees what SQL does not: unioning two queries of different models does not compile.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SQLiteDialect,
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
from snakeorm.linker import snake_link

_DIALECT = PostgresDialect()


@snake_model(table="cmp_customers")
class CompositeCustomer(SnakeModel):
    """The target of the relation: it is needed to test that `include` gets rejected."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="cmp_orders")
class Order(SnakeModel):
    """A minimal model for composing queries."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    status: SnakeColumn[str] = snake_str()
    amount: SnakeColumn[int] = snake_int()
    customer_id: SnakeColumn[int] = snake_int()
    customer: SnakeToOne[CompositeCustomer] = snake_to_one(customer_id)


def _open_orders() -> SnakeQuery[Order]:
    """A query with one parameter, to keep an eye on the param order when composing."""
    return SnakeQuery(Order).filter(Order.status == "open")


def _large_orders() -> SnakeQuery[Order]:
    """Another query, with a parameter of its own."""
    return SnakeQuery(Order).filter(Order.amount > 500)


def test_union_emits_both_branches_in_order() -> None:
    """Checks the basic composition: both branches, with their operator in between."""
    sql, params = _open_orders().union(_large_orders()).to_sql(_DIALECT)

    assert " UNION " in sql
    assert sql.count("SELECT") == 2
    assert params == ("open", 500), "the params go in the TEXTUAL ORDER of the branches"


def test_the_parameters_follow_the_textual_order_not_the_call_order() -> None:
    """THE detail that makes composition correct with POSITIONAL placeholders.

    With `%s` the database does not know which parameter is which: it matches them by position. If
    composing concatenated the params in any other order, the query would not fail - it would return
    the WRONG rows, which is infinitely worse.
    """
    sql, params = _large_orders().union(_open_orders()).to_sql(_DIALECT)

    assert params == (500, "open"), "swapping the branches swaps the params"
    assert sql.index("%s") < sql.rindex("%s")


def test_union_all_keeps_duplicates_and_union_does_not() -> None:
    """Checks that they are emitted as DIFFERENT operators: they are not synonyms."""
    assert (
        " UNION ALL " in _open_orders().union_all(_large_orders()).to_sql(_DIALECT)[0]
    )
    assert (
        " UNION ALL " not in _open_orders().union(_large_orders()).to_sql(_DIALECT)[0]
    )


def test_except_and_intersect_are_available() -> None:
    """Checks the other two set operations. `except_` carries an underscore: it is a reserved word."""
    assert " EXCEPT " in _open_orders().except_(_large_orders()).to_sql(_DIALECT)[0]
    assert (
        " INTERSECT " in _open_orders().intersect(_large_orders()).to_sql(_DIALECT)[0]
    )


def test_order_by_on_a_compound_is_not_table_qualified() -> None:
    """THE trap of the compound: the ORDER BY cannot carry a table alias.

    The result of a `UNION` is neither of the two tables: it is a new set whose columns are those of
    the PROJECTION. An `ORDER BY "cmp_orders"."id"` there does not merely sort oddly - Postgres
    rejects it. That is why the key is emitted bare.
    """
    sql, _ = (
        _open_orders().union(_large_orders()).order_by(Order.id.desc()).to_sql(_DIALECT)
    )

    assert sql.endswith('ORDER BY "id" DESC')
    assert '"cmp_orders"."id" DESC' not in sql


def test_limit_and_offset_apply_to_the_whole_compound() -> None:
    """Checks that the LIMIT goes AT THE END: it bounds the unioned result, not one branch."""
    sql, params = (
        _open_orders().union(_large_orders()).limit(10).offset(5).to_sql(_DIALECT)
    )

    assert sql.index(" UNION ") < sql.index("LIMIT")
    assert params[-2:] == (10, 5), "the LIMIT/OFFSET travels parametrised too"


def test_compounds_nest() -> None:
    """Checks that a compound can be composed again: it is closed over itself."""
    sql, params = (
        _open_orders().union(_large_orders()).intersect(_open_orders()).to_sql(_DIALECT)
    )

    assert " UNION " in sql and " INTERSECT " in sql
    assert params == ("open", 500, "open")


def test_a_compound_carries_the_model_for_row_mapping() -> None:
    """Checks that the compound knows which model its rows belong to: that is what the session needs."""
    composite = _open_orders().union(_large_orders())

    assert composite.model is Order
    assert composite.has_includes is False


def test_a_branch_with_includes_is_refused() -> None:
    """Checks that composing branches with `.include(...)` is rejected instead of silently dropped.

    An `.include()` loads relations with JOINs and extra queries, and none of that survives a
    UNION: the columns of the set are those of the projection, full stop. Accepting it and handing
    back objects without their relations would be the same old silent failure.
    """
    snake_link()
    con_include = SnakeQuery(Order).include(Order.customer)
    sin_include = SnakeQuery(Order).filter(Order.customer_id == 1)

    # It is rejected wherever the include sits: it does not matter which branch carries it.
    with pytest.raises(SnakeEmitError, match="include"):
        con_include.union(sin_include)

    with pytest.raises(SnakeEmitError, match="include"):
        sin_include.union(con_include)


def test_composing_two_different_models_is_refused() -> None:
    """Checks the RUNTIME backup to the type lock: unioning different models is rejected.

    The type already prevents it (`SnakeQuery[T].union(other: SnakeQuery[T])`), but the type would be
    the only guard and this project already decided that is not enough: the read-only lock on views
    carries a runtime guard of its own "for the gap left by a user who turns the checker off or gets
    there by a dynamic route".

    And here the gap is EXPENSIVE. SQL only demands that the number and the types of the columns line
    up, so a `UNION` between two similarly shaped tables runs perfectly happily - and the session
    instantiates ALL the rows as the model of the first branch. The row from the second table comes
    back with its values stuffed into the wrong fields, without a single error.
    """
    with pytest.raises(SnakeEmitError, match="both queries be of the SAME model"):
        SnakeQuery(Order).union(SnakeQuery(CompositeCustomer))  # type: ignore[arg-type]


def test_a_compound_of_whole_rows_projects_everything() -> None:
    """No branch narrows anything, so the set is whole rows and the session maps the whole plan."""
    assert _open_orders().union(_large_orders()).projected_columns is None


def test_a_compound_carries_the_projection_of_its_branches() -> None:
    """A narrowed branch narrows the SET, and the compound has to say so out loud.

    The session maps by ASKING which columns were projected, never by counting the row's width. A
    compound that could not answer was read as whole rows, and the values of an `only()` landed on
    the wrong attributes.
    """
    narrow = (
        _open_orders().only(Order.amount).union_all(_large_orders().only(Order.amount))
    )

    assert narrow.projected_columns == frozenset({"id", "amount"})


def test_composing_two_different_projections_is_refused() -> None:
    """Two branches that name DIFFERENT columns line up positionally, and SQL is happy with it.

    `SELECT id, amount UNION SELECT id, status` compiles wherever the types agree, and every row
    comes back instantiated against ONE of the two projections: half the answer with its values in
    the wrong fields. It is the same hole the model guard closes, one level down.
    """
    with pytest.raises(SnakeEmitError, match="the SAME columns"):
        _open_orders().only(Order.amount).union(_large_orders().only(Order.status))


def test_a_locked_branch_is_refused() -> None:
    """Checks that a `for_update()` on a branch is cut off at COMPOSE time, not by the engine.

    Postgres forbids it (`FOR UPDATE is not allowed with UNION/INTERSECT/EXCEPT`) because the result
    of a compound is not rows of any one concrete table, so there is nothing to lock. Finding out
    while writing the query is better than finding out while running it, and along the way the
    message can say what the engine's does not: what to do instead.
    """
    with pytest.raises(SnakeEmitError, match="for_update"):
        SnakeQuery(Order).for_update().union(SnakeQuery(Order))

    with pytest.raises(SnakeEmitError, match="for_update"):
        SnakeQuery(Order).union(SnakeQuery(Order).for_update())


def test_a_recursive_query_is_a_valid_branch() -> None:
    """A recursive query CAN be a branch of a set, and the type has to allow it.

    It was checked against Postgres: `(SELECT ...) UNION (WITH RECURSIVE ... SELECT ...)` is valid and
    returns the right thing. The original type left it out, so it forbade code that works.

    It is the OPPOSITE failure to the field specifier that was missing (a type that allowed too much
    and lied), but a wrong type all the same: one lies by saying yes, the other by saying no.
    """
    recursive_branch = SnakeQuery(Order).recursive(on=(Order.customer_id, Order.id))

    compound = SnakeQuery(Order).filter(Order.status == "open").union(recursive_branch)
    sql, _ = compound.to_sql(_DIALECT)

    assert " UNION " in sql
    assert "WITH RECURSIVE" in sql
    assert compound.model is Order


def test_a_bounded_branch_is_refused_where_branches_cannot_be_grouped() -> None:
    """A branch with its own `limit()` is refused on SQLite instead of emitting a different set.

    Without parentheses the `LIMIT` would read as belonging to the whole set, so the query would
    run and answer something else. The refusal existed and nothing asserted it.
    """
    compound = _open_orders().limit(1).union(_large_orders())

    with pytest.raises(SnakeEmitError, match="limit\\(\\)/offset\\(\\)"):
        compound.to_sql(SQLiteDialect())


def test_an_ordered_branch_is_refused_where_branches_cannot_be_grouped() -> None:
    """A branch with its own `order_by()` is inexpressible on SQLite, and has to say so.

    It emitted `SELECT ... ORDER BY id DESC UNION SELECT ...` and SQLite answered `ORDER BY clause
    should come after UNION not before`: a raw driver error for something the ORM already knows it
    cannot write. `limit()` on a branch was guarded and `order_by()` was not, though the parentheses
    are what both of them need.
    """
    compound = _open_orders().order_by(Order.id.desc()).union(_large_orders())

    with pytest.raises(SnakeEmitError, match="order_by"):
        compound.to_sql(SQLiteDialect())


def test_a_nested_compound_on_the_right_is_refused_where_branches_cannot_be_grouped() -> (
    None
):
    """THE silent one: `a.union(b.except_(c))` composes a DIFFERENT set on SQLite.

    Without parentheses the engine reads the operators left to right, so `A UNION B EXCEPT C` is
    `(A UNION B) EXCEPT C` — not what was written. It compiles, it runs and it answers wrong rows
    with no error: measured against three engines, 12 of the 16 operator pairs disagreed.
    """
    compound = _open_orders().union(_large_orders().except_(_open_orders()))

    with pytest.raises(SnakeEmitError, match="itself a UNION/EXCEPT/INTERSECT"):
        compound.to_sql(SQLiteDialect())


def test_a_nested_compound_on_the_left_still_compiles_without_parentheses() -> None:
    """Chaining to the LEFT is what the plain text already means, so it is NOT refused.

    `a.union(b).except_(c)` emits `A UNION B EXCEPT C`, and left-to-right reading gives exactly the
    grouping that was written. Measured over the whole 4x4 operator matrix against SQLite, Postgres
    and MySQL: the three agree on all sixteen. Refusing this would break the ordinary chain.
    """
    sql, _ = (
        _open_orders()
        .union(_large_orders())
        .except_(_open_orders())
        .to_sql(SQLiteDialect())
    )

    assert sql.count("UNION") == 1 and sql.count("EXCEPT") == 1
    assert "(" not in sql.split(" UNION ")[0]


def test_a_recursive_branch_is_refused_where_a_cte_cannot_go_in_a_branch() -> None:
    """A `WITH RECURSIVE` as a branch of a set works on Postgres ONLY, and the other two must say so.

    SQLite answered `near "WITH": syntax error` and MySQL error 1064 — raw driver errors naming
    neither the branch nor a way out, for a combination the type advertises as legal.
    """
    compound = _open_orders().union(
        SnakeQuery(Order).recursive(on=(Order.customer_id, Order.id))
    )

    for dialect in (SQLiteDialect(), MySQLDialect()):
        with pytest.raises(SnakeEmitError, match="WITH RECURSIVE inside a branch"):
            compound.to_sql(dialect)


def test_a_nested_compound_with_its_own_limit_is_refused_where_branches_cannot_be_grouped() -> (
    None
):
    """Chaining to the LEFT is safe until the left-hand set is BOUNDED, and then it is not.

    `(a UNION b LIMIT 1) EXCEPT c` has no parentheses to write on SQLite, so the `LIMIT` slides to
    the end and bounds the WHOLE set instead of the left-hand one. That is a different answer with
    no error — the same class of silence as the nested set on the right, one clause further along.
    A limit alone has to be enough to trigger it: bounded is limit OR offset, not both.
    """
    compound = _open_orders().union(_large_orders()).limit(1).except_(_open_orders())

    with pytest.raises(SnakeEmitError, match="its own limit"):
        compound.to_sql(SQLiteDialect())


def test_a_nested_compound_with_its_own_order_is_refused_where_branches_cannot_be_grouped() -> (
    None
):
    """The same for the ORDERING of the left-hand set, which needs the very same parentheses.

    `(a UNION b ORDER BY id) EXCEPT c` written flat orders the whole set, so the sort the caller
    asked of one half silently becomes the sort of the result.
    """
    compound = (
        _open_orders().union(_large_orders()).order_by(Order.id).except_(_open_orders())
    )

    with pytest.raises(SnakeEmitError, match="its own limit"):
        compound.to_sql(SQLiteDialect())
