"""SnakeORM's typing contract: what it MUST type. Verified by mypy and pyright.

This file never runs: `assert_type` is a no-op at runtime and everything lives inside
functions nobody calls. Its worth is static. If a refactor breaks deep navigation or the
dual behaviour of the descriptors, mypy and pyright fail HERE, instead of the failure
reaching Postgres alive.

It is the safety net of the project's thesis: the typing does not lie.

`assert_type` compares the EXACT type (it does not accept subtypes), so it pins down the
real shape of the AST. When what matters is "this can be used as a condition", a variable
is annotated instead: that one does admit subtypes.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz

from decimal import Decimal
from typing import assert_type

from snakeorm.decorators import (
    SnakeResult,
    SnakeRow,
    snake_model,
    snake_result,
    snake_row,
    snake_view,
)
from snakeorm.expressions import (
    SnakeAggregate,
    SnakeDatePart,
    SnakeFuncCall,
    SnakeAnd,
    SnakeArith,
    SnakeComparison,
    SnakeCondition,
    SnakeExpr,
    SnakeInList,
    SnakeIsNull,
    SnakeLike,
    SnakeNot,
    SnakeOr,
    SnakeOrder,
    SnakeSubqueryAggregate,
    SnakeTupleIn,
    SnakeKey,
    snake_key,
    snake_keys,
)
from snakeorm.expressions.conditional import (
    SnakeCoalesce,
    SnakeNullIf,
    snake_coalesce,
    snake_nullif,
)
from snakeorm.expressions.functions import avg, count, max_, min_, sum_
from snakeorm.expressions.scalar import snake_date_trunc, snake_extract, snake_upper
from snakeorm.fields import (
    SnakeCollection,
    snake_decimal,
    SnakeColumn,
    SnakePrefetch,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_str,
    snake_column,
    snake_to_many,
    snake_to_one,
)
from snakeorm.metadata import SnakeServerDefault
from snakeorm.model import SnakeModel, SnakeView
from snakeorm.query import SnakeJoin, SnakeJoinedQuery, SnakeQuery
from snakeorm.drivers.asyncpsycopg import AsyncPsycopgDriver
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Maker, Nation, Truck


@snake_result
class NationStats(SnakeResult[Nation]):
    """Typed result container: the base row (Nation) plus a scalar aggregate."""

    nation: Nation
    maker_count: int


@snake_row
class Nomina(SnakeRow):
    """The DECLARED shape of a payroll function: scalars only, no base model."""

    employee_id: int
    bruto: Decimal
    neto: Decimal


def check_call_returns_a_typed_list_of_rows(session: SnakeSession) -> None:
    """`session.call("f", [1], into=Nomina)` types as `list[Nomina]`; `rows[0].bruto` is `Decimal`.

    The `into: type[R]` parameter, with `R` bound to `SnakeRow`, captures the real type and carries it
    into the list (the road running parallel to `annotate`). Every field of the @snake_row keeps the
    type it declared.
    """
    rows = session.call("calcular_nomina", [1234], into=Nomina)
    assert_type(rows, list[Nomina])
    assert_type(rows[0].bruto, Decimal)
    assert_type(rows[0].employee_id, int)


@snake_model(table="typing_events")
class TypingEvent(SnakeModel):
    """A model with a `server_default` column: the database fills `created_at` in, not the client."""

    id: SnakeColumn[int] = snake_auto()
    label: SnakeColumn[str] = snake_column()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(server_default=SnakeServerDefault.NOW)


def check_server_default_is_not_required_in_init() -> None:
    """A model with a `server_default` does NOT demand that field in `__init__` (the database fills it).

    It is the same contract as `snake_auto`: the `Literal[False]` signal on the overload leaves the
    column out of the constructor. Instance access stays typed (a value) and so does class access
    (an expression), because the descriptor does not change: it is only omitted from `__init__`.
    """
    event = TypingEvent(label="event")  # created_at is NOT passed: the server puts it there
    assert_type(event.created_at, SnakeUtc)
    assert_type(TypingEvent.created_at, SnakeExpr[SnakeUtc])


class ExampleTimestamped(SnakeModel):
    """An ABSTRACT base (it carries no @snake_model): it contributes id (auto) and created_at (server_default).

    It is not a table; it merely groups columns so that several models can inherit them without
    repeating them. The typing contract demands that inheritance does NOT degrade the child's typing.
    """

    id: SnakeColumn[int] = snake_auto()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )


@snake_model(table="typing_inherited_users")
class InheritedUser(ExampleTimestamped):
    """Inherits id and created_at from the abstract base; adds a name of its own."""

    name: SnakeColumn[str] = snake_column()


def check_inherited_column_class_access_is_typed() -> None:
    """CLASS access to an INHERITED column: a typed SQL expression (SnakeExpr), not the value.

    The base's descriptor resolves through the MRO exactly like one of its own: `User.created_at` is
    still `SnakeExpr[datetime]`. Inheritance introduces no `Any`.
    """
    assert_type(InheritedUser.created_at, SnakeExpr[SnakeUtc])
    assert_type(InheritedUser.name, SnakeExpr[str])


def check_inherited_column_instance_access_is_value(user: InheritedUser) -> None:
    """INSTANCE access to an inherited column: the real value, of the type declared on the base."""
    assert_type(user.created_at, SnakeUtc)
    assert_type(user.name, str)


def check_inherited_init_propagates_through_dataclass_transform() -> None:
    """The child's typed __init__ accepts the fields: its own `name`; id/created_at come from the database.

    `@dataclass_transform` on the `SnakeModel` base carries the inherited fields down through the
    inheritance, so the child's constructor includes them (the ones excluded by server_default/auto
    stay out). Verified with mypy AND pyright.
    """
    user = InheritedUser(name="x")  # id and created_at are NOT passed: the server fills them in
    assert_type(user.name, str)
    assert_type(user.created_at, SnakeUtc)


def check_class_access_yields_expressions() -> None:
    """CLASS access to a column: a typed SQL expression, not the value."""
    assert_type(Truck.model, SnakeExpr[str])
    assert_type(Truck.id, SnakeExpr[int])
    assert_type(Nation.name, SnakeExpr[str])


def check_instance_access_yields_values(truck: Truck, nation: Nation) -> None:
    """INSTANCE access to a column: the real value, of the declared type."""
    assert_type(truck.model, str)
    assert_type(truck.id, int)
    assert_type(nation.name, str)


def check_class_access_to_relation_yields_the_target_class() -> None:
    """CLASS access to a to-one relation: `type[M]`, so that navigation can carry on."""
    assert_type(Truck.maker, type[Maker])
    assert_type(Maker.nation, type[Nation])


def check_instance_access_to_relation_yields_the_object(truck: Truck) -> None:
    """INSTANCE access to a to-one relation: the related object."""
    assert_type(truck.maker, Maker)
    assert_type(truck.maker.nation, Nation)


def check_deep_navigation_is_typed() -> None:
    """THE CROWN JEWEL: `Truck.maker.nation.name` crosses two relations and lands on `SnakeExpr[str]`.

    Every hop fires the destination descriptor's CLASS overload all over again. No codegen,
    no type-checker plugin. It is the hand-rolled equivalent of TypeScript's mapped types.
    """
    assert_type(Truck.maker.name, SnakeExpr[str])
    assert_type(Truck.maker.nation_id, SnakeExpr[int])
    assert_type(Truck.maker.nation, type[Nation])
    assert_type(Truck.maker.nation.name, SnakeExpr[str])
    assert_type(Truck.maker.nation.id, SnakeExpr[int])


def check_deep_navigation_on_instances_yields_values(truck: Truck) -> None:
    """The same path, walked over an instance, returns values all the way down."""
    assert_type(truck.maker.nation.name, str)
    assert_type(truck.maker.nation.id, int)


def check_equality_never_yields_bool() -> None:
    """`==` and `!=` return `SnakeCondition`, NEVER `bool`: they may be a comparison or an IS NULL."""
    assert_type(Truck.model == "Ibiza", SnakeCondition)
    assert_type(Truck.model != "Ibiza", SnakeCondition)
    assert_type(Truck.maker.nation.name == "España", SnakeCondition)


def check_ordered_comparisons_yield_comparisons() -> None:
    """`<`, `<=`, `>`, `>=` can only produce a comparison (there is no NULL case)."""
    assert_type(Truck.id > 3, SnakeComparison)
    assert_type(Truck.id >= 3, SnakeComparison)
    assert_type(Truck.id < 3, SnakeComparison)
    assert_type(Truck.id <= 3, SnakeComparison)


def check_conditions_compose() -> None:
    """`&`, `|` and `~` compose conditions and return the matching AST node."""
    left = Truck.model == "Ibiza"
    right = Truck.maker.nation.name == "España"
    assert_type(left & right, SnakeAnd)
    assert_type(left | right, SnakeOr)
    assert_type(~left, SnakeNot)


def check_every_node_is_usable_as_a_condition() -> None:
    """Every node of the boolean AST can be passed wherever a `SnakeCondition` is expected.

    What is checked here is ASSIGNABILITY (subtypes allowed), which is the contract of `.filter()`.
    """
    comparison: SnakeCondition = Truck.id > 3
    like: SnakeCondition = Truck.model.like("Ib%")
    is_null: SnakeCondition = Truck.model.is_null()
    in_list: SnakeCondition = Truck.model.in_(["Ibiza", "M3"])
    conjunction: SnakeCondition = comparison & like
    negation: SnakeCondition = ~in_list
    _ = (comparison, like, is_null, in_list, conjunction, negation)


def check_helpers_yield_their_own_nodes() -> None:
    """The helpers produce their own concrete node: `like`, `in_`, `is_null`, `asc`/`desc`."""
    assert_type(Truck.model.like("Ib%"), SnakeLike)
    assert_type(Truck.model.in_(["Ibiza", "M3"]), SnakeInList)
    assert_type(Truck.model.is_null(), SnakeIsNull)
    assert_type(Truck.model.asc(), SnakeOrder)
    assert_type(Truck.maker.nation.name.desc(), SnakeOrder)


def check_arithmetic_yields_snake_arith() -> None:
    """Arithmetic over a column produces `SnakeArith[T]`, both the direct and the reflected form."""
    assert_type(Truck.id + 1, SnakeArith[int])
    assert_type(1 + Truck.id, SnakeArith[int])


def check_arithmetic_is_comparable() -> None:
    """A `SnakeArith` is just another value: `(col + 1) > 3` is a condition usable in filters."""
    result: SnakeCondition = (Truck.id + 1) > 3
    _ = result


def check_aggregate_constructors_are_typed() -> None:
    """The aggregate constructors pin down the result type, nullability INCLUDED.

    `count(...)` is always `int`: `COUNT` over zero rows is 0, never NULL. The rest ARE NULL over
    zero rows (`SELECT SUM(x) FROM t` with `t` empty returns one row holding NULL), so `avg` is
    `float | None` and `sum_/min_/max_` are `<the column's type> | None`. That `| None` is not
    pessimism: it is what the engine hands back, and leaving it out made the type lie.
    """
    assert_type(count(), SnakeAggregate[int])
    assert_type(count(Truck.id), SnakeAggregate[int])
    assert_type(count(Truck.id, distinct=True), SnakeAggregate[int])
    assert_type(avg(Truck.id), SnakeAggregate[float | None])
    assert_type(sum_(Truck.id), SnakeAggregate[int | None])
    assert_type(min_(Truck.id), SnakeAggregate[int | None])
    assert_type(max_(Truck.model), SnakeAggregate[str | None])


def check_aggregate_is_comparable_for_having() -> None:
    """An aggregate is comparable: `count() > 3` is a `SnakeCondition` usable in `.having(...)`."""
    condition: SnakeCondition = count() > 3
    _ = condition


def check_select_with_aggregate_is_typed(session: SnakeSession, query: SnakeQuery[Truck]) -> None:
    """`session.select(q, col, agg)` types as `list[tuple[...]]`, mixing columns and aggregates.

    The overload asks for `SnakeValue[A]` (their common base), so a column (`SnakeExpr[str]`) and an
    aggregate (`SnakeAggregate[int]`) live together in the same tuple without touching the machinery.
    """
    assert_type(session.select(query, Truck.model, count()), list[tuple[str, int]])
    assert_type(
        session.select(query, Truck.model, count(), avg(Truck.id)),
        list[tuple[str, int, float | None]],
    )


def check_annotate_is_typed(session: SnakeSession) -> None:
    """`session.annotate(q, Result, name=agg)` types as `list[Result]` (the main road).

    Against the escape hatch (which returns `object`), `@snake_result` gives a genuinely typed class:
    the list is `list[NationStats]`, the scalar keeps its type (`int`) and the base row is still a
    navigable model (`stats.nation.name` is `str`).
    """
    stats = session.annotate(SnakeQuery(Nation), NationStats, maker_count=count())
    assert_type(stats, list[NationStats])
    first = stats[0]
    assert_type(first.maker_count, int)
    assert_type(first.nation.name, str)


def check_to_many_class_access_yields_a_collection() -> None:
    """CLASS access to a to-many: `SnakeCollection[M]`, NOT the child's class nor its columns.

    The cardinality changes (there is more than one correct answer), so navigation is made
    EXPLICIT: collection operations only. `Nation.makers.name` (a child column) does NOT exist.
    """
    assert_type(Nation.makers, SnakeCollection[Maker])


def check_collection_any_is_a_condition() -> None:
    """`.any(...)` produces something assignable to `SnakeCondition`: usable in `.filter(...)`."""
    exists: SnakeCondition = Nation.makers.any()
    filtered: SnakeCondition = Nation.makers.any(Maker.name == "SEAT")
    negated: SnakeCondition = ~Nation.makers.any()
    # Deep navigation of the child inside the EXISTS keeps the type: `Maker.nation.name` is
    # `SnakeExpr[str]` by the class overload, and `.any(...)` still returns a `SnakeCondition`.
    navigated: SnakeCondition = Nation.makers.any(Maker.nation.name == "España")
    _ = (exists, filtered, negated, navigated)


def check_collection_count_is_comparable() -> None:
    """`.count()` is a comparable scalar value: `Nation.makers.count() > 3` is a condition."""
    result: SnakeCondition = Nation.makers.count() > 3
    _ = result


def check_collection_aggregates_are_typed() -> None:
    """Collection aggregates pin down their type AND their nullability, just like the constructors.

    Here the NULL is even easier to run into: a parent with NO children makes the correlated
    subquery aggregate zero rows. `.count()` gives 0 (`int`); `.sum_/.avg/.min_/.max_` give NULL,
    so they carry `| None`. Each one is a typed correlated scalar subquery, not `Any`.
    """
    assert_type(Nation.makers.count(), SnakeSubqueryAggregate[int])
    assert_type(Nation.makers.sum_(Maker.id), SnakeSubqueryAggregate[int | None])
    assert_type(Nation.makers.avg(Maker.id), SnakeSubqueryAggregate[float | None])
    assert_type(Nation.makers.min_(Maker.id), SnakeSubqueryAggregate[int | None])
    assert_type(Nation.makers.max_(Maker.id), SnakeSubqueryAggregate[int | None])


def check_collection_aggregates_are_comparable() -> None:
    """Every collection aggregate is comparable, hence assignable to `SnakeCondition` (usable in `.filter`)."""
    by_sum: SnakeCondition = Nation.makers.sum_(Maker.id) > 100
    by_avg: SnakeCondition = Nation.makers.avg(Maker.id) > 100.0
    by_min: SnakeCondition = Nation.makers.min_(Maker.id) == 0
    by_max: SnakeCondition = Nation.makers.max_(Maker.id) > 3
    _ = (by_sum, by_avg, by_min, by_max)


def check_bulk_write_distinct_and_subquery(session: SnakeSession) -> None:
    """PHASE 5: `distinct()` preserves the model, `update_where` returns `int`, `in_(subquery)` is a condition.

    `distinct()` is immutable and remains a `SnakeQuery[Truck]`. The bulk write takes typed
    (column, value) pairs (`Truck.id + 1` is a `SnakeArith[int]`, assignable to `object`) and returns
    the number of rows affected. A scalar subquery of the SAME type as the column is a valid `IN`,
    assignable to `SnakeCondition`.
    """
    query = SnakeQuery(Truck)
    assert_type(query.distinct(), SnakeQuery[Truck])
    affected: int = session.update_where(query, [(Truck.id, Truck.id + 1)])
    _ = affected
    subquery = SnakeQuery(Maker).as_scalar(Maker.id)
    condition: SnakeCondition = Truck.maker_id.in_(subquery)
    _ = condition


def check_join_returns_a_joined_query() -> None:
    """`.join()` onto a collection returns `SnakeJoinedQuery[Root, Child]`, a DIFFERENT kind of query."""
    assert_type(
        SnakeQuery(Nation).join(Nation.makers), SnakeJoinedQuery[Nation, Maker]
    )
    assert_type(
        SnakeQuery(Nation).join(Nation.makers, how=SnakeJoin.LEFT),
        SnakeJoinedQuery[Nation, Maker],
    )


def check_joined_right_is_the_child_class() -> None:
    """`joined.right` is `type[Maker]`: navigating it fires class access again, landing on a child column.

    That is what makes projecting child columns correct: `joined.right.name` is `SnakeExpr[str]`, with
    the prefixed path that gets qualified by the JOIN's alias (not by the root's).
    """
    joined = SnakeQuery(Nation).join(Nation.makers)
    assert_type(joined.right, type[Maker])
    assert_type(joined.right.name, SnakeExpr[str])
    assert_type(joined.right.id, SnakeExpr[int])


def check_select_over_a_joined_query_is_typed(session: SnakeSession) -> None:
    """`session.select(joined, parent.col, joined.right.col)` types the tuple exactly as in a SnakeQuery.

    Projecting an explicit JOIN returns multiplied TUPLES (one per child), and their typing is every
    bit as precise: `(str, str)` mixing a parent column with a child one.
    """
    joined = SnakeQuery(Nation).join(Nation.makers)
    assert_type(
        session.select(joined, Nation.name, joined.right.name), list[tuple[str, str]]
    )


def check_joined_query_chains_and_stays_projectable(session: SnakeSession) -> None:
    """The joined query chains filters and another `.join()`, and remains projectable."""
    joined = SnakeQuery(Nation).join(Nation.makers).filter(Nation.name == "España")
    assert_type(joined, SnakeJoinedQuery[Nation, Maker])
    chained = joined.join(joined.right.trucks)
    assert_type(chained, SnakeJoinedQuery[Nation, Truck])
    assert_type(
        session.select(chained, Nation.name, chained.right.model),
        list[tuple[str, str]],
    )


def check_prefetch_is_typed_and_chains() -> None:
    """`SnakePrefetch` is generic in the child: `.then(...)` only accepts relations of THAT child.

    `SnakePrefetch(Nation.makers)` is `SnakePrefetch[Maker]`; `.then(Maker.trucks)` (to-many) gives
    `SnakePrefetch[Truck]`; `.then(Maker.nation)` (to-one) gives `SnakePrefetch[Nation]`. The chain
    mixes both cardinalities and stays typed hop by hop, like the mapped types.
    """
    assert_type(SnakePrefetch(Nation.makers), SnakePrefetch[Maker])
    assert_type(SnakePrefetch(Nation.makers).then(Maker.trucks), SnakePrefetch[Truck])
    assert_type(SnakePrefetch(Nation.makers).then(Maker.nation), SnakePrefetch[Nation])
    assert_type(
        SnakePrefetch(Nation.makers).then(Maker.nation).then(Nation.makers).then(Maker.trucks),
        SnakePrefetch[Truck],
    )


def check_prefetch_filter_is_typed_and_chains() -> None:
    """`.filter()` on the prefetch keeps the level's type and stays chainable with `.then()`.

    The filter narrows WHICH CHILDREN are loaded at that level; it changes neither the cardinality nor
    the model of the hop, so `SnakePrefetch[Maker].filter(...)` is still `SnakePrefetch[Maker]`.
    """
    assert_type(
        SnakePrefetch(Nation.makers).filter(Maker.name == "x"), SnakePrefetch[Maker]
    )
    assert_type(
        SnakePrefetch(Nation.makers).filter(Maker.name == "x").then(Maker.trucks),
        SnakePrefetch[Truck],
    )
    assert_type(
        SnakePrefetch(Nation.makers).then(Maker.trucks).filter(Truck.id > 1),
        SnakePrefetch[Truck],
    )


def check_include_accepts_a_prefetch() -> None:
    """`query.include(SnakePrefetch(...))` still returns the same `SnakeQuery[T]` (the root untouched)."""
    query = SnakeQuery(Nation).include(SnakePrefetch(Nation.makers).then(Maker.trucks))
    assert_type(query, SnakeQuery[Nation])


@snake_model(table="typing_editors")
class Editor(SnakeModel):
    """A model whose to-many `books` points at a read-only VIEW (navigation towards the view)."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_column()
    books: SnakeToMany[EditorBooks] = snake_to_many("editor")


@snake_view(sql="SELECT editor_id, title FROM editor_books")
class EditorBooks(SnakeView):
    """A read-only view, navigable both ways (FK towards Editor plus the inverse from Editor)."""

    editor_id: SnakeColumn[int] = snake_column()
    title: SnakeColumn[str] = snake_column()
    editor: SnakeToOne[Editor] = snake_to_one(editor_id)


def check_query_over_a_view_is_typed(session: SnakeSession) -> None:
    """`session.all(SnakeQuery(view))` types as `list[View]`: a view is queried just like a model."""
    assert_type(session.all(SnakeQuery(EditorBooks)), list[EditorBooks])


def check_view_instance_columns_keep_their_type(row: EditorBooks) -> None:
    """INSTANCE access to a column of the view honours its declared type (`str`)."""
    assert_type(row.title, str)
    assert_type(row.editor_id, int)


def check_view_class_columns_yield_expressions() -> None:
    """CLASS access to a column of the view gives a typed SQL expression (just like a model)."""
    assert_type(EditorBooks.title, SnakeExpr[str])
    assert_type(EditorBooks.editor_id, SnakeExpr[int])


def check_navigation_from_view_to_model_is_typed(row: EditorBooks) -> None:
    """Navigation FROM the view to a model: class access gives `type[Editor]`; instance access, the object."""
    assert_type(EditorBooks.editor, type[Editor])
    assert_type(EditorBooks.editor.name, SnakeExpr[str])
    assert_type(row.editor.name, str)


def check_navigation_from_model_to_view_is_typed(editor: Editor) -> None:
    """Navigation TOWARDS the view: class access gives `SnakeCollection[View]`; instance access, `list[View]`."""
    assert_type(Editor.books, SnakeCollection[EditorBooks])
    assert_type(editor.books, list[EditorBooks])
    assert_type(editor.books[0].title, str)


@snake_model(table="typing_ledger")
class LedgerLine(SnakeModel):
    """The table a UNION view is built over: two disjoint slices of the same rows."""

    id: SnakeColumn[int] = snake_auto()
    amount: SnakeColumn[int] = snake_column()


@snake_view(
    query=SnakeQuery(LedgerLine)
    .filter(LedgerLine.amount < 0)
    .union(SnakeQuery(LedgerLine).filter(LedgerLine.amount > 1000)),
    name="typing_ledger_edges",
)
class LedgerEdges(SnakeView):
    """A view whose body is a SET OPERATION, which is what half the views in the world are.

    It ran correctly on the three engines while the parameter's annotation said `SnakeQuery`, so the
    only thing stopping it was the type — and a type narrower than the behaviour it describes sends
    the caller to `# type: ignore` over something the ORM does perfectly well.
    """

    id: SnakeColumn[int] = snake_column()
    amount: SnakeColumn[int] = snake_column()


def check_a_view_over_a_set_operation_is_queried_like_any_other(
    session: SnakeSession,
) -> None:
    """The rows of a UNION view type as the view's model, with no cast at the call site."""
    assert_type(session.all(SnakeQuery(LedgerEdges)), list[LedgerEdges])
    assert_type(LedgerEdges.amount, SnakeExpr[int])


def check_tuple_in_is_a_condition() -> None:
    """`SnakeTupleIn` (the row constructor for a composite FK) is assignable to `SnakeCondition`.

    Its columns are expressions (`SnakeExpr`, a subtype of `SnakeValue`); it is built from the tuple
    of child columns and one row per parent. It is the node that emits the composite select-in.
    """
    node: SnakeCondition = SnakeTupleIn(
        columns=(Truck.maker_id, Truck.id), rows=((1, 10), (2, 20))
    )
    _ = node


@snake_model(table="pos_precios")
class PosPrecio(SnakeModel):
    """A money column, to pin that comparing it against a bare integer type-checks."""

    id: SnakeColumn[int] = snake_auto()
    importe: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)


def check_a_money_column_compares_against_a_bare_integer() -> None:
    """`importe >= 0` type-checks: an `int` is accepted where the column declares `Decimal`.

    Python allows `Decimal("1") >= 0` and SQL allows `NUMERIC >= 0`; the ORM emitted the SAME SQL
    either way — measured, byte for byte, on all three dialects. So refusing it statically was the
    ORM being stricter than both the language and the database while gaining nothing, and paying for
    it in the most common domain there is: money.

    The promotion is added because it is EXACT. An integer has no fractional part, so `0` and
    `Decimal(0)` are the same number, and no rounding hides in the conversion.
    """
    assert_type(PosPrecio.importe >= 0, SnakeComparison)
    assert_type(PosPrecio.importe >= Decimal(0), SnakeComparison)


@snake_model(table="pos_existencias")
class PosExistencia(SnakeModel):
    """Two columns of the same type, to pin that comparing one against the other type-checks."""

    id: SnakeColumn[int] = snake_auto()
    cantidad: SnakeColumn[int] = snake_int()
    reservado: SnakeColumn[int] = snake_int()


def check_a_column_compares_against_another_column_of_its_type() -> None:
    """`cantidad > reservado` type-checks, and so does the arithmetic around it.

    The question is the most ordinary one a warehouse has —available is what is there minus what is
    promised— and it used to be inexpressible: the comparison bound the right-hand `SnakeExpr` as a
    parameter, so the SQL came out with the right shape and an object inside it, and the DRIVER was
    what complained.

    The arithmetic form already worked because arithmetic emits each operand by asking whether it is
    an expression or a value. Both forms are pinned here so that the day somebody narrows one of the
    two signatures, the checker says which.
    """
    assert_type(PosExistencia.cantidad > PosExistencia.reservado, SnakeComparison)
    assert_type(PosExistencia.cantidad - PosExistencia.reservado > 0, SnakeComparison)


def check_a_coalesce_with_a_literal_fallback_is_not_nullable() -> None:
    """`COALESCE(SUM(x), 0)` is an `int`, and the whole reason to write it is that it is.

    `sum_` is `int | None` and honestly so: a `SUM` over no rows is NULL on every engine. Wrapping it
    in a `COALESCE` with a literal is how that `None` is removed IN THE ENGINE, so the type has to
    lose it too — otherwise the declarator that exists to make a value non-null hands back a nullable
    one, and the caller has to `cast()` in a project whose rule is zero `Any`.

    Both parts are pinned: the argument is accepted (it is a `SnakeValue[int | None]` going into a
    parameter that used to demand `SnakeValue[int]`), and the result is `SnakeCoalesce[int]`.
    """
    assert_type(snake_coalesce(sum_(PosExistencia.cantidad), 0), SnakeCoalesce[int])


def check_a_coalesce_between_two_expressions_keeps_the_nullability() -> None:
    """With no literal fallback, nothing guarantees a value: `COALESCE(a, b)` is null when both are.

    This is the half that must NOT change. Widening the first case into "a COALESCE is never null"
    would be a lie the checker then defends.
    """
    assert_type(
        snake_coalesce(sum_(PosExistencia.cantidad), max_(PosExistencia.reservado)),
        SnakeCoalesce[int | None],
    )


def check_a_nullif_declares_the_null_it_introduces() -> None:
    """`NULLIF(x, 0)` can return NULL — that is the ONLY reason anybody writes it.

    THE EXACT MIRROR of the two cases above, and it was the half that lied. `snake_coalesce` REMOVES
    a `None` and says so; `snake_nullif` PUTS one in and did not: it typed `SnakeNullIf[int]` and
    handed back `None` at runtime, so a caller doing `x / snake_nullif(y, 0)` was told the result was
    an `int` by a checker this project asks people to trust.

    It is what the declarator is FOR. Guarding a division against zero means turning the zero into a
    NULL, so the nullability is not an edge case of `NULLIF` — it is its entire purpose.
    """
    assert_type(snake_nullif(PosExistencia.cantidad, 0), SnakeNullIf[int | None])


def check_arithmetic_propagates_the_nullability_of_its_operands() -> None:
    """`x / NULLIF(y, 0)` is nullable, and the type has to carry it out of the division.

    THIS IS NOT THE PROMOTION THAT WAS REFUSED, and the difference is the whole argument. Promoting
    `int` to `float` CHANGES what the engine computes —integer division or decimal— so it stays the
    caller's decision, made with `snake_cast`. Propagating a `None` changes NOTHING: `a + NULL` is
    NULL on the three engines, always, with no choice involved. Here the type is not deciding, it is
    finally describing what SQL already does.

    Without this, `snake_nullif` declaring its `None` honestly would have made the expression it
    exists for impossible to write, which is a worse place than the lie it replaced.
    """
    guarded = snake_nullif(PosExistencia.reservado, 0)
    assert_type(PosExistencia.cantidad * 100 / guarded, SnakeArith[int | None])


def check_arithmetic_between_non_nullable_operands_stays_non_nullable() -> None:
    """The half that must NOT move: no `None` in, no `None` out.

    Widening this into "arithmetic is always nullable" would hand every caller a `| None` to unwrap
    for nothing, which is the mirror failure of the one being fixed.
    """
    assert_type(PosExistencia.cantidad * 100, SnakeArith[int])
    assert_type(PosExistencia.cantidad / PosExistencia.reservado, SnakeArith[int])


@snake_model(table="pos_shipments")
class PosShipment(SnakeModel):
    """SIX columns, because the width is the whole argument for this API's shape.

    A positional `snake_tuple(...)` needs one overload per arity, so it stops at whatever the last
    overload declares. The identifying relationships this ORM is built for widen their key one level
    at a time — two, three, four, six — so the ceiling would land on the ordinary case, not on an
    exotic one.
    """

    carrier_id: SnakeColumn[int] = snake_int(primary_key=True)
    route_id: SnakeColumn[int] = snake_int(primary_key=True)
    leg: SnakeColumn[int] = snake_int(primary_key=True)
    origin: SnakeColumn[str] = snake_str()
    destination: SnakeColumn[str] = snake_str()
    weight: SnakeColumn[int] = snake_int()


def check_a_composite_in_is_a_condition() -> None:
    """`snake_keys(M).in_([...])` is a `SnakeCondition`, so it composes wherever a filter goes."""
    assert_type(
        snake_keys(PosShipment).in_(
            [snake_key(PosShipment).set(PosShipment.carrier_id, 1).set(PosShipment.route_id, 2)]
        ),
        SnakeCondition,
    )


def check_a_key_carries_its_model_in_the_type() -> None:
    """The model rides in the type, which is what makes a key of another model a type error."""
    assert_type(snake_key(PosShipment), SnakeKey[PosShipment])
    assert_type(snake_key(PosShipment).set(PosShipment.leg, 3), SnakeKey[PosShipment])


def check_the_width_has_no_ceiling() -> None:
    """Six columns of two different types, with no overload behind it and none needed."""
    wide = (
        snake_key(PosShipment)
        .set(PosShipment.carrier_id, 1)
        .set(PosShipment.route_id, 2)
        .set(PosShipment.leg, 3)
        .set(PosShipment.origin, "Vigo")
        .set(PosShipment.destination, "Porto")
        .set(PosShipment.weight, 400)
    )
    assert_type(snake_keys(PosShipment).in_([wide]), SnakeCondition)


def check_the_slots_may_be_chained_in_any_order() -> None:
    """Chaining order is the caller's business: the emitter canonicalises it by declaration order."""
    assert_type(
        snake_keys(PosShipment).in_(
            [
                snake_key(PosShipment).set(PosShipment.carrier_id, 1).set(PosShipment.origin, "A"),
                snake_key(PosShipment).set(PosShipment.origin, "B").set(PosShipment.carrier_id, 2),
            ]
        ),
        SnakeCondition,
    )


def check_a_scalar_expression_is_accepted_in_a_slot() -> None:
    """A slot takes any SCALAR value. The union is what draws that line — see the negative case."""
    upper = snake_upper(PosShipment.origin)
    assert_type(
        snake_keys(PosShipment).in_([snake_key(PosShipment).set(upper, "VIGO")]),
        SnakeCondition,
    )


def check_the_date_functions_accept_the_orms_own_timestamp() -> None:
    """`EXTRACT` and `DATE_TRUNC` over a `SnakeUtc` column, which is what the ORM tells you to use.

    They took `SnakeValue[datetime]` and `SnakeUtc` is a `datetime` SUBCLASS, so the call ran and
    the checker refused it — `SnakeValue[T]` is invariant, and there was no cast to reach for
    (`CASTABLE` is `int`, `float`, `bool`). The recommended way to store a timestamp could not use
    the date functions at all, which is the sort of hole only writing the query finds.

    `DATE_TRUNC` gives back the type it was handed: it trims a timestamp, it does not change what
    kind of thing it is. Pinning that here is what stops the fix from being a widening that quietly
    returns a plain `datetime` for a `SnakeUtc` column.
    """
    assert_type(snake_extract(SnakeDatePart.YEAR, TypingEvent.created_at), SnakeFuncCall[int])
    assert_type(
        snake_date_trunc(SnakeDatePart.MONTH, TypingEvent.created_at),
        SnakeFuncCall[SnakeUtc],
    )


def check_a_driver_whose_methods_are_decorated_still_satisfies_the_protocol(
    driver: AsyncPsycopgDriver,
) -> AsyncDriver:
    """An asynchronous driver keeps being an `AsyncDriver` after `@async_translating`.

    Every method of `AsyncPsycopgDriver` is wrapped by that decorator, and the decorator used to
    WIDEN the return type: it took a `Callable[P, Awaitable[T]]` and gave back a
    `Callable[P, Coroutine[object, object, T]]`. mypy accepted it; pyright did not, because an
    `async def` in a Protocol is a `CoroutineType` and a plain `Coroutine` does not match it.

    So the ONE place that hands the pair out (`connection.py::driver_and_dialect`) failed the
    pyright gate while the project went on believing the gate was green. A decorator that translates
    exceptions must not change what the method IS, and this pins that down for the whole colour.
    """
    return driver


@snake_model(table="typing_opt_countries")
class OptCountry(SnakeModel):
    """The far end of a two-hop path whose FIRST hop is nullable."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_column()


@snake_model(table="typing_opt_authors")
class OptAuthor(SnakeModel):
    """The middle of the path, itself reachable through a nullable key."""

    id: SnakeColumn[int] = snake_auto()
    username: SnakeColumn[str] = snake_column()
    country_id: SnakeColumn[int | None] = snake_int()
    country: SnakeToOne[OptCountry | None] = snake_to_one(country_id)


@snake_model(table="typing_opt_posts")
class OptPost(SnakeModel):
    """Two to-ones onto the same model, differing in exactly one thing: whether the key may be NULL."""

    id: SnakeColumn[int] = snake_auto()
    author_id: SnakeColumn[int] = snake_int()
    editor_id: SnakeColumn[int | None] = snake_int()
    author: SnakeToOne[OptAuthor] = snake_to_one(author_id)
    editor: SnakeToOne[OptAuthor | None] = snake_to_one(editor_id)


def check_class_access_on_a_nullable_to_one_drops_the_none() -> None:
    """CLASS access on `SnakeToOne[M | None]` is `type[M]`, so a nullable relation NAVIGATES.

    This is the arm resolved by narrowing `self` to `SnakeToOne[N | None]`, and it is the whole
    point of that overload. Before it, `M = OptAuthor | None` distributed to
    `type[OptAuthor] | type[None]`, `type[None]` had no columns, and this line was an error in both
    checkers with a `SnakeExpr[str] | Any` leaking out behind it.

    Dropping the `| None` is right here because class access builds SQL: it names the far side of a
    LEFT JOIN, a table that exists whether or not any given row has a partner.
    """
    assert_type(OptPost.editor, type[OptAuthor])
    assert_type(OptPost.editor.username, SnakeExpr[str])


def check_a_required_to_one_is_unaffected() -> None:
    """The control: a non-nullable relation still resolves through the plain overload.

    Without this, the assertions above could be passing because the narrow arm swallowed every
    to-one rather than only the optional ones.
    """
    assert_type(OptPost.author, type[OptAuthor])
    assert_type(OptPost.author.username, SnakeExpr[str])


def check_navigation_crosses_two_hops_with_the_first_one_nullable() -> None:
    """`OptPost.editor.country.name`: nullable hop, nullable hop, NOT NULL column.

    Deep navigation has to keep working THROUGH the unwrapped arm and not just at the first step.
    Each hop re-enters the descriptor's class access on the next model, so an overload that
    resolved the first hop but returned something un-navigable would fail exactly here.
    """
    assert_type(OptPost.editor.country.name, SnakeExpr[str])


def check_instance_access_on_a_nullable_to_one_keeps_its_none(
    post: OptPost,
) -> None:
    """INSTANCE access keeps the `| None`, and this is what makes the change CORRECT.

    Reading the value off a loaded row genuinely may hand back nothing, so `post.editor` must stay
    `OptAuthor | None` while `OptPost.editor` loses the `None`. The same property answers
    differently depending on where it is read from, which is this ORM's whole descriptor thesis.

    An overload that narrowed `self` on the instance arm too would have fixed the navigation and
    silently deleted the `None` every caller is supposed to handle — a type lie arriving through
    the front door, of exactly the kind `_guard_nullability_parity` exists to keep out.
    """
    assert_type(post.editor, OptAuthor | None)
    assert_type(post.author, OptAuthor)
