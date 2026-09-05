"""The @snake_result decorator: a TYPED result container for `session.annotate()`.

You declare a class that inherits from `SnakeResult[Model]`: EXACTLY one field is the
`@snake_model` model (the base row, = the generic parameter) and the rest are scalars.
`@dataclass_transform` types its `__init__`.

```python
@snake_result
class RealmStats(SnakeResult[Realm]):
    realm: Realm          # the base row (a @snake_model), matching the SnakeResult[Realm] parameter
    forge_count: int      # an aggregate
    avg_size: float
```

Inheriting from `SnakeResult[Model]` serves to (a) reject in the checker a class that does not
inherit and give `annotate` the concrete return type (`list[RealmStats]`), and (b) validate at
runtime that the generic matches the base field and that the query is over that model.

A typing NOTE: the STATIC tie between query and base model (catching
`annotate(query_of_AnotherModel, RealmStats)`) is NOT expressible under `annotate(query, result)`:
it would demand a dependent bound `R <: SnakeResult[T]`, and `TypeVar` bounds cannot be generic
(mypy and pyright both reject it). That is why that mismatch stays as a runtime validation
(`SnakeEmitError`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Generic,
    TypeVar,
    dataclass_transform,
    get_args,
    get_origin,
    get_type_hints,
)

from snakeorm.helpers.annotations import unwrap_optional
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.registry import registry

T = TypeVar("T")
TModel = TypeVar("TModel")

# The key where the compiled SnakeResultInfo is stored on the decorated class.
_RESULT_INFO_KEY = "__snake_result__"


class SnakeResult(Generic[TModel]):
    """Generic base of a `@snake_result` container; the parameter is the base model (the row).

    A typing marker with no runtime (see the module note). `TModel` MUST match the base field
    declared in the subclass (`@snake_result` verifies it).
    """

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class SnakeResultInfo:
    """Compiled metadata of a `@snake_result`: the base row and the scalars, in order.

    `scalars` preserves the declaration order: the session projects the aggregates in that order
    behind the columns of the base model.
    """

    base_field: str
    base_model: type
    scalars: tuple[tuple[str, type], ...]


@dataclass_transform()
def snake_result(cls: type[T]) -> type[T]:
    """Compile the class into a typed result container and install its `__init__` (a dataclass).

    The ONLY annotation that is a `@snake_model` is the base row; the rest are scalars. A scalar
    `X | None` compiles to `X` (the correct declaration for SUM/AVG/MIN/MAX, NULL over zero rows;
    the unwrapped type is the key of the coercion converter, and `coerce` does not touch nulls).

    It fails with `SnakeModelDefinitionError` if: there are 0 or 2+ base models; it does not
    inherit from `SnakeResult[Model]`; it inherits without parametrising; or the generic does not
    match the base field.
    """
    if not (isinstance(cls, type) and issubclass(cls, SnakeResult)):
        raise SnakeModelDefinitionError(
            f"{cls.__name__} does not inherit from SnakeResult[Model]: a @snake_result has to be "
            f"declared as `class {cls.__name__}(SnakeResult[YourModel])` so that "
            f"session.annotate(...) accepts it and returns a typed list."
        )

    hints = get_type_hints(cls)
    base_fields: list[tuple[str, type]] = []
    scalars: list[tuple[str, type]] = []
    for name, annotation in hints.items():
        declared, _ = unwrap_optional(annotation)
        if isinstance(declared, type) and registry.table_of(declared) is not None:
            base_fields.append((name, declared))
        else:
            scalars.append((name, declared))

    if len(base_fields) > 1:
        names = ", ".join(name for name, _ in base_fields)
        raise SnakeModelDefinitionError(
            f"{cls.__name__} declares {len(base_fields)} base models ({names}); a @snake_result "
            f"has to have EXACTLY one. The expected shape: one @snake_model field (the base row) "
            f"and the rest scalars (int, float, str...)."
        )
    if not base_fields:
        raise SnakeModelDefinitionError(
            f"{cls.__name__} declares not a single base model: there is nothing to annotate. A "
            f"@snake_result needs EXACTLY one @snake_model field (the base row) plus the "
            f"scalars that session.annotate(...) will fill in."
        )

    base_field, base_model = base_fields[0]
    _validate_generic_parameter(cls, base_field, base_model)
    info = SnakeResultInfo(
        base_field=base_field, base_model=base_model, scalars=tuple(scalars)
    )
    result_cls = dataclass(cls)
    setattr(result_cls, _RESULT_INFO_KEY, info)
    return result_cls


def _validate_generic_parameter(cls: type, base_field: str, base_model: type) -> None:
    """Check that the subclass's `SnakeResult[Model]` matches the `@snake_model` base field.

    It reads the generic off `__orig_bases__`. It fails if it was inherited without parametrising
    or if the model is not the one of the base field: the static type and the runtime metadata
    must tell the same story.
    """
    declared = _declared_base_model(cls)
    if declared is _UNPARAMETRIZED:
        raise SnakeModelDefinitionError(
            f"{cls.__name__} inherits SnakeResult without the base model; declare "
            f"`SnakeResult[{base_model.__name__}]` so that the type matches field '{base_field}'."
        )
    if declared is not base_model:
        declared_name = getattr(declared, "__name__", repr(declared))
        raise SnakeModelDefinitionError(
            f"{cls.__name__} inherits SnakeResult[{declared_name}], but its base field "
            f"'{base_field}' is {base_model.__name__}: they do not match. The generic parameter "
            f"has to be the SAME model as the base row."
        )


# A sentinel to tell "SnakeResult without parameters" apart from a parameter that does exist.
_UNPARAMETRIZED = object()


def _declared_base_model(cls: type) -> object:
    """Model of the bases' `SnakeResult[Model]` parameter; `_UNPARAMETRIZED` if there is none."""
    for base in getattr(cls, "__orig_bases__", ()):
        if get_origin(base) is SnakeResult:
            args = get_args(base)
            return args[0] if args else _UNPARAMETRIZED
    return _UNPARAMETRIZED


def snake_result_info(cls: type) -> SnakeResultInfo:
    """Return the compiled SnakeResultInfo of a `@snake_result` class; fail if it is not one."""
    info = getattr(cls, _RESULT_INFO_KEY, None)
    if not isinstance(info, SnakeResultInfo):
        raise SnakeModelDefinitionError(
            f"{cls.__name__} is not a @snake_result: it cannot be used in session.annotate(...)."
        )
    return info
