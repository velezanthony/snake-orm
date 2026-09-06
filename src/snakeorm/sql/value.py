"""Polymorphic emission of VALUE expressions (column, F, Case, Cast, aggregates...) via singledispatch.

Each type registers its handler: adding one is a new handler, not a refactor. `qualify` (a
prefix→alias callable) qualifies a column with its table's alias (`t2."col"`) for the deep JOINs;
without it the column is emitted bare. The dialect only enters here; the AST nodes stay agnostic.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import singledispatch
from typing import Any

from snakeorm.dialects import SnakeDialect
from datetime import date

from snakeorm.sql.refs import qualified
from snakeorm.core.exceptions import (
    SnakeEmitError,
    SnakeNodeError,
    SnakeUnsupportedFeature,
)
from snakeorm.expressions import (
    SnakeNulls,
    SnakeAggregate,
    SnakeArith,
    SnakeArithOp,
    SnakeCast,
    SnakeDateShift,
    SnakeCase,
    SnakeCoalesce,
    SnakeExpr,
    SnakeFunc,
    SnakeFuncCall,
    SnakeJsonGet,
    SnakeNullIf,
    SnakeOrder,
    SnakeStringAgg,
    SnakeSubqueryAggregate,
    SnakeSubqueryRow,
    SnakeValue,
    static_type,
)
from snakeorm.expressions.window import SnakeWindow

# Resolves a relation prefix to its table alias (e.g. ("maker","nation") -> "t2").
Qualify = Callable[[tuple[str, ...]], str]


class ExistsAliases:
    """Alias allocator for correlated subqueries (e0, e1...).

    Monotonic and shared by the whole statement, so that a nested `.any()` (or a `.count()`
    alongside an EXISTS) never collides with itself nor with the outer t0...
    """

    __slots__ = ("_next",)

    def __init__(self) -> None:
        self._next = 0

    def allocate(self) -> str:
        """Returns the next free subquery alias and advances the counter."""
        alias = f"e{self._next}"
        self._next += 1
        return alias


@dataclass(frozen=True, slots=True)
class Correlation:
    """Context for emitting correlated subqueries (EXISTS and scalar COUNT).

    `parent_ref`: how to reference the parent (the `t0` alias with JOINs, or the table name without
    them). `aliases`: hands out subquery aliases, shared so that nesting never collides.
    """

    parent_ref: str
    aliases: ExistsAliases


@singledispatch
def emit_value(
    expr: object,
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """Emits a value expression to SQL. Each type registers its handler; unknown -> error."""
    raise SnakeNodeError(f"Value expression cannot be emitted: {type(expr).__name__}")


@emit_value.register(SnakeExpr)
def _emit_column(
    expr: SnakeExpr[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """Column reference: does NOT consume params. With `qualify`, it prepends the alias of the relation prefix."""
    column = dialect.quote_ident(expr.path[-1])
    if qualify is None:
        return column
    return f"{qualify(expr.path[:-1])}.{column}"


@emit_value.register(SnakeArith)
def _emit_arith(
    expr: SnakeArith[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """Arithmetic operation `(<left> <op> <right>)`, parenthesised to preserve precedence.

    Each operand: a `SnakeValue` with `emit_value` (no params); a literal with `emit_operand`
    (placeholder).

    DIVISION IS THE ONE OPERATOR THE ENGINES SPELL DIFFERENTLY. `+`, `-` and `*` mean the same
    everywhere; `/` does not — measured, `45/50` is `0` on PostgreSQL and SQLite and `0.9000` on
    MySQL, which keeps `DIV` for the integer one. Since the ORM declares `SnakeArith[int]` for two
    integer operands, asking the dialect is what makes that declaration true on all three.

    It only asks when both operands are PROVABLY integers. `static_type` returns `None` for anything
    nobody wrote down, and `None` changes nothing: guessing would silently turn a decimal division
    into an integer one, which is a worse failure than the one this closes.
    """
    left = emit_expression_or_literal(expr.left, dialect, params, qualify, correlate)
    right = emit_expression_or_literal(expr.right, dialect, params, qualify, correlate)
    op = expr.op.value
    if expr.op is SnakeArithOp.DIV and static_type(expr.left) is int is static_type(
        expr.right
    ):
        op = dialect.integer_division_op()
    return f"({left} {op} {right})"


@emit_value.register(SnakeDateShift)
def _emit_date_shift(
    expr: SnakeDateShift[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """A date moved by an amount that travels as a PARAMETER, never inside the statement.

    All three engines were measured to accept a placeholder for the amount, including a negative one
    — which is what lets `snake_date_sub` be the same node with the sign flipped.

    `keeps_time` comes from the compiled type of the source and only SQLite reads it: with no date
    type to inspect, `date()` on a timestamp would silently drop the clock. When the type cannot be
    proven the answer is "it keeps time", because losing a clock nobody asked to lose is the worse
    of the two mistakes.
    """
    source = emit_value(expr.value, dialect, params, qualify, correlate)
    params.append(expr.amount)
    placeholder = dialect.placeholder(len(params))
    keeps_time = static_type(expr.value) is not date
    return dialect.date_shift_sql(source, placeholder, expr.unit.value, keeps_time)


@emit_value.register(SnakeStringAgg)
def _emit_string_agg(
    expr: SnakeStringAgg[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """A group joined into one string. The dialect decides how the SEPARATOR travels.

    That decision cannot live here: measured, PostgreSQL and SQLite take the separator as a normal
    argument and parameterise it, while MySQL makes it the `SEPARATOR` keyword and rejects a
    placeholder after it. So the dialect receives `params` and appends to it, or does not — the same
    arrangement `limit_offset` already uses.

    The ORDER BY is emitted here because its keys are ordinary values with ordinary paths.
    """
    value = emit_value(expr.arg, dialect, params, qualify, correlate)
    order_by = ", ".join(
        emit_order_key(key, dialect, params, qualify) for key in expr.order_by
    )
    return dialect.string_agg_sql(value, expr.separator, order_by, params)


@emit_value.register(SnakeCast)
def _emit_cast(
    expr: SnakeCast[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """An explicit cast: the SOURCE is emitted here, the TYPE NAME is the dialect's.

    That split is the same one as `json_get`, and it was measured rather than assumed: the three
    engines do not agree on how to spell a float, and SQLite's `NUMERIC` would silently drop the
    decimals this cast exists to keep.
    """
    source = emit_value(expr.source, dialect, params, qualify, correlate)
    return dialect.cast_sql(source, expr.as_type)


@emit_value.register(SnakeSubqueryAggregate)
def _emit_subquery_aggregate(
    expr: SnakeSubqueryAggregate[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """Scalar aggregation subquery `(SELECT FUNC(arg) FROM child AS alias WHERE child.fk = parent.pk)`.

    It needs the correlation context (without it, error). A composite FK ANDs the pairs. It reuses the
    `SnakeAggregate` node (with `arg=None` it comes out as `COUNT(*)`), re-anchored to the alias just
    like the condition of `.any()`.
    """
    if correlate is None:
        raise SnakeNodeError(
            "SnakeSubqueryAggregate without a correlation context: the parent cannot be referenced"
        )
    quote = dialect.quote_ident
    alias = correlate.aliases.allocate()
    # `qualified()`, not the hand-written reference: in SQLite `"public".` is invalid. Same bug
    # as in `condition.py` — the subquery of `sum_(Brand.cars.price)` pointed at
    # `"public"."cars"`.
    child_ref = qualified(expr.child_schema, expr.child_name, dialect)
    on = " AND ".join(
        f"{alias}.{quote(child_col)} = {correlate.parent_ref}.{quote(parent_col)}"
        for child_col, parent_col in expr.pairs
    )
    inner = Correlation(parent_ref=alias, aliases=correlate.aliases)
    aggregate: SnakeAggregate[Any] = SnakeAggregate(expr.func, expr.arg)
    projected = emit_value(aggregate, dialect, params, _child_qualify(alias), inner)
    return f"(SELECT {projected} FROM {child_ref} AS {alias} WHERE {on})"


@emit_value.register(SnakeSubqueryRow)
def _emit_subquery_row(
    expr: SnakeSubqueryRow[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """`(SELECT col FROM child AS e0 [JOINs] WHERE corr [AND cond] [ORDER BY ...] LIMIT 1)`.

    The LIMIT goes through the dialect like every other one: parametrised and portable.
    """
    from snakeorm.sql.condition import (
        _build_exists_joins,
        _exists_qualify,
        emit_condition_into,
    )

    if correlate is None:
        raise SnakeNodeError(
            "SnakeSubqueryRow without a correlation context: the parent cannot be referenced"
        )
    quote = dialect.quote_ident
    alias = correlate.aliases.allocate()
    child_ref = qualified(expr.child_schema, expr.child_name, dialect)
    on = " AND ".join(
        f"{alias}.{quote(child_col)} = {correlate.parent_ref}.{quote(parent_col)}"
        for child_col, parent_col in expr.pairs
    )
    alias_map, joins_sql = _build_exists_joins(
        expr.joins, alias, correlate.aliases, dialect
    )
    inner = Correlation(parent_ref=alias, aliases=correlate.aliases)
    child_qualify = _exists_qualify(alias_map)
    projected = emit_value(expr.column, dialect, params, child_qualify, inner)
    sql = f"(SELECT {projected} FROM {child_ref} AS {alias}{joins_sql} WHERE {on}"
    if expr.condition is not None:
        cond = emit_condition_into(
            expr.condition, dialect, params, child_qualify, inner
        )
        sql = f"{sql} AND {cond}"
    if expr.order_by:
        keys = ", ".join(
            emit_order_key(key, dialect, params, child_qualify, inner)
            for key in expr.order_by
        )
        sql = f"{sql} ORDER BY {keys}"
    clause = dialect.limit_offset(1, None, params)
    return f"{sql} {clause})"


def _child_qualify(alias: str) -> Qualify:
    """Qualifies direct child columns with its alias (empty prefix): `Maker.name` → `e0."name"`.

    A deep navigation inside the subquery would demand a JOIN that has not been built: it is rejected.
    """

    def qualify(prefix: tuple[str, ...]) -> str:
        if prefix == ():
            return alias
        raise SnakeUnsupportedFeature(
            "deep column navigation inside a correlated subquery is not supported yet; filter or "
            "aggregate by direct columns of the child"
        )

    return qualify


@emit_value.register(SnakeJsonGet)
def _emit_json_get(
    expr: SnakeJsonGet[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """A read inside a document. The SOURCE is emitted here; the spelling is the dialect's.

    It consumes no parameter, and that is not an oversight: the key is part of the STATEMENT (no
    engine takes a placeholder inside a JSON path) and it was validated as a plain identifier when
    the expression was built.
    """
    source = emit_value(expr.source, dialect, params, qualify, correlate)
    return dialect.json_get_sql(source, expr.key_path, expr.as_type)


@emit_value.register(SnakeAggregate)
def _emit_aggregate(
    expr: SnakeAggregate[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """Aggregate: `COUNT(*)`, `COUNT(DISTINCT <arg>)` or `FUNC(<arg>)`.

    With no argument it is `COUNT(*)` (no params). With an argument, it is emitted with `emit_value`
    (its literals do travel parametrised). The aggregate never interpolates values.
    """
    func = expr.func.value
    if expr.arg is None:
        return f"{func}(*)"
    inner = emit_value(expr.arg, dialect, params, qualify, correlate)
    if expr.distinct:
        return f"{func}(DISTINCT {inner})"
    return f"{func}({inner})"


def emit_expression_or_literal(
    operand: object,
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None,
    correlate: Correlation | None = None,
) -> str:
    """THE rule for an operand the user wrote: expression → `emit_value`; literal → `emit_operand`.

    It was called `_emit_arith_operand` while arithmetic was the only caller, and the name was doing
    harm by then: `CASE`, `COALESCE`, `NULLIF` and the function arguments had all adopted it, and the
    place that had NOT —the right-hand side of a comparison— read as if it were a different problem
    rather than the same one with a hole in it. `"a" > "b"` used to bind a `SnakeExpr` object into
    `params` and let the driver be the one to complain.

    An expression consumes NO parameter: it is a reference to a column, and a column reference is
    part of the statement's text. A literal always travels in `params` and is never interpolated,
    which is what kills injection and what makes one emitter serve three engines.
    """
    if isinstance(operand, SnakeValue):
        return emit_value(operand, dialect, params, qualify, correlate)
    return emit_operand(operand, dialect, params)


def emit_operand(value: object, dialect: SnakeDialect, params: list[object]) -> str:
    """Emits a LITERAL operand as a placeholder and stores its value in `params`.

    One of the TWO places where a value enters `params` (the other is the INSERT emitter). The value
    goes in exactly as the user wrote it; translating it to the DBAPI is the driver's business
    (`adapt_params`), and the DDL emitter needs the originals. `SnakeValue`s do not come through here
    (`emit_value` emits those).
    """
    params.append(value)
    return dialect.placeholder(len(params))


def emit_order_key(
    key: SnakeOrder,
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None,
    correlate: Correlation | None = None,
) -> str:
    """Emits an order key: `<value> ASC|DESC [NULLS FIRST|LAST]`.

    `NULLS` only if it was asked for: without it, the engine's default is respected.

    `correlate` is what lets a statement SORT by a correlated aggregate it can already project. It
    defaults to `None` because the other callers emit an ORDER BY where no parent row exists — a
    compound, a recursive CTE, a window's own ordering — and there the refusal is the right answer.
    """
    direction = "DESC" if key.descending else "ASC"
    if key.nulls is not None and not dialect.syntax.has_nulls_ordering:
        # The portable form, for an engine without the keyword. MySQL and MariaDB both answer
        # `ERROR 1064` to `NULLS LAST` — measured on 8.4.11 and 11.8.8, because this dialect serves
        # two engines and cannot promise what only one of them does — and both accept this, inside a
        # UNION as well.
        #
        # The expression is emitted TWICE rather than reusing the string, and that is not waste:
        # `emit_value` APPENDS to `params`, so one emission and two mentions would leave two
        # placeholders for one value on exactly the dialects that count them.
        #
        # `NULLS FIRST` is nulls before, so the flag sorts ASC (False < True puts the non-nulls
        # first for LAST, and DESC flips it).
        nulls_first = "DESC" if key.nulls is SnakeNulls.FIRST else "ASC"
        flag = emit_value(key.expr, dialect, params, qualify, correlate)
        column = emit_value(key.expr, dialect, params, qualify, correlate)
        return f"({flag} IS NULL) {nulls_first}, {column} {direction}"
    column = emit_value(key.expr, dialect, params, qualify, correlate)
    nulls = f" NULLS {key.nulls.value}" if key.nulls is not None else ""
    return f"{column} {direction}{nulls}"


def guard_untabled_order_keys(
    keys: Sequence[SnakeOrder],
    projected: frozenset[str] | None,
    subject: str,
    remedy: str,
) -> None:
    """Refuses an order key that cannot be written where there is no table to write it against.

    A set operation and a `WITH RECURSIVE` order their RESULT, and a result is not a table: there is
    no alias to qualify with and nothing to JOIN to, which is why both call `emit_order_key` with
    `qualify=None`. Nothing checked that the key survived that, and two shapes did not:

    - A key over a RELATIONSHIP. The hop was dropped and only the last segment got written, so
      `Sale.maker.name` came out as the bare `"name"`. On a model that also owns a `name` that is a
      DIFFERENT column, valid SQL, and the three engines sort the same wrong way — no engine can
      disagree about it, so comparing them cannot find it.
    - A key naming a column the projection does not carry. Here nobody agreed: SQLite, Postgres and
      MySQL each answered their own native error about a column the caller never typed.

    `projected` is `None` when the rows come whole, and then every column of the model is there.
    """
    for key in keys:
        for path in key.expr.paths():
            if len(path) > 1:
                raise SnakeEmitError(
                    f"{subject} cannot be ordered by {'.'.join(path)}: that key navigates a "
                    f"relationship and the result of the operation is not a table, so there is "
                    f"nothing to JOIN it to. Emitting it would sort by the bare "
                    f"'{path[-1]}' — another column entirely where the model owns one of that "
                    f"name, with no error anywhere. {remedy}"
                )
            # A key with no path names no column, so there is nothing to check against the
            # projection. Spelt out because after the guard above a tuple of one is indistinguishable
            # from an empty one to a checker, and `path[0]` would be out of range.
            if not path:
                continue
            if projected is not None and path[0] not in projected:
                raise SnakeEmitError(
                    f"{subject} cannot be ordered by {path[0]}: the branches project "
                    f"{', '.join(sorted(projected))} and the result has no other column, so the "
                    f"engine would answer its own error about a column you never asked for. Name "
                    f"the column in the only()/defer() of both branches, or order by one that is "
                    f"already there."
                )


@emit_value.register(SnakeCase)
def _emit_case(
    expr: SnakeCase[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """`CASE WHEN cond THEN value ... [ELSE default] END`, in the declared order.

    Local import of the condition emitter (at module level it would be a cycle). With no default, no
    ELSE is written (in SQL it already is NULL).
    """
    from snakeorm.sql.condition import emit_condition_into

    if not expr.branches:
        raise SnakeEmitError("A CASE needs at least one branch to be emitted")
    parts = []
    for condition, result in expr.branches:
        when = emit_condition_into(condition, dialect, params, qualify, correlate)
        then = emit_expression_or_literal(result, dialect, params, qualify, correlate)
        parts.append(f"WHEN {when} THEN {then}")
    body = " ".join(parts)
    if expr.has_default:
        body = f"{body} ELSE {emit_expression_or_literal(expr.default, dialect, params, qualify, correlate)}"
    return f"CASE {body} END"


@emit_value.register(SnakeCoalesce)
def _emit_coalesce(
    expr: SnakeCoalesce[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """`COALESCE(a, b, ...)`: each argument is emitted according to whether it is a column or a literal."""
    inner = ", ".join(
        emit_expression_or_literal(argument, dialect, params, qualify, correlate)
        for argument in expr.arguments
    )
    return f"COALESCE({inner})"


@emit_value.register(SnakeNullIf)
def _emit_nullif(
    expr: SnakeNullIf[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """`NULLIF(value, sentinel)`."""
    value = emit_value(expr.value, dialect, params, qualify, correlate)
    sentinel = emit_expression_or_literal(
        expr.sentinel, dialect, params, qualify, correlate
    )
    return f"NULLIF({value}, {sentinel})"


@emit_value.register(SnakeFuncCall)
def _emit_func_call(
    expr: SnakeFuncCall[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """`FUNC(arg, ...)`, with the name translated by the dialect.

    `EXTRACT` is the exception: its syntax is `EXTRACT(part FROM value)`, not a list of arguments.
    """
    name = dialect.function_name(expr.func)
    if expr.func is SnakeFunc.EXTRACT and expr.part is not None:
        # EXTRACT(part FROM value): the part is a keyword, it is NOT parametrised.
        value = emit_expression_or_literal(
            expr.arguments[0], dialect, params, qualify, correlate
        )
        return f"{name}({expr.part.value} FROM {value})"
    # The `part` goes FIRST and its param before the arguments: in a positional dialect the order of
    # `params` must follow the textual order of the placeholders (it ended up swapping part and
    # argument).
    rendered: list[str] = []
    if expr.part is not None:
        rendered.append(emit_operand(expr.part.value, dialect, params))
    rendered.extend(
        emit_expression_or_literal(argument, dialect, params, qualify, correlate)
        for argument in expr.arguments
    )
    # ROUND with a digit count: some engines have no overload for a float and want the value as a
    # decimal first. The dialect declares the TYPE NAME; the cast is written in standard
    # `CAST(x AS t)`, which Postgres takes as readily as its own `::`. That way no engine's
    # spelling lives in an emitter whose whole job is to be agnostic.
    cast_to = dialect.syntax.round_casts_first_argument_to
    if expr.func is SnakeFunc.ROUND and len(rendered) == 2 and cast_to is not None:
        rendered[0] = f"CAST({rendered[0]} AS {cast_to})"
    return f"{name}({', '.join(rendered)})"


@emit_value.register(SnakeWindow)
def _emit_window(
    expr: SnakeWindow[Any],
    dialect: SnakeDialect,
    params: list[object],
    qualify: Qualify | None = None,
    correlate: Correlation | None = None,
) -> str:
    """`<func>(<arg>[, <extra>...]) OVER ([PARTITION BY ...] [ORDER BY ...])`.

    TEXTUAL emission order: Postgres's `%s` is positional, so `params` follows the order of the
    placeholders (arguments, then partition, then order).
    """
    arguments: list[str] = []
    if expr.arg is not None:
        arguments.append(emit_value(expr.arg, dialect, params, qualify, correlate))
    arguments.extend(emit_operand(extra, dialect, params) for extra in expr.extra_args)

    window: list[str] = []
    if expr.partition_by:
        keys = ", ".join(
            emit_value(value, dialect, params, qualify, correlate)
            for value in expr.partition_by
        )
        window.append(f"PARTITION BY {keys}")
    if expr.order_by:
        keys = ", ".join(
            emit_order_key(key, dialect, params, qualify) for key in expr.order_by
        )
        window.append(f"ORDER BY {keys}")
    if expr.frame is not None:
        # No dialect involved, and that is measured: `ROWS BETWEEN 1 PRECEDING AND CURRENT ROW`
        # runs unchanged on the three. The offset is IN the clause because MariaDB rejects a
        # placeholder in a bound; it is an `int` checked non-negative when the bound was built.
        window.append(expr.frame.sql())

    return f"{expr.func}({', '.join(arguments)}) OVER ({' '.join(window)})"
