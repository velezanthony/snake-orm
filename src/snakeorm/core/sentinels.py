"""Sentinels the whole package shares. One module, so no two of them mean the same thing.

A sentinel is worth a module of its own for a reason `None` explains: `None` is a VALUE a column may
legitimately hold, so it cannot also mean "there is nothing here". These do not collide with any
value a database can return.
"""

from __future__ import annotations

from typing import Any, Final


class _NotLoaded:
    """The type of `NOT_LOADED`. A class rather than `object()` so the `repr` says what it is."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<not loaded>"

    def __bool__(self) -> bool:
        """Falsy, and deliberately so: `if row.column` on an unloaded one must not read as a value.

        It never reaches user code through the descriptor —that raises— but it does sit in the
        instance's `__dict__`, where a `vars(row)` or a debugger will meet it.
        """
        return False


NOT_LOADED: Final[Any] = _NotLoaded()
"""Written by hydration into every column a query left out (`only()` / `defer()`).

Typed `Any` on purpose: it is assigned into slots declared as `str`, `int` or whatever the column is,
and the checker has no way to express "this is that type or the sentinel" without infecting every
column's type with a union the user would then have to narrow. The guarantee is upheld at RUNTIME by
the descriptor, which raises rather than ever handing this out.
"""
