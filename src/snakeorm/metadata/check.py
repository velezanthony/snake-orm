"""Immutable metadata of a CHECK constraint: a domain rule the DATABASE enforces."""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm.expressions import SnakeCondition, condition_paths


@dataclass(frozen=True, slots=True)
class SnakeCheckInfo:
    """A `CHECK (...)` rule over the table's columns.

    It stores the `SnakeCondition` as an AST, not as emitted SQL: that keeps the metadata
    engine-agnostic (the dialect supplies quoting and syntax) and the condition is the SAME one
    `.filter()` takes, so it is validated at type-check time (`User.age >= 18` stops compiling if
    you rename `age`).
    """

    condition: SnakeCondition
    name: str | None = None

    def resolved_name(self, table_name: str) -> str:
        """The name the DB knows the constraint by: the explicit one, or `ck_{table}_{columns}`.

        Creation, removal and diff must agree on the name or you create duplicates and drop things
        that do not exist. The columns come from the condition, deduplicated (`age > 0 AND
        age < 150` -> `ck_users_age`).
        """
        if self.name:
            return self.name
        columns: list[str] = []
        for path in condition_paths(self.condition):
            column = path[-1]
            if column not in columns:
                columns.append(column)
        return f"ck_{table_name}_{'_'.join(columns)}"
