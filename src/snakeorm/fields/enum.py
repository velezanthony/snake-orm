"""Declaring enumeration columns: `snake_enum(...)`."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields.column import MISSING, SnakeColumn
from snakeorm.metadata import SnakeEnumStorage

E = TypeVar("E", bound=Enum)


def snake_enum(
    enum_type: type[E],
    *,
    storage: SnakeEnumStorage = SnakeEnumStorage.CHECK,
    default: E | object = MISSING,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
) -> Any:
    """Declare a column whose value is a member of a `StrEnum` or an `IntEnum`.

        status: SnakeColumn[Status] = snake_enum(Status, default=Status.ACTIVE)
        reason: SnakeColumn[Status | None] = snake_enum(Status)   # nullable by the annotation

    `default=Status.ACTIVE` must be a MEMBER of the enum: passing `"active"` or `42` is rejected by
    a runtime guard (the `| object` in the signature stops the checker from catching it; without
    the guard, an invalid default reached the DDL silently).

    No `nullable` (the annotation states nullability). `storage` picks which DB object backs the
    rule (see `SnakeEnumStorage`).
    """
    if not (isinstance(enum_type, type) and issubclass(enum_type, Enum)):
        raise SnakeModelDefinitionError(
            f"snake_enum expects an enum class; got {enum_type!r}."
        )
    if not issubclass(enum_type, (int, str)):
        raise SnakeModelDefinitionError(
            f"{enum_type.__name__} has to be a StrEnum or an IntEnum: those are the ones that bring a "
            f"base type (str or int) to store them with. A bare Enum with arbitrary values has no "
            f"obvious representation in SQL, and guessing one would be worse than refusing."
        )
    if default is not MISSING and not isinstance(default, enum_type):
        raise SnakeModelDefinitionError(
            f"default={default!r} is not a member of {enum_type.__name__}. Pass a MEMBER of the "
            f"enum (e.g. {enum_type.__name__}.{next(iter(enum_type)).name}), not its raw value: a "
            f"default that does not belong to the enum would end up as a loose literal in the DDL's DEFAULT."
        )
    column: SnakeColumn[Any] = SnakeColumn(
        primary_key=primary_key,
        unique=unique,
        default=default,
        index=index,
        name=name,
        db_comment=db_comment,
    )
    column.enum_type = enum_type
    column.enum_storage = storage
    return column
