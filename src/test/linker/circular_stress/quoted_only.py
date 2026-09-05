"""Quotes and NO `from __future__ import annotations`: the spelling the standard library documents.

This is the pairing the typing spec itself shows — `if TYPE_CHECKING:` for the import, a forward
reference for the annotation — and until now every fixture in this package carried the future import
instead, so the combination went untested. The two mechanisms answer DIFFERENT questions and a fix
that only worked for one would be a fix nobody could rely on:

    if TYPE_CHECKING     ->  the IMPORT does not run, which is what breaks the cycle
    quotes / __future__  ->  the ANNOTATION is not evaluated

Only the NAME is quoted, never the whole expression. `SnakeToMany` is imported and real, so hiding
it inside the string buys nothing and costs the checker its view of it: a typo in `"SnkToMany[Note]"`
would go unseen until somebody resolved that string.
"""

from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToMany,
    snake_int,
    snake_model,
    snake_to_many,
)
from test.linker.circular_stress import stress_registry

if TYPE_CHECKING:
    from test.linker.circular_stress.quoted_only_target import Quoted


@snake_model(table="stress_quoted", registry=stress_registry)
class Quoter(SnakeModel):
    """Its target is a forward reference the module never imports at runtime."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    items: SnakeToMany["Quoted"] = snake_to_many("owner")
