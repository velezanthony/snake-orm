"""Resolving a model NAME the way the module that wrote it means it.

A class name does not identify a model: two apps can each declare a `Customer`, and the registry's
by-name index keeps whichever registered LAST. Asking it is bug #14, and it does not fail — it
returns a valid answer about the wrong table.

Annotations never had the problem: `get_type_hints` evaluates against the MODULE's globals, so each
file resolves its own `Post`. This does the same for names that arrive as ARGUMENTS
(`through="Tagging"`), so one declaration stops having two rules on adjacent lines.

Two callers, one reader. `resolve_in_module` answers about ONE name; `type_checking_names` answers
about the whole block, for `linker.hints_of`, which resolves a model's annotations all at once. They
share `_type_checking_imports` so a spelling one understands is a spelling the other does too.

Two layers, in this order:

1. The module's globals. Covers the forward declaration — the class comes later in the same file —
   because `snake_link()` runs at the end. Costs nothing.
2. The `if TYPE_CHECKING:` block, read from source. Covers the real circular import, where the name
   is never in globals and `get_type_hints` raises `NameError`.

If neither has it, it REFUSES naming both ways out. Falling back to the global index is what this
module exists to stop.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def resolve_in_module(owner: type, name: str) -> type | None:
    """The class `name` refers to, as seen from the module that declared `owner`.

    `None` when the module cannot see it at all — the caller decides how to complain, because it is
    the one that knows what the name was for.
    """
    module = sys.modules.get(owner.__module__)
    if module is None:  # pragma: no cover - a class whose module was unloaded
        return None
    found = getattr(module, name, None)
    if isinstance(found, type):
        return found
    return _from_type_checking(module, name)


def type_checking_names(owner: type) -> dict[str, type]:
    """Every class the OWNER's module imports under `if TYPE_CHECKING:`, imported for real.

    The same reading as `resolve_in_module`'s second layer, answering for the whole block instead of
    one name — because the caller that needs it, `get_type_hints`, resolves a model's annotations
    ALL AT ONCE and cannot be asked about them one at a time.

    Empty when there is no block, no source, or nothing importable in it. That is not a failure: the
    caller passes this as extra scope, and extra scope that adds nothing simply changes nothing.
    """
    module = sys.modules.get(owner.__module__)
    if module is None:  # pragma: no cover - a class whose module was unloaded
        return {}
    found: dict[str, type] = {}
    for module_name, local, attribute in _type_checking_imports(module):
        imported = _import(module_name, attribute)
        if imported is not None:
            found[local] = imported
    return found


def _from_type_checking(module: ModuleType, name: str) -> type | None:
    """The class a `if TYPE_CHECKING:` import names, imported for real, or `None`.

    This block is invisible at runtime by design, so the only way to read it is from the SOURCE. It
    is the one case layer 1 cannot cover: a genuine circular import between two modules, where the
    runtime import never happens.

    Importing the named module HERE is safe in a way it would not have been at declaration time: by
    the time anything asks, the cycle that made the author write `TYPE_CHECKING` is over.
    """
    for module_name, local, attribute in _type_checking_imports(module):
        if local != name:
            continue
        imported = _import(module_name, attribute)
        if imported is not None:
            return imported
    return None


def _type_checking_imports(module: ModuleType) -> list[tuple[str, str, str]]:
    """Every `from X import Y [as Z]` inside the module's type-checking blocks.

    `(module, bound name, attribute)`, in source order. It is one reader for the two questions asked
    of the block —one name, or all of them— so a spelling either understands is a spelling both do.
    Splitting it was how `through=` and the annotations came to disagree in the first place.
    """
    try:
        source = inspect.getsource(module)
    except (OSError, TypeError):  # pragma: no cover - a module with no source on disk
        return []
    found: list[tuple[str, str, str]] = []
    for statement in ast.parse(source).body:
        if not isinstance(statement, ast.If) or not _is_type_checking(statement.test):
            continue
        for node in statement.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            absolute = _absolute(node, module)
            if absolute is None:
                continue
            for alias in node.names:
                found.append((absolute, alias.asname or alias.name, alias.name))
    return found


def _absolute(node: ast.ImportFrom, module: ModuleType) -> str | None:
    """The module an import names, with `from .sibling import X` resolved against its package.

    Relative imports are the ordinary way to write one inside a package, so skipping them would drop
    the pair back onto the bare `NameError` this fallback exists to stop. Resolving them is not a
    guess: the module carries its own `__package__` and `importlib.util.resolve_name` is what the
    import system itself uses. `None` only when there is no package to resolve against.
    """
    if not node.level:
        return node.module
    package = getattr(module, "__package__", None)
    if (
        not package
    ):  # pragma: no cover - a relative import outside any package cannot be executed
        return None
    try:
        return importlib.util.resolve_name(
            f"{'.' * node.level}{node.module or ''}", package
        )
    except (
        ImportError,
        ValueError,
    ):  # pragma: no cover - more dots than the package is deep
        return None


def _is_type_checking(test: ast.expr) -> bool:
    """Whether an `if` guards on `TYPE_CHECKING`, spelled bare or as `typing.TYPE_CHECKING`."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _import(module_name: str, attribute: str) -> type | None:
    """Imports `module_name` and returns its `attribute`, or `None` if either step fails.

    Failures come back as `None` rather than raising: this is one of two layers, and a module that
    cannot be imported is a name this layer cannot answer for — not an error in itself. The caller
    refuses once, with both ways out named.
    """
    try:
        found = getattr(importlib.import_module(module_name), attribute, None)
    except ImportError:
        return None
    return found if isinstance(found, type) else None
