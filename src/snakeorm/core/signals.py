"""CODE signals: `PRE_SAVE` / `POST_SAVE` / `PRE_DELETE` / `POST_DELETE`.

The difference from `snake_trigger` (one of GUARANTEE, not of implementation): a trigger lives in
the schema and always holds; a signal lives in the app and only fires if the write goes through the
session —which is why it NEVER guarantees integrity; if it must always hold, it is a trigger. The
handlers run INSIDE the transaction: if one raises, the write is undone.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from enum import Enum
from typing import TypeVar

from snakeorm.core.exceptions import SnakeWarning

T = TypeVar("T")

Handler = Callable[[object], None]
"""A handler receives the instance and returns nothing."""


class SnakeSignal(Enum):
    """The moment a handler fires relative to the write."""

    PRE_SAVE = "pre_save"
    POST_SAVE = "post_save"
    PRE_DELETE = "pre_delete"
    POST_DELETE = "post_delete"


_HANDLERS: dict[tuple[type, SnakeSignal], list[Handler]] = {}
"""Connected handlers, by (model, signal). Module-global, like the registry."""


def snake_on(
    model: type[T], signal: SnakeSignal
) -> Callable[[Callable[[T], None]], Callable[[T], None]]:
    """Connects a handler to a model's signal. Returns the function untouched.

        @snake_on(Order, SnakeSignal.POST_SAVE)
        def notify(order: Order) -> None:
            ...

    The handler receives the instance with the model's TYPE (to the checker it is a `Order`, not
    `Any`).
    """

    def decorator(handler: Callable[[T], None]) -> Callable[[T], None]:
        connect(model, signal, handler)
        return handler

    return decorator


def connect(model: type[T], signal: SnakeSignal, handler: Callable[[T], None]) -> None:
    """Connects a handler without the decorator (handy for connecting at runtime)."""
    _HANDLERS.setdefault((model, signal), []).append(handler)  # type: ignore[arg-type]


def disconnect_all(model: type | None = None) -> None:
    """Disconnects a model's handlers, or ALL of them if none is given (mostly for tests: the
    dictionary is global and a handler left in place contaminates the ones that follow)."""
    if model is None:
        _HANDLERS.clear()
        return
    for key in [key for key in _HANDLERS if key[0] is model]:
        del _HANDLERS[key]


def signals_of(model: type) -> tuple[SnakeSignal, ...]:
    """The signals that model has connected. The bulk-write warning uses it."""
    return tuple(
        sorted(
            {key[1] for key in _HANDLERS if key[0] is model and _HANDLERS[key]},
            key=lambda signal: signal.value,
        )
    )


def models_with_signals() -> tuple[type, ...]:
    """The models that have any signal connected. The `check` command lists them."""
    return tuple({key[0] for key in _HANDLERS if _HANDLERS[key]})


def emit(model: type, signal: SnakeSignal, instance: object) -> None:
    """Fires the handlers of `(model, signal)` in connection order.

    Exceptions are deliberately not caught: if a handler fails, the write must be undone with it.
    """
    for handler in _HANDLERS.get((model, signal), ()):
        handler(instance)


def warn_bulk_skips_signals(model: type, operation: str) -> None:
    """Warns that a BULK write is not going to fire the model's signals.

    Neither an error (bulk writing is legitimate) nor silence (the `queryset.update()` trap in
    Django): the bulk path resolves the UPDATE in the engine without fetching the rows, and firing
    them would force a SELECT of N rows — the very N+1 the rest of the ORM avoids. So we warn.
    """
    signals = signals_of(model)
    if not signals:
        return
    names = ", ".join(signal.value for signal in signals)
    warnings.warn(
        f"{operation}() over '{model.__name__}' does NOT fire its signals ({names}): a bulk write "
        f"is resolved by the engine without fetching the rows. If that logic has to run here, walk "
        f"the rows and use update()/delete() on each one; if it has to hold ALWAYS — outside the ORM "
        f"too — move it into a trigger.",
        SnakeWarning,
        stacklevel=3,
    )
