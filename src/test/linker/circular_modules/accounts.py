"""The ACCOUNTS side. Needs `Note`, which lives in `notes`, and never imports it at runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToMany,
    snake_int,
    snake_model,
    snake_str,
    snake_to_many,
)
from test.linker.circular_modules import circular_registry

if TYPE_CHECKING:
    # Not imported at runtime: `notes` imports THIS module, so doing it here would be the cycle.
    from test.linker.circular_modules.notes import Note, QuotedNote


@snake_model(table="circ_accounts", registry=circular_registry)
class Account(SnakeModel):
    """Its to-many crosses the module boundary, written as the class and not as a string."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    handle: SnakeColumn[str] = snake_str()
    notes: SnakeToMany[Note] = snake_to_many("account")


@snake_model(table="circ_quoted_accounts", registry=circular_registry)
class QuotedAccount(SnakeModel):
    """The same thing written as a STRING, which has to resolve exactly the same way."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    notes: SnakeToMany["QuotedNote"] = snake_to_many("account")
