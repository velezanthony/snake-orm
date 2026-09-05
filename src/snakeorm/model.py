"""Base class of the SnakeORM models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, dataclass_transform

from snakeorm.core.exceptions import SnakeAggregateNotLoaded
from snakeorm.fields import (
    SnakeIndex,
    snake_auto,
    snake_column,
    snake_datetime,
    snake_datetimetz,
    snake_float,
    snake_time,
    snake_timetz,
    snake_decimal,
    snake_discriminator,
    snake_enum,
    snake_int,
    snake_json,
    snake_str,
    snake_to_many,
    snake_to_many_through,
    snake_to_one,
)
from snakeorm.metadata import SnakeCheckInfo

# Key (with a trailing double underscore: it does NOT get name-mangled) holding, per instance, the
# dict of aggregates `session.annotate(...)` fills in. Absent = the instance was not annotated.
_AGGREGATES_KEY = "__snake_aggregates__"


class _AggregateNamespace:
    """EMERGENCY EXIT for reading annotated aggregates by dynamic name.

    `obj.aggregate.<name>` returns `object` (NEVER `Any`): the name is dynamic, so the checker cannot
    type it and FORCES a `cast()` at the point of use. No IntelliSense and no typo-safety: it is the
    hatch, not the road. The genuinely typed road is `@snake_result` + `session.annotate(...)`, which
    hands you a class with genuinely typed fields.
    """

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, object] | None) -> None:
        self._values = values

    def __getattr__(self, name: str) -> object:
        """Returns the aggregate's annotated value, or explains why it is not available."""
        values = self._values
        if values is None:
            raise SnakeAggregateNotLoaded(
                f"This instance was not annotated: '{name}' only exists after "
                f"session.annotate(query, Result, {name}=<aggregate>). The typed path is "
                f"@snake_result; this is the emergency exit (returns object, demands a cast)."
            )
        if name not in values:
            available = ", ".join(sorted(values)) or "(none)"
            raise SnakeAggregateNotLoaded(
                f"There is no '{name}' aggregate on this instance. Annotations available: "
                f"{available}. Ask for it with session.annotate(query, Result, {name}=<aggregate>)."
            )
        return values[name]


# The tuple is LITERAL: PEP 681 does not accept a constant here (see SNAKE_FIELD_SPECIFIERS in
# `fields/__init__.py`, the canonical reference, which a test ties this literal to).
@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        snake_column,
        snake_auto,
        snake_enum,
        snake_int,
        snake_str,
        snake_decimal,
        snake_datetime,
        snake_datetimetz,
        snake_float,
        snake_time,
        snake_timetz,
        snake_json,
        snake_to_one,
        snake_to_many,
        snake_to_many_through,
        snake_discriminator,
    ),
)
class SnakeModel:
    """Model base: provides the table config at class level, TYPED.

    The settings that reference columns or are documentation (table comment,
    indexes, checks) are declared here and NOT in the decorator. They are annotated
    as `ClassVar` so `dataclass_transform` does not mistake them for model columns.
    """

    SnakeComment: ClassVar[str | None] = None
    SnakeIndexes: ClassVar[list[SnakeIndex]] = []
    # Domain rules the DB enforces. Declared with `snake_check(User.age >= 18)`: the condition is
    # the SAME one `.filter()` uses, so the checker validates it and renaming a column breaks the
    # rule at type-check time, not in production.
    SnakeChecks: ClassVar[list[SnakeCheckInfo]] = []

    @property
    def aggregate(self) -> _AggregateNamespace:
        """EMERGENCY EXIT to the annotated aggregates by dynamic name (`object`, demands a cast).

        Returns a per-instance namespace whose `__getattr__` gives `object` (NEVER `Any`): the checker
        forces a `cast()` on you and gives you no IntelliSense. The typed road is `@snake_result`. If
        the instance was not annotated, or the name does not exist, `SnakeAggregateNotLoaded` is raised.
        """
        values: Mapping[str, object] | None = getattr(self, _AGGREGATES_KEY, None)
        return _AggregateNamespace(values)


# The tuple is LITERAL: PEP 681 does not accept a constant here (see SNAKE_FIELD_SPECIFIERS in
# `fields/__init__.py`, the canonical reference, which a test ties this literal to).
@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        snake_column,
        snake_auto,
        snake_enum,
        snake_int,
        snake_str,
        snake_decimal,
        snake_datetime,
        snake_datetimetz,
        snake_float,
        snake_time,
        snake_timetz,
        snake_json,
        snake_to_one,
        snake_to_many,
        snake_to_many_through,
        snake_discriminator,
    ),
)
class SnakeView:
    """VIEW base: like `SnakeModel`, but it marks the model as READ-ONLY.

    A database view (`@snake_view`) is queried and NAVIGATED exactly like a model, but it is NOT
    written: `session.add/update/delete/...` do not accept it. The lock is one of TYPES — those
    methods ask for a `SnakeModel`, and a `SnakeView` does NOT inherit from `SnakeModel`, so it does
    not fit — backed by a reinforcing runtime guard in the session.

    It carries its own `@dataclass_transform` (independent of `SnakeModel`'s) because it is also
    INSTANTIATED: the user does not build it by hand, but the session does when HYDRATING each row of
    the view. That way its generated `__init__` ends up typed just like a model's.
    """

    SnakeComment: ClassVar[str | None] = None


def attach_aggregates(instance: object, values: Mapping[str, object]) -> None:
    """Stores on the instance the dict of aggregates the `aggregate` escape hatch exposes.

    `session.annotate(...)` calls it after hydrating the base row. It uses `object.__setattr__`
    because models keep their state per attribute (there are no `__slots__`), as descriptors do.
    """
    object.__setattr__(instance, _AGGREGATES_KEY, dict(values))
