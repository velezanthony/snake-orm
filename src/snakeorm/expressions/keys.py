"""The typed composite `IN`: a tuple of columns compared against a set of tuples of values.

`(warehouse_id, product_id) IN ((7, 3), (9, 1))` is standard SQL and all three engines run it, and
until this module the only way to ask for it was one `in_()` per column — which is the CARTESIAN
PRODUCT and also answers `(7, 1)` and `(9, 3)`. On a small fixture the two are indistinguishable,
which is what makes the gap worth closing rather than documenting.

WHY THE COLUMN AND ITS VALUE ARE PAIRED, and not positional (`snake_tuple(a, b).in_([(7, 3)])`): a
positional tuple gives the checker nothing to line up, so with two columns of the same type a
swapped pair passes mypy AND pyright and comes back with the wrong rows in silence. It also needs
one overload per arity, so it has a CEILING, and the identifying relationships this ORM is built
for widen their key one level at a time. Pairing each column with its own value in `set()` lets the
checker bind the type per slot, at any width, with no overloads at all.

WHAT THE CHECKER STILL CANNOT DO is COUNT. A two-column key and a three-column one are both
`SnakeKey[M]`, so the shape of the list is checked here, at build time, and it raises. A warning
would be followed by wrong rows or by SQL no engine parses.

This module builds a `SnakeTupleIn` and stops there: the emitter for that node already exists, and
already falls back to the equivalent OR-of-ANDs on a dialect that declares no `Cap.ROW_CONSTRUCTOR`.
A second node would have needed its own copy of that fallback.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Generic, Self, TypeAlias, TypeVar

from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions.conditional import SnakeCase, SnakeCoalesce, SnakeNullIf
from snakeorm.expressions.expression import (
    SnakeArith,
    SnakeCast,
    SnakeCondition,
    SnakeExpr,
    SnakeJsonGet,
    SnakeSubquery,
    SnakeSubqueryAggregate,
    SnakeSubqueryRow,
    SnakeTupleIn,
    SnakeValue,
)
from snakeorm.expressions.scalar import SnakeDateShift, SnakeFuncCall

T = TypeVar("T")
M = TypeVar("M")

SnakeScalar: TypeAlias = (
    SnakeExpr[T]
    | SnakeArith[T]
    | SnakeCast[T]
    | SnakeJsonGet[T]
    | SnakeCase[T]
    | SnakeCoalesce[T]
    | SnakeNullIf[T]
    | SnakeFuncCall[T]
    | SnakeDateShift[T]
    | SnakeSubquery[T]
    | SnakeSubqueryAggregate[T]
    | SnakeSubqueryRow[T]
)
"""Every `SnakeValue` that may stand on the left of a comparison inside a WHERE.

It is a union and not a base class because NOTHING in the hierarchy separates the two kinds:
`SnakeExpr`, `SnakeCase`, `SnakeAggregate` and `SnakeWindow` are flat siblings under `SnakeValue`.
Without it a `Fleet.depots.count()` reaches `set()` past both checkers, reads like a value, and is
refused by the engine at execution — a bare aggregate belongs in a HAVING, and a window function is
evaluated after the WHERE has already chosen the rows.

A union FAILS IN CLOSED: a scalar node added later and not listed here would be refused while being
perfectly valid. That is why `test_every_value_declares_whether_it_is_scalar.py` walks the package
and demands that every subclass appear either here or in its table of values that cannot — a new
node fails that test on the day it is written, which is the day the decision is cheap.
"""

_Slot: TypeAlias = tuple[SnakeValue[Any], object]
_Fingerprint: TypeAlias = tuple[str, object]


def _fingerprint(slot: SnakeValue[Any]) -> _Fingerprint:
    """What makes two slots THE SAME slot when comparing one key against another.

    A column is its path, which is exact. Anything else is its object identity, and that is a
    deliberate choice to fail in closed: comparing two expressions by their shape would call
    `SUBSTRING(code, 1, 3)` and `SUBSTRING(code, 2, 4)` equal — a FALSE match that emits wrong SQL
    without a word. Refusing two separately built expressions is loud and has an obvious fix; the
    message says it.
    """
    if isinstance(slot, SnakeExpr):
        return ("path", slot.path)
    return ("object", id(slot))


def _describe(slot: SnakeValue[Any]) -> str:
    """How a slot is named in an error message: the column, or the kind of expression it is."""
    if isinstance(slot, SnakeExpr):
        return ".".join(slot.path)
    return type(slot).__name__


def _column_order(model: type) -> dict[str, int]:
    """Where each column of the model sits in its DECLARATION, by SQL name.

    An empty map for a model the registry never compiled: the slots then keep the order they were
    chained in, which is still consistent across the keys because the shape check demands it.
    """
    from snakeorm.registry import registry

    table = registry.table_of(model)
    if table is None:
        return {}
    return {column.name: position for position, column in enumerate(table.columns)}


class SnakeKey(Generic[M]):
    """ONE row of the right-hand side: a column paired with its value, as many times as needed.

    Immutable — `set` returns a new key. A shared prefix is a natural thing to write
    (`base.set(a, 1)` and `base.set(a, 2)` off the same partial key), and with mutation the second
    branch would either overwrite the first or trip the duplicate guard for no reason at all.

    `M` is invariant, which is what makes a `SnakeKey[Truck]` inside a list of `SnakeKey[Province]`
    a type error under both checkers. That is the guard that matters; the runtime one below is for
    whoever runs no checker.
    """

    __slots__ = ("_model", "_slots")

    def __init__(self, model: type[M], slots: tuple[_Slot, ...] = ()) -> None:
        self._model = model
        self._slots = slots

    def set(self, slot: SnakeScalar[T], value: T) -> Self:
        """Pairs one column (or scalar expression) with the value this row compares it against.

        `T` is bound by the SLOT, so the value has to match the column's type: this is the whole
        reason the API is not a positional tuple.
        """
        self._guard_belongs_here(slot)
        seen = _fingerprint(slot)
        if any(_fingerprint(existing) == seen for existing, _ in self._slots):
            raise SnakeEmitError(
                f"'{_describe(slot)}' is already in this key of {self._model.__name__}. A row "
                f"constructor compares each column once, so `(a, a) IN ((1, 2))` is a question "
                f"with no answer. Letting the second value win would be the ORM choosing between "
                f"two things you asked for."
            )
        return type(self)(self._model, (*self._slots, (slot, value)))

    def _guard_belongs_here(self, slot: SnakeValue[Any]) -> None:
        """A BARE column name has to be a column of this model. The type cannot say this.

        `SnakeKey[M]`'s invariance guards the KEY's model, which is what keeps a whole key of another
        table out of the list. It says nothing about where each SLOT came from: `Depot.code` and
        `Stock.city` are both `SnakeExpr[str]`, so both checkers accept either in a key of either
        model, and what would come out is a column of one table inside a filter over another.

        Putting the model into the EXPRESSION would close it and cost too much: `join()` returns
        `SnakeJoinedQuery[T, M]` and is bi-rooted on purpose, so a condition over two models is
        legitimate there. `annotate` documents the same wall in `session/session.py` — a dependent
        bound, which TypeVar bounds cannot be. So the check lives here, where the model IS known.

        It covers a bare name only. A path of more than one element navigates a relationship and
        whether the hop exists is the linker's question; a compound expression is the emitter's.
        Refusing either would forbid a legal filter for not being understood by a check written for
        something else. A model the registry never compiled cannot be checked at all, and is left.
        """
        if not isinstance(slot, SnakeExpr) or len(slot.path) != 1:
            return
        order = _column_order(self._model)
        if not order or slot.path[0] in order:
            return
        raise SnakeEmitError(
            f"'{slot.path[0]}' is not a column of {self._model.__name__}, so it cannot be a slot of "
            f"one of its keys: the filter would name a column of another table. Neither checker "
            f"catches this — a column expression carries its own type but not the model it came "
            f"from — which is why it is refused here."
        )

    def _ordered(self, order: dict[str, int]) -> tuple[_Slot, ...]:
        """The slots in the model's declaration order, whatever order they were chained in.

        This is correctness and not tidiness. Every tuple's values have to line up with the ONE
        column list the emitter writes, and the caller chains freely: trusting each key's insertion
        order would put `(warehouse, product)` on one row and `(product, warehouse)` on the next,
        and the engine would compare a warehouse against a product without complaining — both are
        integers.

        A slot that is not a plain column of this model has no declared position, so it keeps its
        relative order and follows the ones that do. The pairing is still consistent across keys
        because they are all required to present the same slots.
        """

        def position(entry: tuple[int, _Slot]) -> tuple[int, int]:
            index, (slot, _value) = entry
            if isinstance(slot, SnakeExpr) and len(slot.path) == 1:
                declared = order.get(slot.path[0])
                if declared is not None:
                    return (0, declared)
            return (1, index)

        return tuple(slot for _, slot in sorted(enumerate(self._slots), key=position))


class SnakeKeys(Generic[M]):
    """The left-hand side: the tuple of columns, taken from the keys themselves.

    It carries only the model, because the columns are whatever the keys declare — which is what
    lets one API serve any width. What it does is CHECK that they all declare the same ones.
    """

    __slots__ = ("_model",)

    def __init__(self, model: type[M]) -> None:
        self._model = model

    def in_(self, keys: Iterable[SnakeKey[M]]) -> SnakeCondition:
        """`(c1, c2, ...) IN ((v1a, v2a, ...), ...)`, refusing anything that would not be that."""
        rows = list(keys)
        if not rows:
            raise SnakeEmitError(
                f"A composite IN over {self._model.__name__} needs at least one key: there is no "
                f"`IN ()` in SQL."
            )
        order = _column_order(self._model)
        self._guard_models(rows)
        ordered = [self._ordered_slots(key, order) for key in rows]
        self._guard_same_slots(ordered)
        columns = tuple(slot for slot, _ in ordered[0])
        return SnakeTupleIn(
            columns=columns,
            rows=tuple(tuple(value for _, value in row) for row in ordered),
        )

    def _guard_models(self, keys: list[SnakeKey[M]]) -> None:
        """Every key belongs to the model being filtered. Both checkers refuse this already."""
        for key in keys:
            if key._model is not self._model:
                raise SnakeEmitError(
                    f"A key built for {key._model.__name__} cannot go in a composite IN over "
                    f"{self._model.__name__}: its columns belong to another table. Both type "
                    f"checkers refuse this too — `SnakeKey` is invariant in its model."
                )

    def _ordered_slots(
        self, key: SnakeKey[M], order: dict[str, int]
    ) -> tuple[_Slot, ...]:
        """One key's slots, canonicalised, refusing the empty one."""
        if not key._slots:
            raise SnakeEmitError(
                f"A key of {self._model.__name__} has no columns: it would emit `() IN (())`, "
                f"which is not SQL on any engine. Add at least one `.set(column, value)`."
            )
        return key._ordered(order)

    def _guard_same_slots(self, ordered: list[tuple[_Slot, ...]]) -> None:
        """Every key presents the SAME columns, in the same canonical order.

        Two failures live here and only one of them is visible. A key of a different WIDTH emits SQL
        no engine parses, so it is caught either way. Two keys of the same width over DIFFERENT
        columns is the quiet one: the shapes agree, the second row's values line up against the
        first row's columns, and `units` compared against `product_id` is two integers and no
        complaint from anywhere.
        """
        first = [_fingerprint(slot) for slot, _ in ordered[0]]
        for position, row in enumerate(ordered[1:], start=2):
            current = [_fingerprint(slot) for slot, _ in row]
            if current == first:
                continue
            if len(current) != len(first):
                raise SnakeEmitError(
                    f"The keys of this composite IN over {self._model.__name__} are not the same "
                    f"width: the first has {len(first)} columns and key {position} has "
                    f"{len(current)}. Every row of a row constructor compares against the same "
                    f"column list."
                )
            mine = [_describe(slot) for slot, _ in ordered[0]]
            theirs = [_describe(slot) for slot, _ in row]
            unstated = (
                " A slot that is not a plain column is matched by identity, so two separately "
                "built expressions never match: bind it to a name and pass the same expression "
                "object to every key."
                if any(kind == "object" for kind, _ in first + current)
                else ""
            )
            raise SnakeEmitError(
                f"Key {position} of this composite IN over {self._model.__name__} is over "
                f"different columns from the first: {theirs} instead of {mine}. Both are the same "
                f"width, so the values would have been compared against the wrong columns without "
                f"any engine objecting.{unstated}"
            )


def snake_key(model: type[M]) -> SnakeKey[M]:
    """Starts one row of a composite IN. Chain `.set(column, value)` once per column."""
    return SnakeKey(model)


def snake_keys(model: type[M]) -> SnakeKeys[M]:
    """Starts a composite IN over this model. Feed it the keys with `.in_([...])`."""
    return SnakeKeys(model)
