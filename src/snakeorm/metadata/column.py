"""Immutable metadata of columns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.metadata.enum_storage import SnakeEnumStorage
from snakeorm.metadata.int_size import SnakeIntSize
from snakeorm.metadata.json_storage import SnakeJsonStorage
from snakeorm.metadata.server_default import SnakeServerDefault
from snakeorm.metadata.type_params import (
    SnakeDateTimeParams,
    SnakeDecimalParams,
    SnakeIntParams,
    SnakeJsonParams,
    SnakeStrParams,
    SnakeTypeParams,
)


def _width_of(enum_type: type[Enum]) -> SnakeStrParams | None:
    """The WIDTH a text-backed enum needs, or `None` when there is none to derive.

    An enum knows exactly how wide its column has to be: it has a longest member, and the length of
    that member's VALUE is an exact number available at compile time. The value and not the name,
    because the value is what `adapt_param` writes and what the `CHECK` enumerates.

    Three cases give nothing back, each for its own reason:

    - an `IntEnum`, because an integer has no length (it has a `SnakeIntSize`, which is not this);
    - an enum with no members, because there is no longest one — and `SnakeStrParams` rejects
      `max_length=0` on purpose, so guessing would turn a strange model into a crash at import;
    - anything that is not a text-backed enum at all, because the shout for that already lives in
      `storage_type`, and saying it twice from a `__post_init__` would move the failure to a place
      nobody is looking at.

    `int` is checked before `str` for the same reason `storage_type` checks it first: the two orders
    have to agree, or a column could be stored as an integer and sized as text.
    """
    if not (isinstance(enum_type, type) and issubclass(enum_type, Enum)):
        return None
    if issubclass(enum_type, int) or not issubclass(enum_type, str):
        return None
    widths = [len(str(member.value)) for member in enum_type]
    if not widths:
        return None
    return SnakeStrParams(max_length=max(widths))


@dataclass(frozen=True, slots=True)
class SnakeColumnInfo:
    """Metadata of a column.

    The type ALWAYS comes from Python (`python_type`); everything else only adds SQL info.
    Immutable (frozen) and with `slots`: it is part of the compiled graph, which never changes.
    """

    name: str
    python_type: type
    nullable: bool = False
    unique: bool = False
    default: object | None = None
    index: bool = False
    db_comment: str | None = None  # COMMENT ON COLUMN
    attr_name: str = ""  # name of the Python attribute; enables the SQL→Python mapping
    has_default: bool = (
        False  # tells "no default" apart from "default = None" (for the DDL)
    )
    autoincrement: bool = False  # the DB generates the value; the dialect picks how (SERIAL, AUTOINCREMENT...)
    # Callable that fills the value in Python when building the object; NEVER touches the DDL. Mutually exclusive with `default`.
    default_factory: Callable[[], object] | None = None
    # SERVER default, engine-agnostic (the dialect translates it): the column is OMITTED from the
    # INSERT and the RETURNING brings it back. Mutually exclusive with `default`.
    server_default: SnakeServerDefault | None = None
    # Escape hatch: raw SQL for the server default. NOT PORTABLE. Mutually exclusive with `server_default`.
    server_default_sql: str | None = None

    # SQL parameters of the type's FAMILY (an int's width, a str's length, a Decimal's precision, a
    # dict's backing), or None if the type has none (`bool`, `date`, `UUID`...).
    # They travel grouped and not loose because loose they allowed writing `max_length` AND
    # `precision` on the same column: a state no engine represents, living in the graph that IS the
    # truth.
    type_params: SnakeTypeParams | None = None
    # Enum: the enum's type and how it is backed. Primitives only; the conversions are not stored,
    # they are derived from `enum_type`.
    enum_type: type[Enum] | None = None
    enum_storage: SnakeEnumStorage | None = None

    def __post_init__(self) -> None:
        """Fills in the width of a text-backed enum, which the column already knew and threw away.

        `storage_type` derives ONE thing from `enum_type` —the base type, so the dialect never has
        to know what an enum is— and this is the SECOND, derived in the same place and for the same
        reason. Without it `type_params` stayed `None`, MySQL read "a `str` with no declared length",
        wrote `TEXT`, and a composite index over the column died with `1071, Specified key was too
        long`. The information was there the whole time.

        It is NOT a new knob: `snake_enum` grows no `max_length=`, because there is nothing left for
        anybody to decide. The type ALWAYS comes from Python, and this is the metadata reading all
        of what Python said instead of half.

        Params written out by hand WIN, and that is what keeps a historical migration honest: a
        generated file spells the width the enum had the day it was written, so replaying it rebuilds
        the column the database really has and the diff can see that today's longer member is a
        change. Re-deriving from the live class would make that change invisible.
        """
        if self.type_params is not None or self.enum_type is None:
            return
        derived = _width_of(self.enum_type)
        if derived is None:
            return
        # `object.__setattr__` is how a frozen dataclass normalises itself: the guarantee is that
        # nobody changes the column AFTERWARDS, and this runs before anyone has it.
        object.__setattr__(self, "type_params", derived)

    # The five properties below READ the family's parameters under their usual names.
    # Writing remains impossible other than through `type_params`: reading is comfortable, writing
    # is narrow. They return the family's default when the column is not of that family, which is
    # exactly what a column with the knob unset used to read before.

    @property
    def int_size(self) -> SnakeIntSize:
        """A DB-side `int` width. Default `BIGINT`: the widest of both engines, so Python's
        unbounded `int` lines up in Postgres and SQLite."""
        return (
            self.type_params.size
            if isinstance(self.type_params, SnakeIntParams)
            else SnakeIntSize.BIGINT
        )

    @property
    def max_length(self) -> int | None:
        """Maximum length of a `str`. Without it TEXT; with it Postgres emits VARCHAR(n)."""
        return (
            self.type_params.max_length
            if isinstance(self.type_params, SnakeStrParams)
            else None
        )

    @property
    def json_storage(self) -> SnakeJsonStorage:
        """Backing of a `dict`. Default `JSONB` (indexable, normalised); `JSON` preserves the
        exact text. SQLite collapses both to TEXT."""
        return (
            self.type_params.storage
            if isinstance(self.type_params, SnakeJsonParams)
            else SnakeJsonStorage.JSONB
        )

    @property
    def precision(self) -> int | None:
        """Digits of a NUMERIC. Without it Postgres accepts any number (rounding on money)."""
        return (
            self.type_params.precision
            if isinstance(self.type_params, SnakeDecimalParams)
            else None
        )

    @property
    def with_timezone(self) -> bool:
        """Whether the date column carries a zone (`TIMESTAMPTZ`) or is wall-clock (`TIMESTAMP`).

        The declarator sets it (`snake_datetimetz()` / `snake_datetime()`) and the compiler demands
        it match the annotation, so reading it from here is reading what both of them say.
        """
        return isinstance(self.type_params, SnakeDateTimeParams) and self.type_params.tz

    @property
    def scale(self) -> int | None:
        """Decimal places of a NUMERIC."""
        return (
            self.type_params.scale
            if isinstance(self.type_params, SnakeDecimalParams)
            else None
        )

    @property
    def storage_type(self) -> type:
        """The Python type the DIALECT maps to SQL.

        Normal column: its own type. Enum: its BASE type (`str`/`int`), so the dialect never needs
        to know anything about enums.
        """
        if self.enum_type is None:
            return self.python_type
        if issubclass(self.enum_type, int):
            return int
        if issubclass(self.enum_type, str):
            return str
        raise SnakeModelDefinitionError(
            f"Enum {self.enum_type.__name__} is neither a StrEnum nor an IntEnum, which leaves "
            f"it without a base type to store it with."
        )

    @property
    def has_server_default(self) -> bool:
        """Tells whether the DB sets the value: the column is excluded from `__init__` and INSERT."""
        return self.server_default is not None or self.server_default_sql is not None
