"""The @snake_model decorator: it turns a class into a compiled model."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, dataclass_transform, overload

from snakeorm.compiler import compile_model
from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.core.exceptions import SnakeModelError
from snakeorm.core.sentinels import NOT_LOADED
from snakeorm.fields import (
    SnakeColumn,
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
from snakeorm.helpers.inheritance import collect_inherited
from snakeorm.metadata import SnakeTableInfo
from snakeorm.decorators.polymorphic import guard_child_columns, resolve_polymorphic
from snakeorm.registry import SnakeRegistry
from snakeorm.registry import registry as default_registry

T = TypeVar("T")


def _make_init(cls: type, discriminator: tuple[str, str] | None = None) -> Any:
    """Generate a keyword-only __init__ that assigns each column through its descriptor.

    It is built by hand because @dataclass would take the descriptors as defaults. `discriminator`
    is the `(column, value)` pair of a polymorphic subclass: the column is excluded from the
    constructor (the CLASS decides its value, like an autoincrement) and gets filled in here. The
    value travels in the closure, not in global state, because the source of truth is already
    `table.polymorphic.value`.
    """
    # It walks the MRO (base→child): the child's __init__ also demands/fills the columns inherited
    # from an abstract base, not only its own.
    columns = list(collect_inherited(cls, SnakeColumn).items())
    discriminator_column = discriminator[0] if discriminator is not None else None
    discriminator_value = discriminator[1] if discriminator is not None else None

    def __init__(self: Any, **kwargs: Any) -> None:
        for attr, descriptor in columns:
            if descriptor.column_name == discriminator_column:
                setattr(self, attr, discriminator_value)
                continue
            if descriptor.autoincrement or descriptor.has_server_default:
                continue  # excluded from the constructor (the DB supplies it); not an argument
            if attr in kwargs:
                setattr(self, attr, kwargs.pop(attr))
            elif descriptor.has_default:
                setattr(self, attr, descriptor.default)
            elif descriptor.default_factory is not None:
                setattr(
                    self, attr, descriptor.default_factory()
                )  # a fresh value per instance
            else:
                raise TypeError(f"{cls.__name__}() missing required argument: '{attr}'")
        if kwargs:
            raise TypeError(f"{cls.__name__}() unexpected arguments: {sorted(kwargs)}")

    return __init__


_UNSET = "<unassigned>"
_NOT_LOADED_LABEL = "<not loaded>"
"""What a column the query deliberately left out prints as. A repr must never raise."""
_MISSING = object()
"""Sentinel for "the storage key is not there at all", which is not the same as "left out"."""


def _install_dunders(cls: type, reg: SnakeRegistry) -> None:
    """Install `__repr__`, `__eq__` and `__hash__` by reading the PK off the already compiled GRAPH.

    Equality goes by PRIMARY KEY, not by value: two objects of the same row are the same row even
    if one of them is stale. The columns come from `SnakePrimaryKeyInfo.columns` (not from a magic
    `pk`), so a composite PK works with the SAME code.
    """
    table = reg.table_of(cls)
    if table is None:  # pragma: no cover - defensive: the decorator just registered it
        return
    column_attrs = tuple(column.attr_name or column.name for column in table.columns)
    pk_attrs = tuple(
        column.attr_name or column.name for column in table.primary_key.columns
    )

    def _pk_values(instance: object) -> tuple[object, ...] | None:
        """The PK values, or None if there is no row identity to read.

        It returns None in two cases: a table WITHOUT a PK (a `@snake_db_first` mirror, which falls
        back to identity) and a table WITH a PK not yet set (an object that has not been inserted).
        The first case is the critical one: without it, an empty `pk_attrs` would return `()` and
        any two rows would compare equal → data loss inside a `set`.
        """
        if not pk_attrs:
            return None
        values: list[object] = []
        for attr in pk_attrs:
            if not hasattr(instance, f"__snake_{attr}"):
                return None
            values.append(getattr(instance, attr))
        return tuple(values)

    def _printable(instance: object, attr: str) -> str:
        """One field of the repr. THREE states, the same three the descriptor tells apart.

        Reading an unloaded column RAISES, which is the feature, and `__repr__` used to inherit that
        raise: printing a narrowed row killed the inspection it was part of. So the sentinel is read
        off the storage key here rather than through the descriptor.
        """
        stored = getattr(instance, f"__snake_{attr}", _MISSING)
        if stored is _MISSING:
            # A half-built object is STILL printable (useful right before the INSERT).
            return f"{attr}={_UNSET}"
        if stored is NOT_LOADED:
            return f"{attr}={_NOT_LOADED_LABEL}"
        return f"{attr}={getattr(instance, attr)!r}"

    def __repr__(self: object) -> str:
        fields = ", ".join(_printable(self, attr) for attr in column_attrs)
        return f"{type(self).__name__}({fields})"

    def __eq__(self: object, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        mine, theirs = _pk_values(self), _pk_values(other)
        if mine is None or theirs is None:
            # Without a PK there is no row identity to compare: it falls back to object identity.
            return self is other
        return mine == theirs

    def __hash__(self: object) -> int:
        # A table WITHOUT a PK (a legacy mirror): hashable by IDENTITY; nothing the INSERT fills in
        # later, so the hash cannot mutate.
        if not pk_attrs:
            return object.__hash__(self)
        values = _pk_values(self)
        if values is None:
            raise TypeError(
                f"{type(self).__name__} is not hashable until it has a primary key: its hash "
                f"would come from the PK, and the INSERT would fill it in afterwards MUTATING the "
                f"hash inside whatever set or dict it was sitting in. Insert it first."
            )
        return hash((type(self).__name__, values))

    for name, value in (
        ("__repr__", __repr__),
        ("__eq__", __eq__),
        ("__hash__", __hash__),
    ):
        setattr(cls, name, value)


@overload
def snake_model(cls: type[T]) -> type[T]: ...
@overload
def snake_model(
    *,
    table: str | None = ...,
    prefix: str | None = ...,
    schema: str = ...,
    database: str = ...,
    discriminator_value: str | None = ...,
    registry: SnakeRegistry = ...,
) -> Callable[[type[T]], type[T]]: ...


# A LITERAL tuple as PEP 681 demands; tied to SNAKE_FIELD_SPECIFIERS by a test.
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
def snake_model(
    cls: type[T] | None = None,
    *,
    table: str | None = None,
    prefix: str | None = None,
    schema: str = DEFAULT_SCHEMA,
    database: str = "default",
    discriminator_value: str | None = None,
    registry: SnakeRegistry = default_registry,
) -> Any:
    """Compile the model, store its SnakeTableInfo and install the __init__ at runtime.

    It is used bare (`@snake_model`) or parametric. The table name is `{prefix}_{table}`: `table=`
    changes only the table (keeping the prefix), `prefix=` changes the namespace.

    A `snake_discriminator()` column opens a POLYMORPHIC hierarchy: the whole family shares this
    table and that column says what each row is. The children inherit it in Python and declare
    their `discriminator_value=`; they do not pick a table, because there is none to pick.

    ```python
    @snake_model(table="animals")
    class Animal(SnakeModel):
        id: SnakeColumn[int] = snake_auto()
        kind: SnakeColumn[str] = snake_discriminator()

    @snake_model(discriminator_value="dog")
    class Dog(Animal):
        breed: SnakeColumn[str | None] = snake_str()
    ```

    There is no `inherits=Animal`: Python inheritance ALREADY says who the base is (it avoids a
    second source).
    """

    def wrap(klass: type[T]) -> type[T]:
        placement = resolve_polymorphic(klass, discriminator_value, registry)
        compiled = compile_model(
            klass,
            # A polymorphic child does NOT pick a table: it shares its base's, and name, schema
            # and connection all come from there.
            table=placement.table if placement.table is not None else table,
            prefix=None if placement.table is not None else prefix,
            schema=placement.schema if placement.schema is not None else schema,
            database=placement.database if placement.database is not None else database,
            polymorphic=placement.info,
        )
        # The guard operates on the ALREADY compiled table (without recompiling).
        guard_child_columns(klass, compiled, placement)
        registry.register(klass, compiled)
        # The model remembers WHICH registry it lives in: typed navigation resolves relations
        # against THAT registry, not the global one. Without this, `@snake_model(registry=reg)`
        # broke `User.car.brand`.
        setattr(klass, "__snake_registry__", registry)
        setattr(klass, "__init__", _make_init(klass, placement.constructor_fills()))
        _install_dunders(klass, registry)
        return klass

    return wrap if cls is None else wrap(cls)


def snake_table(cls: type, reg: SnakeRegistry = default_registry) -> SnakeTableInfo:
    """Return the compiled SnakeTableInfo of a @snake_model model."""
    table = reg.table_of(cls)
    if table is None:
        raise SnakeModelError(f"{cls.__name__} is not a @snake_model.")
    return table
