"""The @snake_row decorator: a typed ROW container for `session.call(...)`.

A function/procedure is OPAQUE SQL: the ORM cannot verify what it returns. The contract is
DECLARED, not verified: the user declares the expected shape (a @snake_row whose fields are ALL
scalars) and the session hydrates each row into it (the same guarantee as reading a raw SELECT into
a dataclass).

```python
@snake_row
class Payroll(SnakeRow):
    employee_id: int
    gross: Decimal
    net: Decimal

rows: list[Payroll] = session.call("calculate_payroll", [1234], into=Payroll)
```

The difference with `@snake_result`: this one has NO base model, all its fields are scalars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, dataclass_transform, get_type_hints

from snakeorm.helpers.annotations import unwrap_optional
from snakeorm.core.exceptions import SnakeModelDefinitionError

T = TypeVar("T")

# The key where the compiled SnakeRowInfo is stored on the decorated class.
_ROW_INFO_KEY = "__snake_row__"


class SnakeRow:
    """Marker base for a `@snake_row`: a container of scalar rows, WITHOUT a base model.

    A typing marker with no runtime: `session.call` bounds its `into` to `type[R]` with
    `R: SnakeRow`, so a class that does not inherit from here is rejected IN THE CHECKER.
    """

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class SnakeRowInfo:
    """Compiled metadata of a `@snake_row`: its columns (name + type), in order.

    `columns` preserves the declaration order: `session.call` maps each row by POSITION (field
    order == column order of the function).
    """

    columns: tuple[tuple[str, type], ...]


@dataclass_transform()
def snake_row(cls: type[T]) -> type[T]:
    """Compile the class into a typed row container and install its `__init__` (a dataclass).

    A field `X | None` compiles to `X` (the key of the coercion converter; the `None` survives
    because `coerce` does not touch nulls). It fails with `SnakeModelDefinitionError` if it does
    not inherit from `SnakeRow`.
    """
    if not (isinstance(cls, type) and issubclass(cls, SnakeRow)):
        raise SnakeModelDefinitionError(
            f"{cls.__name__} does not inherit from SnakeRow: a @snake_row has to be declared as "
            f"`class {cls.__name__}(SnakeRow)` so that session.call(...) accepts it and returns "
            f"a typed list."
        )

    hints = get_type_hints(cls)
    columns: list[tuple[str, type]] = []
    for name, annotation in hints.items():
        declared, _ = unwrap_optional(annotation)
        columns.append((name, declared))

    info = SnakeRowInfo(columns=tuple(columns))
    row_cls = dataclass(cls)
    setattr(row_cls, _ROW_INFO_KEY, info)
    return row_cls


def snake_row_info(cls: type) -> SnakeRowInfo:
    """Return the compiled SnakeRowInfo of a `@snake_row` class; fail if it is not one."""
    info = getattr(cls, _ROW_INFO_KEY, None)
    if not isinstance(info, SnakeRowInfo):
        raise SnakeModelDefinitionError(
            f"{cls.__name__} is not a @snake_row: it cannot be used in session.call(...)."
        )
    return info
