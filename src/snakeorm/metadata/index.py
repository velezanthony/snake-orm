"""Immutable metadata of an index."""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm.expressions import SnakeCondition
from snakeorm.metadata.index_method import SnakeIndexMethod


@dataclass(frozen=True, slots=True)
class SnakeIndexInfo:
    """Index over one or more of the table's columns. 1 column = simple, N = composite."""

    columns: tuple[str, ...]
    unique: bool = False
    name: str | None = None
    # PARTIAL index: only indexes the rows that satisfy the condition (`WHERE deleted_at IS NULL`).
    # It is what makes soft-delete and multi-tenancy usable.
    where: SnakeCondition | None = None
    # Access method, engine-agnostic (the dialect translates it). `None` = the default one.
    method: SnakeIndexMethod | None = None

    @property
    def is_constraint(self) -> bool:
        """Whether it produces a uniqueness CONSTRAINT instead of an index.

        A plain `unique=True` is a constraint (`uq_*`); a PARTIAL one cannot be (Postgres does not
        accept `CONSTRAINT ... UNIQUE ... WHERE`), so with `where=` uniqueness is a unique index and
        nothing more.
        """
        return self.unique and self.where is None

    def resolved_name(self, table_name: str) -> str:
        """The name the DB knows the object by: the explicit one, or the one generated from its type.

        The prefix says which object it is (`uq_` constraint, `ix_` index). It lives here and not in
        the DDL emitter because the diff needs the same name as creation and removal, or it creates
        duplicates and drops things that do not exist.
        """
        if self.name:
            return self.name
        return f"{'uq' if self.is_constraint else 'ix'}_{table_name}_{'_'.join(self.columns)}"
