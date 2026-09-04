"""Declaring indexes: SnakeIndex (used in the body of the model)."""

from __future__ import annotations

from typing import Any

from snakeorm.expressions import SnakeCondition, SnakeExpr
from snakeorm.fields.column import SnakeColumn
from snakeorm.metadata import SnakeIndexMethod


class SnakeIndex:
    """Declare an index referencing the model's LOCAL columns (typed, no strings).

    It holds references to the descriptors; the names get resolved at compile time, once
    `__set_name__` has run. `where` (a PARTIAL index) and `method` are also declared here.
    """

    def __init__(
        self,
        *columns: SnakeColumn[Any] | SnakeExpr[Any],
        unique: bool = False,
        name: str | None = None,
        where: SnakeCondition | None = None,
        method: SnakeIndexMethod | None = None,
    ) -> None:
        self._columns = columns
        self.unique = unique
        self.name = name
        # PARTIAL index: it only indexes the rows that satisfy the condition. With `unique=True`
        # it comes out as a unique index, not a constraint (Postgres has no `UNIQUE ... WHERE`).
        self.where = where
        self.method = method

    def column_names(self) -> tuple[str, ...]:
        """SQL names of the index columns, whether they come as a DESCRIPTOR or as an EXPRESSION.

        Both cases because of the project's dual behaviour: inside the body, `name` is the raw
        descriptor (its name resolved at compile time); outside, `Customer.name` is CLASS access →
        `SnakeExpr`. Accepting only the descriptor left `SnakeIndex` useless outside the body,
        which is exactly where a PARTIAL index gets declared.
        """
        return tuple(
            column.path[-1] if isinstance(column, SnakeExpr) else column.column_name
            for column in self._columns
        )
