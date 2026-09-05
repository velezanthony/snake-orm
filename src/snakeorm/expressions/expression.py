"""Typed expression AST: values (SnakeValue) and conditions (SnakeCondition).

The nodes do NOT execute: they describe SQL; `sql/` translates them. Hierarchy of values:

    SnakeValue[T]       base: it compares and operates; it has NO `.path`.
    ├── SnakeExpr[T]    a column (the only one with `.path`).
    └── SnakeArith[T]   an arithmetic operation.

`SnakeValue.__eq__` returns a comparison (not `bool`), so the nodes use identity equality
(`eq=False`) and are not hashable by value.
"""

from __future__ import annotations

import re
from decimal import Decimal

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

from snakeorm.core.exceptions import SnakeUnsupportedFeature, SnakeValueError

if TYPE_CHECKING:
    # For the checker only: `window` imports this module, so at runtime it would be a cycle.
    # With `from __future__ import annotations` the annotation is a string and is never evaluated.
    from snakeorm.expressions.window import SnakeFrame, SnakeWindow

T = TypeVar("T")
V = TypeVar("V")


class SnakeOp(Enum):
    """Comparison operators supported inside a condition."""

    EQ = "="
    NE = "<>"
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


class SnakeArithOp(Enum):
    """Arithmetic operators supported inside a value expression."""

    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"


class SnakeNulls(Enum):
    """Where the NULLs go when ordering. Agnostic: `NULLS FIRST`/`NULLS LAST` is standard SQL."""

    FIRST = "FIRST"
    LAST = "LAST"


class SnakeLock(Enum):
    """What to do if the row to be locked is already locked.

    `WAIT` waits (the default of `FOR UPDATE`), `NOWAIT` fails, `SKIP_LOCKED` ignores it. The last
    two are opposites: asking for both is an error.
    """

    WAIT = "wait"
    NOWAIT = "nowait"
    SKIP_LOCKED = "skip_locked"


class SnakeAggFunc(Enum):
    """Supported aggregation functions (standard SQL, engine-agnostic)."""

    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"


class SnakeCondition:
    """Boolean node of the query AST (WHERE, JOIN ON...).

    It combines with `&` (AND), `|` (OR) and is negated with `~` (NOT).
    """

    __slots__ = ()

    def __and__(self, other: SnakeCondition) -> SnakeAnd:
        return SnakeAnd(parts=(self, other))

    def __or__(self, other: SnakeCondition) -> SnakeOr:
        return SnakeOr(parts=(self, other))

    def __invert__(self) -> SnakeNot:
        return SnakeNot(operand=self)


@dataclass(frozen=True, slots=True, eq=False)
class SnakeComparison(SnakeCondition):
    """Comparison `value OP value` (e.g. `username = 'Ana'`)."""

    left: SnakeValue[Any]
    op: SnakeOp
    right: object


@dataclass(frozen=True, slots=True, eq=False)
class SnakeAnd(SnakeCondition):
    """Conjunction of conditions (all of them must hold)."""

    parts: tuple[SnakeCondition, ...]


@dataclass(frozen=True, slots=True, eq=False)
class SnakeOr(SnakeCondition):
    """Disjunction of conditions (at least one of them must hold)."""

    parts: tuple[SnakeCondition, ...]


@dataclass(frozen=True, slots=True, eq=False)
class SnakeInList(SnakeCondition):
    """Membership in a set: `value IN (v1, v2, ...)`."""

    left: SnakeValue[Any]
    values: tuple[object, ...]


@dataclass(frozen=True, slots=True, eq=False)
class SnakeTupleIn(SnakeCondition):
    """Row constructor: `(c1, c2) IN ((v1a, v2a), ...)` — the N-dimensional version of `SnakeInList`.

    It is produced by the select-in of a to-many with a composite FK. Postgres emits it as is; a
    dialect without a row constructor translates it into the disjunction `(a=.. AND b=..) OR (...)`. Parametrised values.
    """

    columns: tuple[SnakeValue[Any], ...]
    rows: tuple[tuple[object, ...], ...]


@dataclass(frozen=True, slots=True, eq=False)
class SnakeIsNull(SnakeCondition):
    """Nullity check: `value IS NULL`."""

    left: SnakeValue[Any]


@dataclass(frozen=True, slots=True, eq=False)
class SnakeIsNotNull(SnakeCondition):
    """Non-nullity check: `value IS NOT NULL`."""

    left: SnakeValue[Any]


def _escape_like(value: str) -> str:
    """Escapes the LIKE wildcards inside a VALUE, so they are data and not pattern.

    `startswith("100%")` must search for a literal "100%": without this, the filter would silently
    bring back TOO MUCH. The backslash goes first, or it would escape the escapes just put in.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, slots=True, eq=False)
class SnakeLike(SnakeCondition):
    """Pattern match: `value LIKE pattern` (or `ILIKE` if it ignores case).

    The pattern ALWAYS travels parametrised. `case_insensitive` is a flag (it does not compose well
    with the existing nodes).
    """

    left: SnakeValue[Any]
    pattern: str
    case_insensitive: bool = False
    # True when the wildcards of the VALUE were escaped (startswith/contains/endswith): the emission
    # adds `ESCAPE '\'` or SQLite treats the `\` as a character and filters wrong. A raw `.like()` goes with False.
    escaped: bool = False


@dataclass(frozen=True, slots=True, eq=False)
class SnakeNot(SnakeCondition):
    """Negation of a condition: `NOT (...)`."""

    operand: SnakeCondition


@dataclass(frozen=True, slots=True)
class SnakeExistsJoin:
    """A navigation JOIN INSIDE the subquery of an EXISTS (a to-one relationship of the child).

    When the condition of `.any()` navigates (`Maker.nation.name`), it joins the target table inside
    the EXISTS. Already resolved against the graph (the emission only assigns aliases). `prefix` is
    the relationships accumulated from the child (`prefix[:-1]` reaches the parent, `()` = the
    child); `pairs` are the to-one FK pairs (`parent.local = alias.remote`, a composite FK ANDs
    them). Primitives only: no `SnakeTableInfo`.
    """

    prefix: tuple[str, ...]
    schema: str
    name: str
    pairs: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True, eq=False)
class SnakeExists(SnakeCondition):
    """Correlated EXISTS: does the parent have at least one child [satisfying `condition`]?

    It is produced by class access to a to-many (`Nation.makers.any(...)`). It changes the
    cardinality, which is why it is explicit; it inherits `& | ~`. It stores the child table and the
    correlation pairs (`(child_column, parent_column)`) so it can emit `child.fk = parent.pk`. The
    `condition` (optional) filters the child (paths relative to the child, re-anchored at emission).
    `joins` are the to-one navigation JOINs of the child. Primitives only, no `SnakeTableInfo`.
    """

    child_schema: str
    child_name: str
    pairs: tuple[tuple[str, str], ...]
    condition: SnakeCondition | None = None
    joins: tuple[SnakeExistsJoin, ...] = ()


@dataclass(frozen=True, slots=True, eq=False)
class SnakeOrder:
    """Ordering key: a value, its direction and where the NULLs go.

    `nulls=None` leaves the engine default, which has a trap in it: Postgres puts the NULLs last in
    ASC and first in DESC, so changing the direction moves the gaps around.
    """

    expr: SnakeValue[Any]
    descending: bool
    nulls: SnakeNulls | None = None

    def nulls_first(self) -> SnakeOrder:
        """The same key, with the NULLs first."""
        return SnakeOrder(self.expr, self.descending, SnakeNulls.FIRST)

    def nulls_last(self) -> SnakeOrder:
        """The same key, with the NULLs last."""
        return SnakeOrder(self.expr, self.descending, SnakeNulls.LAST)


class SnakeValue(Generic[T]):
    """Base of every VALUE expression: it knows how to compare itself and operate arithmetically.

    With no SQL identity of its own (the subclasses provide that). The comparators produce a
    `SnakeCondition`; the arithmetic ones another `SnakeValue` (`SnakeArith`), chainable.
    """

    __slots__ = ()

    def __eq__(self, other: object) -> SnakeCondition:  # type: ignore[override]
        if (
            other is None
        ):  # `col == None` -> IS NULL (not `= NULL`, which in SQL is always false)
            return SnakeIsNull(self)
        return SnakeComparison(self, SnakeOp.EQ, other)

    def __ne__(self, other: object) -> SnakeCondition:  # type: ignore[override]
        if other is None:  # `col != None` -> IS NOT NULL
            return SnakeIsNotNull(self)
        return SnakeComparison(self, SnakeOp.NE, other)

    # A COLUMN is accepted on the right, and it costs no parameter: `quantity > reserved` emits
    # `"quantity" > "reserved"`. It is the same rule arithmetic always used: an operand that is a
    # `SnakeValue` is a reference, anything else is a literal.
    #
    # The pair stays TYPED: `SnakeValue` is invariant in `T`, so `SnakeExpr[str] > SnakeExpr[int]`
    # is still rejected. Comparing a column against a column of another type is the mistake this
    # opening must not let through.
    #
    # An `int` is accepted on a `Decimal` column, and ONLY there. `Decimal("1") >= 0` is valid
    # Python, `NUMERIC >= 0` is valid SQL, and this ORM emits the SAME SQL either way — measured
    # byte for byte on the three dialects. The promotion is EXACT: an integer has no fractional
    # part, so `0` and `Decimal(0)` are the same number and nothing rounds. `float` is NOT opened
    # here and does not need to be: PEP 484's numeric tower already says an `int` goes wherever a
    # `float` is expected. `str` stays shut, as it is in Python.
    @overload
    def __lt__(
        self: SnakeValue[Decimal],
        other: Decimal | int | SnakeValue[Decimal] | SnakeValue[int],
    ) -> SnakeComparison: ...

    @overload
    def __lt__(self, other: SnakeValue[T] | T) -> SnakeComparison: ...

    def __lt__(self, other: object) -> SnakeComparison:
        return SnakeComparison(self, SnakeOp.LT, other)

    @overload
    def __le__(
        self: SnakeValue[Decimal],
        other: Decimal | int | SnakeValue[Decimal] | SnakeValue[int],
    ) -> SnakeComparison: ...

    @overload
    def __le__(self, other: SnakeValue[T] | T) -> SnakeComparison: ...

    def __le__(self, other: object) -> SnakeComparison:
        return SnakeComparison(self, SnakeOp.LE, other)

    @overload
    def __gt__(
        self: SnakeValue[Decimal],
        other: Decimal | int | SnakeValue[Decimal] | SnakeValue[int],
    ) -> SnakeComparison: ...

    @overload
    def __gt__(self, other: SnakeValue[T] | T) -> SnakeComparison: ...

    def __gt__(self, other: object) -> SnakeComparison:
        return SnakeComparison(self, SnakeOp.GT, other)

    @overload
    def __ge__(
        self: SnakeValue[Decimal],
        other: Decimal | int | SnakeValue[Decimal] | SnakeValue[int],
    ) -> SnakeComparison: ...

    @overload
    def __ge__(self, other: SnakeValue[T] | T) -> SnakeComparison: ...

    def __ge__(self, other: object) -> SnakeComparison:
        return SnakeComparison(self, SnakeOp.GE, other)

    # Not hashable: `__eq__` returns a condition, not a bool. A RUNTIME guard (`hash()` raises
    # TypeError); statically it cannot be closed off, hence the `# type: ignore[assignment]`.
    __hash__ = None  # type: ignore[assignment]

    # THE SECOND OVERLOAD OF EACH OPERATOR PROPAGATES NULLABILITY, and the line it draws is one
    # question: does the type CHANGE what the engine computes, or finally DESCRIBE it?
    #
    #   int * 1.0        changes it — integer division or decimal is a decision, and it stays the
    #                    caller's, made explicit with `snake_cast`.
    #   a + NULL         changes nothing — it is NULL on the three engines, always, no choice in it.
    #
    # Without it, `snake_nullif` declaring the `None` it introduces would make
    # `x / snake_nullif(y, 0)` impossible to write — the one expression it exists for.
    #
    # The non-nullable overload goes FIRST: with a nullable operand it cannot match (`SnakeValue[T]`
    # is invariant, so `SnakeValue[int | None]` is not a `SnakeValue[int]`) and resolution falls
    # through to the second. Reversing them would make every arithmetic nullable.

    @overload
    def __add__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __add__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __add__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(self, SnakeArithOp.ADD, other)

    @overload
    def __sub__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __sub__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __sub__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(self, SnakeArithOp.SUB, other)

    @overload
    def __mul__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __mul__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __mul__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(self, SnakeArithOp.MUL, other)

    @overload
    def __truediv__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __truediv__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __truediv__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(self, SnakeArithOp.DIV, other)

    # Reflected: the foreign operand ends up on the LEFT (the order matters for `-` and `/`).

    @overload
    def __radd__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __radd__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __radd__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(other, SnakeArithOp.ADD, self)

    @overload
    def __rsub__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __rsub__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __rsub__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(other, SnakeArithOp.SUB, self)

    @overload
    def __rmul__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __rmul__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __rmul__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(other, SnakeArithOp.MUL, self)

    @overload
    def __rtruediv__(self, other: SnakeValue[T] | T) -> SnakeArith[T]: ...
    @overload
    def __rtruediv__(self, other: SnakeValue[T | None]) -> SnakeArith[T | None]: ...
    def __rtruediv__(self, other: object) -> SnakeArith[Any]:
        return SnakeArith(other, SnakeArithOp.DIV, self)

    def json_get(self, *key_path: str, as_type: type[V]) -> SnakeJsonGet[V]:
        """Reads a key INSIDE a JSON column, as the declared type: `meta.json_get("size", as_type=int)`.

        `as_type` is required and it is not ceremony. What the engines give back from a document is
        text, so without a declared type the comparison below would be a TEXT comparison and
        `'9' > '100'` would be true — the same trap the capability catalogue documents for a
        `Decimal` ordered as text. The type is what makes the ORM emit the cast.

        Several keys walk a nested path in ONE access (`json_get("owner", "name")`), because every
        engine takes a path and two accesses would be two trips through the document.

        The key is validated rather than parametrised: it is emitted inside a literal, where no
        engine accepts a placeholder, so a key that is not a plain identifier is refused here.
        """
        if as_type not in JSON_CASTABLE:
            raise SnakeUnsupportedFeature(
                f"json_get(as_type={getattr(as_type, '__name__', as_type)!r}) is not supported: a "
                f"document is read back as one of {', '.join(t.__name__ for t in JSON_CASTABLE)}. "
                f"Read it as str and convert it yourself if the engine has no cast for that type."
            )
        if not key_path:
            raise SnakeValueError("json_get() needs at least one key to read")
        for key in key_path:
            if not _JSON_KEY.match(key):
                raise SnakeValueError(
                    f"json_get() key {key!r} is not a plain identifier. The key is emitted INSIDE "
                    f"the statement (no engine takes a placeholder in a JSON path), so anything "
                    f"else would be an injection rather than a lookup."
                )
        return SnakeJsonGet(source=self, key_path=key_path, as_type=as_type)

    @overload
    def in_(self, values: SnakeSubquery[T]) -> SnakeInSubquery: ...
    @overload
    def in_(self, values: Iterable[T]) -> SnakeInList: ...
    def in_(
        self, values: Iterable[T] | SnakeSubquery[T]
    ) -> SnakeInList | SnakeInSubquery:
        """`value IN (...)`: a set of values or a scalar SUBQUERY.

        An iterable -> values typed to `T`, `SnakeInList`. A `SnakeSubquery[T]` (same `T`) -> `value
        IN (SELECT ...)`, `SnakeInSubquery` (the checker rejects a subquery of another type).
        """
        if isinstance(values, SnakeSubquery):
            return SnakeInSubquery(left=self, subquery=values)
        return SnakeInList(self, tuple(values))

    def is_null(self) -> SnakeIsNull:
        """`value IS NULL`. Valid for any expression."""
        return SnakeIsNull(self)

    def is_not_null(self) -> SnakeIsNotNull:
        """`value IS NOT NULL`. Valid for any expression."""
        return SnakeIsNotNull(self)

    def like(self: SnakeValue[str], pattern: str) -> SnakeLike:
        """`value LIKE pattern`. Only over text expressions (self: SnakeValue[str])."""
        return SnakeLike(self, pattern)

    def ilike(self: SnakeValue[str], pattern: str) -> SnakeLike:
        """`value ILIKE pattern`: like `like`, but ignoring upper and lower case."""
        return SnakeLike(self, pattern, case_insensitive=True)

    def not_in(self, values: Iterable[T]) -> SnakeNot:
        """`NOT (value IN (...))`: the NEGATION of the IN, not a new node (one more node would be one more place to forget something)."""
        return SnakeNot(operand=SnakeInList(self, tuple(values)))

    def between(self, low: T, high: T) -> SnakeAnd:
        """`value BETWEEN low AND high` (inclusive), as an AND of two comparisons (no node of its own: equivalent SQL)."""
        try:
            inverted = low > high  # type: ignore[operator]
        except TypeError:
            # `T` carries no bound and cannot: bounding it would break `SnakeColumn[dict]`, which is
            # a real column type. So the comparison can fail, and Python's own message —"'>' not
            # supported between instances of 'dict' and 'dict'"— is about Python's operators in the
            # middle of building a query, leaving the reader to work out which column it meant.
            # `json_get()` twelve lines above already translates its own refusal; this is that move.
            raise SnakeUnsupportedFeature(
                f"between() needs values that can be ORDERED, and {type(low).__name__} cannot be. "
                f"A column of that type has no range to sit inside: filter it with an equality, or "
                f"with json_get() if what you want is a value inside the document."
            ) from None
        if inverted:
            raise SnakeValueError(
                f"The between range is inverted ({low!r} > {high!r}): there is no value between "
                f"those two, so the query would return nothing. Did you swap them round?"
            )
        return SnakeAnd(
            parts=(
                SnakeComparison(self, SnakeOp.GE, low),
                SnakeComparison(self, SnakeOp.LE, high),
            )
        )

    def startswith(self: SnakeValue[str], value: str) -> SnakeLike:
        """`LIKE 'value%'`, with the wildcards of the VALUE escaped."""
        return SnakeLike(self, f"{_escape_like(value)}%", escaped=True)

    def istartswith(self: SnakeValue[str], value: str) -> SnakeLike:
        """Like `startswith`, but ignoring case."""
        return SnakeLike(
            self, f"{_escape_like(value)}%", case_insensitive=True, escaped=True
        )

    def endswith(self: SnakeValue[str], value: str) -> SnakeLike:
        """`LIKE '%value'`, with the wildcards of the VALUE escaped."""
        return SnakeLike(self, f"%{_escape_like(value)}", escaped=True)

    def iendswith(self: SnakeValue[str], value: str) -> SnakeLike:
        """Like `endswith`, but ignoring case."""
        return SnakeLike(
            self, f"%{_escape_like(value)}", case_insensitive=True, escaped=True
        )

    def contains(self: SnakeValue[str], value: str) -> SnakeLike:
        """`LIKE '%value%'`, with the wildcards of the VALUE escaped."""
        return SnakeLike(self, f"%{_escape_like(value)}%", escaped=True)

    def icontains(self: SnakeValue[str], value: str) -> SnakeLike:
        """Like `contains`, but ignoring case."""
        return SnakeLike(
            self, f"%{_escape_like(value)}%", case_insensitive=True, escaped=True
        )

    def asc(self) -> SnakeOrder:
        """Ascending order key by this expression."""
        return SnakeOrder(self, descending=False)

    def desc(self) -> SnakeOrder:
        """Descending order key by this expression."""
        return SnakeOrder(self, descending=True)

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Column paths contained in this node. Each concrete subclass defines it."""
        raise NotImplementedError


class SnakeExpr(SnakeValue[T]):
    """Typed expression over ONE column.

    `path` is the navigation down to the column (the last element is the column, the earlier ones
    relationships: `("car", "brand", "name")`). The only column leaf node.

    `python_type` is the COMPILED type of the column, carried here so the emitter can reason about
    it: the generic `T` is erased at runtime, and without this the SQL layer cannot tell an integer
    division from a decimal one. It is `None` when nobody stamped it — a hand-built node in a test,
    or a path the compiler never saw — and everything that reads it treats `None` as "no proof" and
    changes nothing.
    """

    __slots__ = ("path", "python_type")

    def __init__(self, path: tuple[str, ...], python_type: type | None = None) -> None:
        self.path = path
        self.python_type = python_type

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """A column contributes exactly its own path."""
        return (self.path,)


@dataclass(frozen=True, slots=True, eq=False)
class SnakeArith(SnakeValue[T]):
    """Arithmetic operation between two values: `left OP right`.

    Each operand is another `SnakeValue` or a literal `T`. Chainable: `(a + 1) > 3`.
    """

    left: SnakeValue[T] | T
    op: SnakeArithOp
    right: SnakeValue[T] | T

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Recursively collects the paths of the operands that are expressions."""
        collected: tuple[tuple[str, ...], ...] = ()
        if isinstance(self.left, SnakeValue):
            collected += self.left.paths()
        if isinstance(self.right, SnakeValue):
            collected += self.right.paths()
        return collected


# What a declared type becomes inside the document access. It is a WHITELIST and not a mapping with a
# fallback: a type nobody has written a cast for must be refused by name, because the alternative is
# emitting SQL the engine rejects and letting the driver explain a decision this ORM made.
JSON_CASTABLE: tuple[type, ...] = (str, int, float, bool)

# What a JSON key may be. Emitted INSIDE a literal (`'$.a'`, `'{a,b}'`) because no engine takes a
# placeholder there — which is exactly the shape where an unchecked string becomes an injection.
_JSON_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True, eq=False)
class SnakeJsonGet(SnakeValue[T]):
    """A read INSIDE a JSON document: `meta ->> 'size'`, cast to the type that was declared.

    The type is DECLARED rather than inferred, and that is the decision the whole feature rests on.
    A key access could have been `str` always —which is what `->>` returns— and it would have let
    `meta.json_get("size") > 100` compare TEXT, where `'9' > '100'` is true. The cast is what makes
    the comparison mean what it looks like.

    What is inside the document is not something the ORM can know: if it does not hold what was
    declared, the ENGINE complains, and that is the right place for it.
    """

    source: SnakeValue[Any]
    key_path: tuple[str, ...]
    as_type: type

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """The column being read into: the access adds no navigation of its own."""
        return self.source.paths()


# What an explicit cast may target. A WHITELIST for the same reason `JSON_CASTABLE` is one, and NOT
# the same list: `str` belongs there because `->>` already returns text, and does NOT belong here,
# where accepting it would mean emitting the source unchanged and handing an integer to somebody who
# asked for text. These three are exactly what the dialects' cast tables can spell.
CASTABLE: tuple[type, ...] = (int, float, bool)


@dataclass(frozen=True, slots=True, eq=False)
class SnakeCast(SnakeValue[T]):
    """An EXPLICIT conversion: `CAST(<source> AS <type>)`, with the type named at the call site.

    It exists because the arithmetic operators are `SnakeValue[T] | T -> SnakeArith[T]` — one single
    `T` — and that is right: promoting `int` to `float` behind the user's back would be the ORM
    deciding. But strictness only holds up with an explicit door, and there was none: `column * 1.0`
    does not type-check, so a real division between two integer columns could not be written at all.

    The TYPE NAME is the dialect's, not this node's. Measured: `CAST(x AS NUMERIC)` answers `0.9` on
    PostgreSQL and `0` on SQLite, whose NUMERIC affinity collapses an integral value back to an
    integer. One spelling would be right on two engines and silently wrong on the third.
    """

    source: SnakeValue[Any]
    as_type: type

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """What it wraps: a cast adds no navigation, and swallowing these would drop the JOIN."""
        return self.source.paths()


@dataclass(frozen=True, slots=True, eq=False)
class SnakeStringAgg(SnakeValue[T]):
    """`STRING_AGG(arg, sep ORDER BY ...)`: a group's values joined into ONE string.

    It gets its own node instead of a member of `SnakeAggFunc` because it is not shaped like the
    others. `SnakeAggregate` emits `FUNC(arg)` uniformly, and this one has a second argument whose
    POSITION differs per engine — and on MySQL is not an argument at all but the `SEPARATOR` keyword.
    Squeezing it into the uniform node would mean the node knowing about engines, which is the one
    thing the graph must never do.

    `order_by` is not decoration: without it the concatenation comes back in whatever order the
    engine chose, so a value somebody READS changes between runs.
    """

    arg: SnakeValue[Any]
    separator: str
    order_by: tuple[SnakeOrder, ...] = ()

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """The argument's and the order's: both of them plan JOINs."""
        paths = list(self.arg.paths())
        for key in self.order_by:
            paths.extend(key.expr.paths())
        return tuple(paths)


def static_type(value: object) -> type | None:
    """The type of an operand when it can be PROVEN, and `None` when it cannot.

    The generic `T` is erased at runtime, so emission cannot read it. What survives is what somebody
    wrote down: a column's compiled type, a cast's declared target, the class of a literal. This
    walks those, and it is deliberately a PROVER rather than an inferrer — the answer is either a
    type somebody stated or nothing at all.

    `None` is not a failure to be papered over. Its only caller uses it to decide whether an engine
    needs a different operator, and reading `None` as a guess would silently turn a decimal division
    into an integer one. Absence of proof leaves the SQL exactly as it was.
    """
    if isinstance(value, SnakeExpr):
        return value.python_type
    if isinstance(value, (SnakeCast, SnakeJsonGet)):
        return value.as_type
    if isinstance(value, SnakeArith):
        # An arithmetic node keeps its operands' type only when BOTH agree. Mixed or unprovable
        # operands make the whole node unprovable, which is what makes nesting safe.
        left = static_type(value.left)
        return left if left is not None and left is static_type(value.right) else None
    if isinstance(value, SnakeValue):
        # Every other node (aggregate, window, function call...) pins its type in the CONSTRUCTOR
        # and does not carry it. Claiming otherwise here would be inventing proof.
        return None
    return type(value)


@dataclass(frozen=True, slots=True, eq=False)
class SnakeAggregate(SnakeValue[T]):
    """Aggregate over a value: `COUNT(*)`, `SUM(col)`, `MIN/MAX(col)`...

    It is a `SnakeValue` (comparable -> HAVING, projectable). `arg` is the aggregated value (`None` =
    `COUNT(*)`); `distinct` marks `COUNT(DISTINCT ...)`. The TYPE is pinned down by the constructors in `functions.py`.
    """

    func: SnakeAggFunc
    arg: SnakeValue[Any] | None = None
    distinct: bool = False

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Propagates the argument's paths (empty in `COUNT(*)`): that is how the aggregate plans its JOINs."""
        return self.arg.paths() if self.arg is not None else ()

    def over(
        self,
        *,
        partition_by: tuple[SnakeValue[Any], ...] | list[SnakeValue[Any]] = (),
        order_by: tuple[SnakeOrder, ...] | list[SnakeOrder] = (),
        frame: SnakeFrame | None = None,
    ) -> SnakeWindow[T]:
        """The same aggregate as a WINDOW: `SUM(x)` -> `SUM(x) OVER (...)`.

        With `GROUP BY` it returns one row per group; as a window, every row with its running total.
        `frame` is what makes that total MOVING instead of cumulative, and it is forwarded whole so
        this door and `SnakeWindow.over` cannot drift apart — including the guard that refuses a
        frame with no order to measure it against.

        The import of `as_window` is local because `window` imports this module and at module level
        that would be a cycle. The ANNOTATIONS are a different matter and used to be lumped in with
        it: `frame` was `Any` and the docstring blamed the same cycle. It never applied — the
        `TYPE_CHECKING` block above already imports `SnakeWindow`, this method's own return type,
        from that very module, and `from __future__ import annotations` means neither name is
        evaluated at runtime. `Any` there switched off the door's type for the checker and crossed
        the strict gate without a word, in a project whose rule is zero `Any`.
        """
        from snakeorm.expressions.window import as_window

        return as_window(self).over(
            partition_by=partition_by, order_by=order_by, frame=frame
        )


class SnakeSubqueryAggregate(SnakeValue[T]):
    """Scalar aggregation subquery `(SELECT FUNC(arg) FROM child AS alias WHERE correlation)`.

    It is produced by `collection.count()/.sum_()/...`. It does NOT change the cardinality: it is a
    comparable scalar VALUE. The TYPE is pinned down by the constructors of `SnakeCollection`. `arg`
    is the column OF THE CHILD (`None` = `COUNT(*)`), re-anchored to the alias at emission like the
    condition of `.any()`. It contributes no paths to the outer query (empty `paths()`): the
    correlation is resolved at emission. It stores the child table and the correlation pairs.
    """

    __slots__ = ("func", "arg", "child_schema", "child_name", "pairs")

    def __init__(
        self,
        func: SnakeAggFunc,
        arg: SnakeExpr[Any] | None,
        child_schema: str,
        child_name: str,
        pairs: tuple[tuple[str, str], ...],
    ) -> None:
        self.func = func
        self.arg = arg
        self.child_schema = child_schema
        self.child_name = child_name
        self.pairs = pairs

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """A correlated aggregate references no columns of the outer query: no paths."""
        return ()


class SnakeSubquery(SnakeValue[T]):
    """Scalar subquery used as a VALUE: `(SELECT <column> FROM <table> [WHERE ...])`.

    It is produced by `SnakeQuery.as_scalar(column)`. Primitives only (agnostic; it does not import
    `SnakeQuery`, which avoids a cycle). It has its own FROM: it contributes no paths and does not
    correlate. It is used in `.in_(...)`; its params are threaded into the outer numbering at emission.
    """

    __slots__ = ("schema", "name", "column", "where")

    def __init__(
        self, schema: str, name: str, column: str, where: SnakeCondition | None = None
    ) -> None:
        self.schema = schema
        self.name = name
        self.column = column
        self.where = where

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """A subquery has its own FROM: it references no columns of the outer query."""
        return ()


@dataclass(frozen=True, slots=True, eq=False)
class SnakeInSubquery(SnakeCondition):
    """Membership in the result of a scalar subquery: `<value> IN (SELECT ...)`.

    It is produced by `SnakeValue.in_(subquery)`. `left` is the value from the outer query;
    `subquery` is the subquery. It inherits `& | ~`.
    """

    left: SnakeValue[Any]
    subquery: SnakeSubquery[Any]
