"""Resolving a polymorphic hierarchy: who the base is, which table they share and what is banned.

All the judgement about polymorphic inheritance lives HERE (not scattered across the decorator, the
compiler and the linker) so that it cannot decide differently in each place. Python's MRO says who
the base is; there is no `inherits=Animal` because that would be a second source of truth next to
`class Dog(Animal)`.
"""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.metadata import SnakePolymorphicInfo, SnakeTableInfo
from snakeorm.registry import SnakeRegistry


@dataclass(frozen=True, slots=True)
class PolymorphicPlacement:
    """Where a class of the hierarchy lives: its inherited table, its role and its base.

    `table`/`schema`/`database` are `None` when the class is NOT a polymorphic child: "I impose
    nothing, the decorator decides with its usual parameters".
    """

    info: SnakePolymorphicInfo | None = None
    table: str | None = None
    schema: str | None = None
    database: str | None = None
    base: type | None = None
    inherited: frozenset[str] = frozenset()
    """Column names the child inherits from the base, so we know which ones are ITS OWN.

    They get captured here because whoever resolves the hierarchy already had the base's table in
    hand.
    """

    def constructor_fills(self) -> tuple[str, str] | None:
        """The `(column, value)` pair the `__init__` must fill in by itself. `None` if it does not
        apply.

        It lives here, not in the decorator, so it is not recomposed from two loose fields and put
        at risk of getting it wrong.
        """
        if self.info is None or self.info.value is None:
            return None
        return (self.info.column, self.info.value)


def discriminator_column(cls: type) -> str | None:
    """The SQL name of the column marked with `snake_discriminator()`, if there is one.

    It is read from the MODEL (there is no `discriminator="kind"` in the decorator): it avoids a
    second source, and only the field specifier can carry the `init: Literal[False]` that lines
    mypy/pyright up with the runtime.
    """
    from snakeorm.fields import SnakeColumn
    from snakeorm.helpers.inheritance import collect_inherited

    for descriptor in collect_inherited(cls, SnakeColumn).values():
        if descriptor.is_discriminator:
            return descriptor.column_name
    return None


def resolve_polymorphic(
    cls: type,
    discriminator_value: str | None,
    registry: SnakeRegistry,
) -> PolymorphicPlacement:
    """Decide this class's role in a hierarchy, or that it is in none.

    1. Without `snake_discriminator()` nor `discriminator_value` → there is no hierarchy.
    2. With its own `snake_discriminator()` → it is the BASE. The table is its own.
    3. With `discriminator_value` → it is a CHILD. It looks the base up in the MRO and inherits its
       whole table.
    """
    if discriminator_value is None:
        column = discriminator_column(cls)
        if column is None:
            return PolymorphicPlacement()
        return PolymorphicPlacement(info=SnakePolymorphicInfo(column=column))

    base, base_table = _find_base(cls, registry)
    assert base_table.polymorphic is not None  # _find_base guarantees it
    return PolymorphicPlacement(
        info=SnakePolymorphicInfo(
            column=base_table.polymorphic.column, value=discriminator_value
        ),
        table=base_table.name,
        schema=base_table.schema,
        database=base_table.database,
        base=base,
        inherited=frozenset(column.name for column in base_table.columns),
    )


def _find_base(cls: type, registry: SnakeRegistry) -> tuple[type, SnakeTableInfo]:
    """The class of the hierarchy, looked up in the MRO. The FIRST one that opened one wins.

    It walks the class's MRO upwards. In a deep hierarchy the nearest ancestor wins, but its
    `polymorphic.column` is the same as the root's: the answer does not depend on the level, so a
    deep hierarchy is not a special case.
    """
    for ancestor in cls.__mro__[1:]:
        table = registry.table_of(ancestor)
        if table is not None and table.polymorphic is not None:
            return ancestor, table
    raise SnakeModelDefinitionError(
        f"{cls.__name__} declares `discriminator_value`, but none of its base classes opens a "
        f"polymorphic hierarchy. Add `discriminator='<column>'` to the `@snake_model` of the base, "
        f"and make sure {cls.__name__} inherits from it in Python."
    )


def guard_child_columns(
    cls: type, compiled: SnakeTableInfo, placement: PolymorphicPlacement
) -> None:
    """A child's OWN columns have to be nullable.

    The whole hierarchy shares ONE table, so `Dog`'s `breed` column also exists in `Cat`'s rows,
    where there is no value: a `NOT NULL` would make inserting a cat impossible. It gets checked at
    declaration time (fixable with `| None`), not when inserting in production. It operates on the
    ALREADY compiled table, without recompiling.
    """
    if placement.base is None:  # not a polymorphic child: there is nothing to check
        return
    not_nullable = [
        column.name
        for column in compiled.columns
        if column.name not in placement.inherited and not column.nullable
    ]
    if not_nullable:
        raise SnakeModelDefinitionError(
            f"The columns that belong to {cls.__name__} itself have to accept NULL, and "
            f"{not_nullable} do not. The whole hierarchy shares the table of "
            f"{placement.base.__name__}, so those "
            f"columns also exist in the rows of its siblings, where there is nothing to put in "
            f"them. Declare them as `SnakeColumn[T | None]`."
        )
