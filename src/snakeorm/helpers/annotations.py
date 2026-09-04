"""Utilities over type annotations, shared by two consumers that must not know about each other:
the Model Compiler (which infers `nullable`) and `@snake_result` (the type to coerce an `X | None`
with)."""

from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin


def unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """If the type is `X | None`, returns `(X, True)`; otherwise `(type, False)`.

    It recognises both syntaxes: `Optional[X]` / `Union[X, None]` and PEP 604's `X | None`.
    """
    if get_origin(annotation) in (Union, types.UnionType):
        args = get_args(annotation)
        non_none = tuple(arg for arg in args if arg is not type(None))
        if len(non_none) != len(args):
            return non_none[0], True
    return annotation, False
