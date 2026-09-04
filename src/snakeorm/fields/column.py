"""The SnakeColumn descriptor and its field specifier snake_column."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any, Generic, Literal, TypeVar, overload

from snakeorm.core.exceptions import (
    SnakeColumnNotLoaded,
    SnakeModelDefinitionError,
)
from snakeorm.core.sentinels import NOT_LOADED
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeEnumStorage,
    SnakeIntParams,
    SnakeIntSize,
    SnakeServerDefault,
    SnakeTypeParams,
)

T = TypeVar("T")


class _MissingType:
    """Sentinel for 'no default value' (different from default=None)."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _MissingType()


class SnakeColumn(Generic[T]):
    """Column descriptor.

    CLASS access (`User.username`) → `SnakeExpr[T]` (an expression for queries).
    INSTANCE access (`user.username`) → the stored value (`T`).
    It also holds the SQL metadata the compiler will read to build the graph.
    """

    def __init__(
        self,
        *,
        primary_key: bool = False,
        unique: bool = False,
        default: object = MISSING,
        default_factory: Callable[[], T] | None = None,
        index: bool = False,
        name: str | None = None,
        db_comment: str | None = None,
        type_params: SnakeTypeParams | None = None,
        declared_by: str | None = None,
        autoincrement: bool = False,
        is_discriminator: bool = False,
        server_default: SnakeServerDefault | None = None,
        server_default_sql: str | None = None,
    ) -> None:
        # `default` is a DDL literal; `default_factory` a Python callable. Mutually exclusive.
        if default is not MISSING and default_factory is not None:
            raise SnakeModelDefinitionError(
                "Do not declare `default` and `default_factory` at the same time: `default` is the "
                "DDL literal and `default_factory` is a Python callable. Pick one."
            )
        if default is not MISSING and callable(default):
            raise SnakeModelDefinitionError(
                "`default` must be a literal (it goes to the DDL as DEFAULT); got a callable. "
                "For a value computed in Python (e.g. datetime.now) use `default_factory=`."
            )
        # `server_default` (an engine-agnostic enum) and `server_default_sql` (raw SQL): two
        # shapes of the same concept (the DB supplies the value). Declaring both contradicts
        # itself.
        if server_default is not None and server_default_sql is not None:
            raise SnakeModelDefinitionError(
                "Do not declare `server_default` and `server_default_sql` at the same time: the enum is "
                "the portable route and raw SQL its escape hatch. Pick one."
            )
        # `server_default` and `default` feed the same DDL `DEFAULT`: they cannot coexist.
        if default is not MISSING and (
            server_default is not None or server_default_sql is not None
        ):
            raise SnakeModelDefinitionError(
                "Do not declare `default` and `server_default`/`server_default_sql` at the same time: "
                "both feed the DDL's DEFAULT. `default` is the client's literal; "
                "`server_default` is the value the server supplies. Pick one."
            )
        self.primary_key = primary_key
        self.unique = unique
        self.default = default
        self.default_factory = default_factory
        self.index = index
        self.db_comment = db_comment
        # SQL parameters of the type FAMILY, or None if the type has none. The specifier of its
        # family sets them (snake_int/snake_str/snake_decimal/snake_json); the compiler checks
        # that the family matches the annotation.
        self.type_params = type_params
        self.declared_by = declared_by
        """The specifier the USER wrote, for the guards' messages.

        It sits on the descriptor and NOT on `type_params`, which travels into the metadata
        graph and is compared by equality — a field there would read as a phantom diff in
        every migration. `None` means the family's own declarator is the right answer."""
        self.autoincrement = (
            autoincrement  # the DB generates the value; optional in __init__
        )
        self.server_default = (
            server_default  # the DB supplies the value; excluded from __init__/INSERT
        )
        self.server_default_sql = (
            server_default_sql  # escape hatch: raw SQL, NOT portable
        )
        self._name_override = name
        self._attr_name = ""
        self._storage_key = ""
        # `snake_enum` fills these in (None on a normal column). They live on the descriptor, not
        # on a subtype, so that the compiler has ONE single walk over columns.
        self.enum_type: type[Enum] | None = None
        self.enum_storage: SnakeEnumStorage | None = None
        # `snake_discriminator()` marks it: the column says which class each row is. Here, and not
        # as a parameter of the decorator, so the hierarchy is declared in ONE place (the model).
        self.is_discriminator = is_discriminator
        # Filled in by the COMPILER, which is the only place that reads the annotation. Class access
        # hands it to the expression so the SQL layer can reason about the type: the generic `T` is
        # erased at runtime, and without it an integer division cannot be told from a decimal one.
        # `None` until compiled, and every reader treats `None` as "no proof" and changes nothing.
        self.python_type: type | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        """Capture the property name and compute the per-instance storage key."""
        self._attr_name = name
        self._storage_key = f"__snake_{name}"

    @property
    def column_name(self) -> str:
        """SQL name of the column: the override if one was given, otherwise the property's."""
        return self._name_override or self._attr_name

    @property
    def attr_name(self) -> str:
        """Python attribute name (for the SQL→Python trip back when mapping rows)."""
        return self._attr_name

    @property
    def has_default(self) -> bool:
        """Whether the column has a default LITERAL (the one that goes to the DDL as DEFAULT)."""
        return self.default is not MISSING

    @property
    def has_default_factory(self) -> bool:
        """Whether the column has a factory (a callable) that fills the value in Python."""
        return self.default_factory is not None

    @property
    def has_server_default(self) -> bool:
        """Whether the DB supplies the value: the column is excluded from `__init__` and INSERT."""
        return self.server_default is not None or self.server_default_sql is not None

    @overload
    def __get__(self, instance: None, owner: Any) -> SnakeExpr[T]: ...
    @overload
    def __get__(self, instance: object, owner: Any) -> T: ...
    def __get__(self, instance: object | None, owner: Any) -> Any:
        if instance is None:
            return SnakeExpr(path=(self.column_name,), python_type=self.python_type)
        value = getattr(instance, self._storage_key, self.default)
        # THREE states, not two, and collapsing any pair of them is a bug of its own. A VALUE is
        # returned; a column the query deliberately left out (`only()`/`defer()`) carries the
        # sentinel and RAISES; an attribute simply never set on an instance nobody hydrated falls
        # through to the default, which is what makes a hand-built model work.
        #
        # Without the middle one, a deferred column reads as its default: `None` for a name, `0` for
        # a count. A wrong answer with no error is the one outcome this ORM does not produce.
        if value is NOT_LOADED:
            raise SnakeColumnNotLoaded(
                f"Column '{self.column_name}' was not loaded: the query that built this row named "
                f"only some columns (only()/defer()). Ask for it in the query, or use select() if "
                f"what you want is the values rather than the model."
            )
        return value

    def __set__(self, instance: object, value: T) -> None:
        object.__setattr__(instance, self._storage_key, value)


@overload
def snake_column(
    *,
    server_default: SnakeServerDefault,
    server_default_sql: str | None = ...,
    default: object = ...,
    default_factory: Callable[[], Any] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_column(
    *,
    server_default_sql: str,
    server_default: SnakeServerDefault | None = ...,
    default: object = ...,
    default_factory: Callable[[], Any] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_column(
    *,
    primary_key: bool = ...,
    unique: bool = ...,
    default: object = ...,
    default_factory: Callable[[], Any] | None = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_column(
    *,
    primary_key: bool = False,
    unique: bool = False,
    default: object = MISSING,
    default_factory: Callable[[], Any] | None = None,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare a column WITHOUT type parameters: `bool`, `date`, `UUID`, `bytes`, `timedelta`...

    The type comes from the annotation; this only adds type-agnostic SQL metadata.

    There are NO type-specific knobs. `int_size`, `max_length`, `json_storage` and
    `precision`/`scale` each live in the specifier of THEIR family (`snake_int`, `snake_str`,
    `snake_json`, `snake_decimal`): offering them here made them autocomplete on EVERY column, and
    a `max_length` on an integer is an illegal state that could be written. The type rules.

    There is NO `nullable`: nullability is stated by the annotation alone
    (`SnakeColumn[str | None]`); two sources would allow a type that lies.

    `name` renames the SQL column. `default` is a DDL literal; `default_factory` a Python callable
    that never touches the DDL. `server_default`/`server_default_sql` (a portable enum or raw SQL)
    declare a SERVER value: the column is excluded from `__init__` and INSERT (RETURNING brings it
    back). All the default sources are mutually exclusive.

    `init` is not passed by hand: it is the `Literal[False]` signal that excludes from the
    constructor the columns with `server_default` (through the overloads), just like `snake_auto`.
    """
    del init  # typing signal only; the runtime excludes via `server_default`
    return SnakeColumn(
        primary_key=primary_key,
        unique=unique,
        default=default,
        default_factory=default_factory,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


def snake_auto(
    *,
    name: str | None = None,
    db_comment: str | None = None,
    int_size: SnakeIntSize = SnakeIntSize.BIGINT,
    init: Literal[False] = False,
) -> Any:
    """Declare an autoincrementing PK: the DB generates the value.

    It is excluded from the constructor (the `init: Literal[False]` is the typing signal): the id
    shows up after the INSERT (RETURNING). For an explicit id, assign it as an attribute.

    `int_size` fixes the width of the PK (default `BIGINT` → `BIGSERIAL`); lower it to `INTEGER` on
    small catalogues.
    """
    return SnakeColumn(
        primary_key=True,
        autoincrement=True,
        name=name,
        db_comment=db_comment,
        type_params=SnakeIntParams(size=int_size),
        declared_by="snake_auto",
    )


def snake_discriminator(
    *,
    name: str | None = None,
    index: bool = True,
    db_comment: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare the column that says WHICH CLASS each row is in a polymorphic hierarchy.

    Here, and not as a parameter of the decorator: the `init: Literal[False]` excludes it from
    `__init__` (the runtime fills it in by itself). Its value comes from the CLASS: each subclass
    its own in `@snake_model(discriminator_value=...)`, the base its name in lowercase.

    `index=True` by default because every query on a subclass carries
    `WHERE <discriminator> = ...`: without an index the whole hierarchy gets scanned on each read.
    """
    return SnakeColumn(
        name=name, index=index, db_comment=db_comment, is_discriminator=True
    )
