"""POLYMORPHIC inheritance: several classes share ONE table and are told apart by a column.

Against concrete inheritance (a table per class, duplicated columns), here `session.all(Animal)`
returns `Dog`/`Cat` with their real class and `session.all(Dog)` filters by the discriminator.
The metadata is just two strings (column and value): no references to Python classes, because this
travels into a rendered migration file and a class reference would couple it to the generating code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SnakePolymorphicInfo:
    """How a class takes part in a polymorphic hierarchy.

    `column` (the discriminator) is carried by every class. `value` is `None` on the BASE (which
    sees the whole hierarchy) and, on each CHILD, its own value, used as an automatic filter and on
    insert. An optional field instead of a separate `is_base`: two fields would allow illegal
    combinations.
    """

    column: str
    value: str | None = None

    @property
    def is_base(self) -> bool:
        """The root of the hierarchy: the one that sees every row, no discriminator filter."""
        return self.value is None
