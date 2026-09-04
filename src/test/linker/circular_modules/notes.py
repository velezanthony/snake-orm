"""The NOTES side. Needs `Account`, which lives in `accounts`, and never imports it at runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_int,
    snake_model,
    snake_str,
    snake_to_one,
)
from test.linker.circular_modules import circular_registry

if TYPE_CHECKING:
    from test.linker.circular_modules.accounts import Account, QuotedAccount


@snake_model(table="circ_notes", registry=circular_registry)
class Note(SnakeModel):
    """Points back at ACCOUNTS. The class, unquoted."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    body: SnakeColumn[str] = snake_str()
    account_id: SnakeColumn[int] = snake_int()
    account: SnakeToOne[Account] = snake_to_one(account_id)


@snake_model(table="circ_quoted_notes", registry=circular_registry)
class QuotedNote(SnakeModel):
    """The same, quoted."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    account_id: SnakeColumn[int] = snake_int()
    account: SnakeToOne["QuotedAccount"] = snake_to_one(account_id)
