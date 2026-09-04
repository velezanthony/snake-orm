"""SnakeORM's typing contract: what must NOT compile. Illegal states made unrepresentable.

This file contains type errors ON PURPOSE. It is excluded from the global `mypy .`; the only
thing that runs it is the tests in `test_type_checkers.py`, which check that every line marked
with `# EXPECT: <error-code>` produces EXACTLY that error, and that no other line carries an
error at all.

Why it matters: the project's thesis is that the type system makes bad SQL unwritable. A test
that only checks what DOES type proves nothing — what has to be shown is that the forbidden
stays forbidden. If a refactor opens a hole, the error vanishes, the line stops matching and
the test fails.

Nothing runs at runtime: everything lives inside functions nobody calls.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz

from datetime import datetime

from snakeorm.decorators import snake_model, snake_view
from snakeorm.expressions import SnakeCondition, snake_key, snake_keys
from snakeorm.expressions.functions import count
from decimal import Decimal

from snakeorm.fields import (
    SnakeColumn,
    SnakePrefetch,
    snake_auto,
    snake_column,
    snake_decimal,
    snake_float,
    snake_int,
    snake_str,
)
from snakeorm.metadata import (
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeServerDefault,
)
from snakeorm.model import SnakeModel, SnakeView
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Maker, Nation, Truck


@snake_view(sql="SELECT user_id, class_name FROM neg_enrollments")
class NegView(SnakeView):
    """A read-only VIEW: the session's write methods must reject it."""

    user_id: SnakeColumn[int] = snake_column()
    class_name: SnakeColumn[str] = snake_column()


@snake_model(table="typing_neg_events")
class NegEvent(SnakeModel):
    """A model with a `server_default`: the column is left out of the constructor."""

    id: SnakeColumn[int] = snake_auto()
    label: SnakeColumn[str] = snake_column()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(server_default=SnakeServerDefault.NOW)


class _NotAResult:
    """A result class that does NOT inherit from SnakeResult[Model]: annotate() must reject it."""

    nation: Nation
    maker_count: int


class _NotARow:
    """A row class that does NOT inherit from SnakeRow: session.call(into=) must reject it."""

    employee_id: int
    bruto: int


def check_like_is_only_for_text_columns() -> None:
    """`like()` over a numeric column makes no sense, and the checker must stop it."""
    Truck.id.like("3%")  # EXPECT: misc


# Note: `hash(Truck.model)` is caught by NEITHER mypy NOR pyright, and NOT because of the
# `# type: ignore` on `SnakeValue.__hash__ = None`, but because the builtin is typed
# `hash(obj: object) -> int`: it accepts ANY object, so no checker ever looks at the argument's
# `__hash__`. (Verified: not even a canonical unhashable — a dataclass with `eq=True` — gets its
# `hash()` caught.) Pyright DOES reject the use as a dict key or inside a set (reportUnhashable);
# mypy rejects not even that. The guard lives at RUNTIME (`__hash__ = None` raises `TypeError`),
# not statically. And the `# type: ignore[assignment]` is NECESSARY: without it, `__hash__: None
# = None` reintroduces a real error in the declaration itself (None incompatible with object's
# `Callable[[], int]`) in BOTH checkers. That is why it is left as it stands and there is no
# `# EXPECT:` line for `hash(...)`: it would be a hole impossible to close from here.


def check_instance_attribute_must_exist() -> None:
    """An attribute the model does not declare does not exist for the checker either."""
    truck = Truck(id=1, model="Ibiza", maker_id=1)
    truck.no_declarada  # EXPECT: attr-defined


def check_instance_value_keeps_its_declared_type() -> None:
    """Instance access honours the declared type: an `int` is not a `str`."""
    truck = Truck(id=1, model="Ibiza", maker_id=1)
    model: str = truck.id  # EXPECT: assignment
    _ = model


def check_class_access_is_not_the_value() -> None:
    """CLASS access gives an expression, not the value: it cannot be assigned to `str`."""
    model: str = Truck.model  # EXPECT: assignment
    _ = model


def check_deep_navigation_respects_column_types() -> None:
    """Navigating deep loses no type: `nation.id` is `SnakeExpr[int]`, not `SnakeExpr[str]`."""
    Truck.maker.nation.id.like("1%")  # EXPECT: misc


def check_unknown_relation_step_is_rejected() -> None:
    """A relation hop the model does not declare does not exist for the checker."""
    Truck.maker.inexistente  # EXPECT: attr-defined


def check_condition_is_not_a_bool() -> None:
    """A condition is not a `bool`: assigning it to `bool` must fail."""
    result: bool = Truck.model == "Ibiza"  # EXPECT: assignment
    _ = result


def check_condition_cannot_be_combined_with_bool() -> None:
    """`&` composes conditions, not conditions with booleans."""
    condition: SnakeCondition = Truck.id > 3
    condition & True  # EXPECT: operator


def check_arithmetic_respects_operand_type() -> None:
    """Adding an integer to a text column makes no sense: the checker must stop it."""
    Truck.model + 1  # EXPECT: operator


def check_aggregate_escape_hatch_yields_object() -> None:
    """The escape hatch returns `object`, NOT `Any`: it can be neither operated on nor assigned to a concrete type.

    `obj.aggregate.<name>` is the emergency exit: the checker cannot type a dynamic name, so it
    returns `object` and FORCES a `cast()`. With `Any` this would compile (it would switch the
    checker off); with `object` the checker stays awake and forbids it.
    """
    nation = Nation(id=1, name="España")
    nation.aggregate.whatever * 2  # EXPECT: operator
    total: int = nation.aggregate.whatever  # EXPECT: assignment
    _ = total


def check_to_many_does_not_expose_child_columns() -> None:
    """CLASS access to a to-many gives a SnakeCollection, NOT the child's class.

    That is why `Nation.makers.name` (a child column) does not exist for the checker: the
    unrunnable inverted JOIN stops being writable. Only `.any()` and `.count()` are allowed.
    """
    Nation.makers.name  # EXPECT: attr-defined


def check_in_subquery_rejects_mismatched_column_type() -> None:
    """`in_(subquery)` demands that the subquery's type match the column's.

    `Nation.name` is text, so the subquery is `SnakeSubquery[str]`; comparing it against `Truck.id`
    (an integer) makes no sense. No overload of `in_` matches (neither the subquery one nor the
    iterable one): the checker must reject it.
    """
    subquery = SnakeQuery(Nation).as_scalar(Nation.name)  # SnakeSubquery[str]
    Truck.id.in_(subquery)  # EXPECT: arg-type


def check_server_default_column_is_excluded_from_init() -> None:
    """Passing a `server_default` column to the constructor is an unexpected argument (as the auto id is).

    The database fills that column in; forcing a value is done by attribute ASSIGNMENT, not through
    the constructor. The `Literal[False]` on the overload takes it out of `__init__`, so both
    checkers reject it here.
    """
    NegEvent(label="x", created_at=datetime(2020, 1, 1))  # EXPECT: call-arg


def check_joined_query_cannot_be_hydrated(session: SnakeSession) -> None:
    """A `SnakeJoinedQuery` (an explicit JOIN) can NOT be handed to `session.all()`.

    A JOIN onto a collection multiplies the rows: hydrating them as models would return the same
    parent N times (Django's gotcha). `.all()`/`.first()` accept only `SnakeQuery`, so handing them a
    joined query is a type error. Only `session.select(...)` (tuples) accepts it.
    """
    joined = SnakeQuery(Nation).join(Nation.makers)
    session.all(joined)  # EXPECT: arg-type


def check_prefetch_then_rejects_a_column() -> None:
    """`.then(...)` accepts only relations of the child, never a column: asking for a column does not compile.

    `SnakePrefetch(Nation.makers)` is `SnakePrefetch[Maker]`. `Truck.model` is a `SnakeExpr[str]`
    (a column, and one belonging to ANOTHER model at that): it matches neither the `SnakeCollection`
    overload nor the `type` one, so both checkers reject the call. That way the chain can only
    navigate real relations.
    """
    SnakePrefetch(Nation.makers).then(Truck.model)  # EXPECT: call-overload


def check_view_cannot_be_added(session: SnakeSession) -> None:
    """`session.add(view)` does NOT compile: the write methods ask for `SnakeModel`, and a view is not one.

    This is the read-only lock enforced by TYPES: `add/update/delete/...` are bound to `SnakeModel`;
    a `SnakeView` does not inherit from `SnakeModel`, so it fails to satisfy the TypeVar and both
    checkers reject it here (the runtime reinforcement covers the dynamic route).
    """
    session.add(NegView(user_id=1, class_name="Álgebra"))  # EXPECT: type-var


def check_annotate_rejects_a_non_result_class(session: SnakeSession) -> None:
    """`annotate()` demands `result: type[SnakeResult[Any]]`: a class without that base is rejected.

    This is the STATIC guard that can actually be expressed: `result` is bound to `SnakeResult[Any]`,
    so passing `_NotAResult` (which does not inherit) fails to match the type var. (The mismatch
    between query and base model, by contrast, is NOT static: see the note in
    snakeorm/decorators/result.py; it is validated at runtime.)
    """
    session.annotate(SnakeQuery(Nation), _NotAResult)  # EXPECT: type-var


def check_call_rejects_a_non_row_class(session: SnakeSession) -> None:
    """`call()` demands `into: type[SnakeRow]`: a class without that base is rejected IN THE CHECKER.

    It is the same static guard as `annotate`'s: `into` is bound to `SnakeRow`, so passing
    `_NotARow` (which does not inherit) fails to match the type var. The ORM does not verify the
    function (the SQL is opaque), but it does demand that the DECLARED shape be a valid row
    container.
    """
    session.call("f", [1], into=_NotARow)  # EXPECT: type-var


def check_snake_column_has_no_nullable_parameter() -> None:
    """`nullable=` does not exist: nullability is stated by the ANNOTATION and by nothing else.

    With two sources, one of them can lie. `SnakeColumn[str]` plus `nullable=True` produced a column
    that accepts NULL carrying a type that swore it did not, and this project holds that a type which
    lies is worse than no type at all. For an optional column: `SnakeColumn[str | None]`.
    """
    snake_column(nullable=True)  # EXPECT: call-overload


def check_a_to_one_relation_is_not_a_constructor_argument() -> None:
    """A to-one relation is NOT constructed: it is loaded with `.include(...)`.

    The runtime always knew it — `Maker(nation=...)` raises `TypeError: unexpected arguments` —
    but the checker did not, because `snake_to_one` was missing from `field_specifiers`: it saw an
    `Any` value assigned to the annotation and read it as "a field with a default". The upshot:
    mypy and pyright waved through a line that blows up the moment it runs.

    That is exactly what this project exists to prevent. The anti-N+1 lock is worth nothing if the
    type lets you walk straight past it.
    """
    Maker(id=1, name="Seat", nation_id=1, nation=Nation(id=1, name="ES"))  # EXPECT: call-arg


def una_errata_en_la_cardinalidad_no_compila(rel: SnakeRelationshipInfo) -> bool:
    """A cardinality that does not exist gets rejected. With the string `Literal[...]`, it did NOT.

    This is the line that justifies `kind` being an enum. The field used to be
    `Literal["to_one", "to_many", "to_many_through"]`, which protects ASSIGNMENT but not
    COMPARISON — and all twelve uses of the field across the ORM are comparisons. Measured at the
    time:

        rel.kind == "to_onee"    # mypy: silence.  pyright: silence.

    A typo compiled clean, returned `False` for ever and switched a branch off without a word: a
    JOIN that never gets emitted, a foreign key that never gets created. With the enum it is
    unwritable, and this case is what keeps that true.
    """
    return rel.kind is SnakeRelationshipKind.TO_ONEE  # EXPECT: attr-defined


def asignar_una_relacion_a_uno_no_compila(truck: Truck, maker: Maker) -> None:
    """Assigning a relation is rejected BY THE TYPE. It used to compile and do nothing.

    Of all the bugs this project carried, this was the most expensive: `truck.maker = other` stored
    the object in memory and did NOT touch `maker_id`, so the `UPDATE` went out without the foreign
    key and the row stayed pointing where it already was. No exception, no warning, no checker error.

    The lock is `__set__(self, instance, value: Never)`: no value is assignable to `Never`, so the
    line compiles in neither mypy nor pyright. It is closed by SHOUTING rather than by propagating
    the FK, because propagating it would be magic and around here the developer decides.
    """
    truck.maker = maker  # EXPECT: assignment


def asignar_una_coleccion_a_muchos_no_compila(nation: Nation) -> None:
    """Likewise for a to-many, where the silence was even more deceptive.

    The children hold THEIR own foreign key, so hanging a list off the parent writes nothing at all
    to the database. It looked like a write and it was nothing of the sort.
    """
    nation.makers = []  # EXPECT: assignment


def usar_una_relacion_opcional_sin_comprobarla_no_compila(truck: Truck) -> str:
    """A relation whose FK accepts NULL is declared `| None`, and then the None has to be DEALT with.

    This is the typing half of a lie the runtime was already telling: with the FK at NULL the
    `include()` does a LEFT JOIN, finds no partner and the ORM hangs `None` off the relation. If the
    type said plain `SnakeToOne[Maker]`, this line would compile and turn into an `AttributeError`
    in production.

    The other half comes from the linker, which demands PARITY: if the foreign key accepts NULL and
    the relation does not declare it (or the other way round), linking fails. Between the two, the
    case cannot be written wrong at typing time nor at start-up time.
    """
    opcional: Maker | None = truck.maker if truck.model else None
    return opcional.name  # EXPECT: union-attr


@snake_model(table="neg_precios")
class NegPrecio(SnakeModel):
    """One column of each numeric family, to pin WHERE the `int` literal is accepted."""

    id: SnakeColumn[int] = snake_auto()
    importe: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
    medida: SnakeColumn[float] = snake_float()
    etiqueta: SnakeColumn[str] = snake_column()


def check_a_bare_int_is_not_accepted_outside_exact_arithmetic() -> None:
    """`>= 0` is opened for `Decimal` ONLY. `float` and `str` stay shut, and each for its own reason.

    `str` is the case that must never move: comparing text against a number is a mistake in any
    language, and Python refuses it too.

    `float` is NOT asserted here, and the absence is the point. PEP 484 states that an `int` is
    acceptable wherever a `float` is expected —the numeric tower— so `SnakeExpr[float] >= 0` already
    type-checks and would go on doing so whatever this ORM wrote. Closing it would mean inventing a
    rule stricter than the language's own, which this project does nowhere else: it declares what an
    engine cannot do, it does not pretend Python said something it did not.

    So the opening below is for `Decimal` alone, and that is the half that IS ours: no checker
    promotes an `int` to a `Decimal`, and the promotion is the right one to add because it is exact
    — an integer has no fractional part to lose. `float` is where the imprecision lives (measured:
    `0.1 + 0.2` is `0.30000000000000004`, and a cent added a thousand times gives
    `9.999999999999831`), and Python having opened that door is not a reason for us to widen it.
    """
    NegPrecio.etiqueta >= 0  # EXPECT: operator


@snake_model(table="neg_existencias")
class NegExistencia(SnakeModel):
    """Two columns of DIFFERENT types, to pin what opening the right-hand side must not allow."""

    id: SnakeColumn[int] = snake_auto()
    cantidad: SnakeColumn[int] = snake_int()
    referencia: SnakeColumn[str] = snake_str()


def check_two_columns_of_different_types_do_not_compare() -> None:
    """Opening the right-hand side to a column must not open it to a column of ANOTHER type.

    `SnakeValue` is invariant in `T`, and this is the line that proves the invariance is doing work
    rather than being an accident of the declaration. Comparing a count against a reference is the
    mistake the whole thesis exists to catch before it reaches a database.
    """
    NegExistencia.cantidad > NegExistencia.referencia  # EXPECT: operator


@snake_model(table="neg_shipments")
class NegShipment(SnakeModel):
    """Two INTEGER key columns, which is the pair a positional tuple could not tell apart."""

    carrier_id: SnakeColumn[int] = snake_int(primary_key=True)
    route_id: SnakeColumn[int] = snake_int(primary_key=True)
    origin: SnakeColumn[str] = snake_str()


@snake_model(table="neg_carriers")
class NegCarrier(SnakeModel):
    """Another model, so a key of the wrong model has somewhere to come from."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()


def check_a_slot_refuses_a_value_of_another_type() -> None:
    """The whole reason the column and its value are PAIRED instead of positional.

    `snake_tuple(carrier_id, route_id).in_([(3, 7)])` gives the checker two integers and no way to
    tell which is which: swapping them passes both checkers and returns the wrong rows in silence.
    Here the slot binds `T`, so the value has to match the column it was set against.

    THE CODE IS `misc` AND NOT `arg-type`, which looks like a worse refusal than it is. mypy solves
    `T` from the slot and the value TOGETHER, so a disagreement between them leaves it with nothing
    to bind and it says `Cannot infer value of type parameter "T"`. That is not the union's doing —
    measured against an intermediate base class, which produces the same `misc` — so there is no
    shape of this signature that gets a better code out of mypy. pyright, on the same line, says
    `"Literal['nine']" is not assignable to "int"`, which is the sentence a caller needs. The line
    is refused by both, which is what this file asserts.
    """
    snake_key(NegShipment).set(NegShipment.carrier_id, "nine")  # EXPECT: misc


def check_a_key_of_another_model_cannot_join_the_list() -> None:
    """`SnakeKey[M]` is invariant in its model: a carrier key is not a shipment key.

    This is what makes `SnakeExpr[M, T]` unnecessary. Carrying the model in the EXPRESSION would
    have rejected legitimate two-model expressions inside a `join()`, which is bi-rooted on purpose;
    carrying it in the KEY closes the same hole at the only place the mixing could happen.
    """
    snake_keys(NegShipment).in_(
        [snake_key(NegCarrier).set(NegCarrier.id, 1)]  # EXPECT: list-item
    )


def check_an_aggregate_cannot_stand_in_a_slot() -> None:
    """A bare `COUNT(x)` is not a value a WHERE can filter on, and the union is what says so.

    Nothing in the class hierarchy separates the two: `SnakeExpr` and `SnakeAggregate` are flat
    siblings under `SnakeValue`, so without `SnakeScalar` this line types and the engine refuses it
    at execution — an aggregate belongs in a HAVING.
    """
    snake_key(NegShipment).set(count(NegShipment.carrier_id), 3)  # EXPECT: arg-type


def check_select_stops_at_four_projected_columns(session: SnakeSession) -> None:
    """A fifth projected column is not a looser tuple: there is no overload for it.

    The overloads run `c1` to `c4`, so `list[tuple[A, B, C, D]]` is the widest shape `select` can
    describe. What matters is that the fifth FAILS rather than falling back to `tuple[Any, ...]` —
    in a project whose thesis is zero `Any`, silently widening here would be the checker agreeing to
    stop checking, which is worse than the refusal it replaced.

    `limits.md` publishes this and cannot run it: it is a claim about what a type checker accepts,
    and that file executes none. This is the half that holds it.
    """
    session.select(  # EXPECT: call-overload
        SnakeQuery(NegExistencia),
        NegExistencia.id,
        NegExistencia.cantidad,
        NegExistencia.referencia,
        NegExistencia.id,
        NegExistencia.cantidad,
    )
