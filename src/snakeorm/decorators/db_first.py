"""The `@snake_db_first` decorator: a model that MIRRORS something that already exists."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, dataclass_transform

from snakeorm.compiler import compile_model
from snakeorm.decorators.model import _install_dunders, _make_init
from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.fields import (
    snake_auto,
    snake_column,
    snake_datetime,
    snake_datetimetz,
    snake_decimal,
    snake_discriminator,
    snake_enum,
    snake_float,
    snake_int,
    snake_json,
    snake_str,
    snake_time,
    snake_timetz,
    snake_to_many,
    snake_to_many_through,
    snake_to_one,
)
from snakeorm.metadata import SnakeTableKind
from snakeorm.registry import SnakeRegistry
from snakeorm.registry import registry as default_registry

T = TypeVar("T")


# A LITERAL tuple as PEP 681 demands; tied to SNAKE_FIELD_SPECIFIERS by a test.
#
# It used to carry seven of these instead of the whole set, and nothing said so: the test that ties
# the sites together listed FOUR of them by hand and this was the fifth. The scaffolder emits
# `snake_decimal()`, `snake_int()` and `snake_str()`, so a mirrored model declared with those
# stopped typing its `__init__` in silence — the checker read the call as a plain default value.
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
def snake_db_first(
    *,
    table: str | None = None,
    schema: str = DEFAULT_SCHEMA,
    database: str = "default",
    registry: SnakeRegistry = default_registry,
) -> Callable[[type[T]], type[T]]:
    """Declare a model that MIRRORS a table that ALREADY exists and that we do NOT govern (the
    Django `managed=False`).

    You query and write it like any other model, but migrations IGNORE it (`current_schema()`
    excludes anything unmanaged): the source of truth of the schema is the DB, not the model.

    There is NO in-place adoption: swapping `@snake_db_first` for `@snake_model` does NOT hand the
    controls to the migrations; the history does not know the table and the autogen would only
    emit a `CreateTable`, which against the existing table dies with `DuplicateTable`. It IS good
    for TAKING the schema to ANOTHER database managed from scratch (there the `CreateTable` is
    correct); the original DB is left untouched.
    """

    def wrap(klass: type[T]) -> type[T]:
        registry.register(
            klass,
            compile_model(
                klass,
                table=table,
                schema=schema,
                database=database,
                kind=SnakeTableKind.EXTERNAL,
            ),
        )
        # The mirror remembers WHICH registry it lives in, exactly as `@snake_model` does. Without
        # it `@snake_db_first(registry=reg)` registered the model in `reg` and then every consumer
        # that asks the MODEL —typed navigation, the query, the session— was answered by the global
        # one, so the class was registered and unreachable. It went unnoticed because nothing asked
        # until the query and the session stopped reaching for the global registry themselves.
        setattr(klass, "__snake_registry__", registry)
        setattr(klass, "__init__", _make_init(klass))
        _install_dunders(klass, registry)
        return klass

    return wrap
