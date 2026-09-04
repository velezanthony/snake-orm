"""Immutable metadata of the primary key (simple or composite)."""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm.metadata.column import SnakeColumnInfo


@dataclass(frozen=True, slots=True)
class SnakePrimaryKeyInfo:
    """Primary key as a tuple of columns.

    ONE single structure for a simple PK (1 column) and a composite one (N columns): no special
    cases. Order is preserved because it matters for mapping FKs by position.
    """

    columns: tuple[SnakeColumnInfo, ...]

    @property
    def is_composite(self) -> bool:
        """Tells whether the key spans more than one column."""
        return len(self.columns) > 1
