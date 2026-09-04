"""Row hydration: the HOTTEST path of the ORM, with the plan compiled ONCE per table.

Which attribute, which converter (or none) and in which position is FIXED per table, so it gets
compiled once and reused instead of being resolved per row. It writes straight into the descriptor's
storage key WITHOUT calling the constructor (exactly what its `__set__` does): validating arguments
and applying defaults is pointless work when the values come from the database itself.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from snakeorm.registry import registry_of
from snakeorm.metadata import SnakeTableInfo
from snakeorm.core.sentinels import NOT_LOADED
from snakeorm.session.coercion import converter_for

T = TypeVar("T")

_Instruction = tuple[str, Callable[[object], object] | None]
"""(storage key, converter, or None if the value passes through as is)."""

_Dispatch = tuple[int, dict[str, type]] | None
"""(position of the discriminator in the row, value -> subclass). `None` on a normal table.

Resolved HERE and not per row: the position and the map are fixed per table (resolving them per row
cost 55% more on the hot path).
"""

_Entry = tuple[SnakeTableInfo, tuple[_Instruction, ...], tuple[int, ...], _Dispatch]
"""(table that generated it, instructions, PK positions, polymorphic dispatch)."""

_CACHE: dict[tuple[type, type], _Entry] = {}
"""Compiled plan, indexed by (model being INSTANTIATED, model whose TABLE was read).

It is indexed by models (not by `id(table)`, which leaked: every `snake_link()` creates new tables).
The second element tells polymorphism apart, where `Dog` is hydrated from TWO row shapes (its own
and `Animal`'s). The table is stored TOO and the REFERENCE is compared, so a relink invalidates the
old plan.
"""

_DISCARD = ""
"""Storage key of a column the row carries and this class does NOT have.

It happens under polymorphism: `Animal`'s row includes `Cat`'s `lives` column, and when hydrating a
`Dog` that value goes nowhere; writing it would leave a phantom attribute, so it gets thrown away.
"""


def _compile(
    table: SnakeTableInfo, own: frozenset[str] | None
) -> tuple[_Instruction, ...]:
    """Translates the columns into instructions: where to write and which conversion applies, if any.

    `own` are the column names the class being instantiated really declares. With `None` — the normal
    case — they are all assumed to be its own. Only polymorphism passes a set: there the row comes
    from the BASE's table and carries columns of the sibling classes.
    """
    return tuple(
        (
            f"__snake_{column.attr_name or column.name}"
            if own is None or column.name in own
            else _DISCARD,
            converter_for(column.python_type, column.scale),
        )
        for column in table.columns
    )


def _entry(model: type, table: SnakeTableInfo, owner: type) -> _Entry:
    """The entry for that pair, compiling it the first time and redoing it if the table changed.

    Everything precomputed lives in ONE entry so it gets invalidated in one go (two caches = two
    sources of truth).
    """
    key = (model, owner)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] is table:
        return cached
    names = [column.name for column in table.columns]
    entry: _Entry = (
        table,
        _compile(table, _own_columns(model) if owner is not model else None),
        tuple(names.index(pk.name) for pk in table.primary_key.columns),
        _dispatch(table, names, model),
    )
    _CACHE[key] = entry
    return entry


def _own_columns(model: type) -> frozenset[str] | None:
    """The column names THAT model declares, so its siblings' ones can be discarded."""
    table = registry_of(model).table_of(model)
    return None if table is None else frozenset(column.name for column in table.columns)


def _dispatch(table: SnakeTableInfo, names: list[str], owner: type) -> _Dispatch:
    """Where the discriminator is and which class each value stands for. `None` if there is no hierarchy.

    Only the BASE dispatches: querying a child already filters by its value. The map is frozen along
    with the plan and invalidated by the table's reference, which is why linking is an explicit pass
    at the end.
    """
    if table.polymorphic is None or not table.polymorphic.is_base:
        return None
    if (
        table.polymorphic.column not in names
    ):  # pragma: no cover - the compiler guarantees it
        return None
    # The OWNER's registry, not the global one. Asking the global one for a model that lives in
    # a private registry returns `{}`, and `{}` is falsy, so the dispatch simply switches off:
    # every row of a polymorphic hierarchy hydrates as the BASE class, with no error anywhere.
    # This is the one site where resolving in the wrong registry stops shouting and starts lying.
    by_value = registry_of(owner).polymorphic_map(table)
    return (names.index(table.polymorphic.column), by_value) if by_value else None


def dispatch_for(model: type, table: SnakeTableInfo) -> _Dispatch:
    """The polymorphic dispatch of that table, resolved ONCE and cached along with the plan."""
    return _entry(model, table, model)[3]


def plan_for(
    model: type, table: SnakeTableInfo, owner: type | None = None
) -> tuple[_Instruction, ...]:
    """The hydration instructions of that model over that row shape."""
    return _entry(model, table, owner if owner is not None else model)[1]


def pk_positions(model: type, table: SnakeTableInfo) -> tuple[int, ...]:
    """Positions of the PK inside the row, computed ONCE (used by the "LEFT JOIN with no partner"
    detection; resolving them per row was O(columns²) on the `include` path)."""
    return _entry(model, table, model)[2]


def partial_plan_for(
    model: type, table: SnakeTableInfo, columns: frozenset[str]
) -> tuple[tuple[_Instruction, ...], tuple[str, ...]]:
    """The plan for a row that carries only SOME columns, plus the keys to mark as not loaded.

    It SLICES the full plan instead of compiling a second one, and that is the point: the two would
    be two answers to "where does column N go", and the day one of them learns about a new converter
    the other keeps the old one. The projection is emitted in the table's declaration order for
    exactly this reason, so position `i` of the row is the `i`-th kept column.

    The second half is what makes the feature safe. Every column left out has its storage key filled
    with `NOT_LOADED`, so the descriptor can tell "you did not ask for this" from "this is `None`"
    — without it a deferred column reads as its default and nobody finds out.

    `_DISCARD` keys are skipped: they belong to a sibling class under polymorphism and writing the
    sentinel there would leave a phantom attribute on an object that never had one.
    """
    full = plan_for(model, table)
    kept: list[_Instruction] = []
    missing: list[str] = []
    for instruction, column in zip(full, table.columns, strict=True):
        if column.name in columns:
            kept.append(instruction)
        elif instruction[0] is not _DISCARD:
            missing.append(instruction[0])
    return tuple(kept), tuple(missing)


def hydrate_partial(
    model: type[T],
    plan: tuple[_Instruction, ...],
    missing: tuple[str, ...],
    row: Sequence[object],
) -> T:
    """Builds an instance from a partial row, marking every absent column as not loaded."""
    instance = _hydrate_with_plan(model, plan, row)
    write = object.__setattr__
    for storage_key in missing:
        write(instance, storage_key, NOT_LOADED)
    return instance


def hydrate(
    model: type[T],
    table: SnakeTableInfo,
    row: Sequence[object],
    owner: type | None = None,
) -> T:
    """Builds an instance with the row's values, in column order.

    No kwargs, no constructor and no resolving converters: the plan already says where each value
    goes and what to do to it. `owner` is the model whose TABLE generated the row; it only differs
    from `model` under polymorphism (the query goes against `Animal` and each row is instantiated as
    a `Dog` or a `Cat`).
    """
    return _hydrate_with_plan(model, plan_for(model, table, owner), row)


def _hydrate_with_plan(
    model: type[T], plan: tuple[_Instruction, ...], row: Sequence[object]
) -> T:
    """The hydration loop with the plan ALREADY resolved: it hoists the resolution OUT of the
    per-row loop (`plan_for`/`dispatch_for` are fixed per table). Whoever maps N rows resolves the
    plan once."""
    instance = object.__new__(model)
    write = object.__setattr__
    for (storage_key, converter), value in zip(plan, row, strict=True):
        if storage_key is not _DISCARD:
            # `or value is None`: a NULL passes through untouched, with no conversion
            # (`_to_bool(None)` would give `False`, `_to_uuid(None)` would blow up). Inline, not in a
            # closure: +132 ns/column.
            write(
                instance,
                storage_key,
                value if converter is None or value is None else converter(value),
            )
    return instance
