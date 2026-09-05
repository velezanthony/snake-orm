"""SQL parameters of a column, grouped BY TYPE FAMILY.

Every Python type family has its own parameters: an `int` has width, a `str` has length, a
`Decimal` has precision and scale, a `dict` has backing. Loose and flat inside `SnakeColumnInfo`,
nothing stopped you from writing a column with `max_length` AND `precision` at once — a state no
engine can represent, living in the graph that is supposed to BE the truth.

Grouped, that combination cannot even be built. And the dialect now receives ONE parameter instead
of five: that is what finally lets `precision` enter `map_type` (it used to be concatenated onto
the type FROM OUTSIDE, with an f-string, which is why it was the only unvalidated one).

Adding a new family = a dataclass here and a branch in each dialect. Neither the compiler nor
`SnakeColumnInfo` gets touched: the guard is structural and reads `python_type`.
"""

from __future__ import annotations

from typing import get_origin

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.metadata.int_size import SnakeIntSize
from snakeorm.metadata.json_storage import SnakeJsonStorage


def base_type(python_type: object) -> object:
    """A parameterised generic reduced to its ORIGIN; anything else unchanged.

    `dict[str, object]` answers `dict`, `list[int]` answers `list`, and `bool` answers `bool` —
    `get_origin` of a plain class is `None`, which is what keeps the identity comparison below
    strict where it has to be.

    It exists because the guard compared `python_type is self.python_type`, so a user who
    parameterised their column —the only way to write a JSON column WITHOUT dragging in `Any`—
    got a refusal at import, with a message that asked them to change `dict` into `dict`. The
    project's rule number one is zero `Any`, and the ORM was forcing it.
    """
    return get_origin(python_type) or python_type


@dataclass(frozen=True, slots=True)
class SnakeIntParams:
    """Parameters of an `int` column: how much room it takes in the database."""

    size: SnakeIntSize = SnakeIntSize.BIGINT

    @property
    def python_type(self) -> type:
        """The Python type this family belongs to. The compiler's guard uses it."""
        return int

    def accepts(self, python_type: object) -> bool:
        """The family covers EXACTLY its type. By identity, not by inheritance: `bool` is a
        subclass of `int` and accepting it would size a boolean column as an integer.

        The ORIGIN is what gets compared, so `dict[str, object]` is a `dict` — which is the only
        way to declare a JSON column without a bare `dict` and the `Any` it drags in. It does not
        loosen the identity: `get_origin(bool)` is `None`, so `bool` still compares as itself."""
        return base_type(python_type) is self.python_type

    @property
    def declarator(self) -> str:
        """The name of the field specifier that declares them. It goes into the error messages, so
        the warning says WHAT to write and not just what is wrong."""
        return "snake_int"


@dataclass(frozen=True, slots=True)
class SnakeStrParams:
    """Parameters of a `str` column: its maximum length, if it declares one.

    The CEILING is set by each engine (Postgres and MySQL do not agree, and MySQL's even depends on
    the collation); here we only head off what means nothing on any of them.
    """

    max_length: int | None = None
    fixed: bool = False
    """FIXED length (`CHAR(n)`) instead of variable (`VARCHAR(n)`).

    It is not a stricter VARCHAR: `CHAR` pads with spaces up to `n` and compares ignoring that
    padding. Whoever stores country codes, ISINs or a hash of known length wants it for exactly that
    reason, and everybody else should not pay for it — which is why the default is still VARCHAR.
    """

    def __post_init__(self) -> None:
        """A VARCHAR has to fit at least one character, and a CHAR has to say how many.

        `VARCHAR(0)` is LEGAL on both engines and useless: it only accepts the empty string. That
        the engine swallows it does not make it a reasonable declaration — nobody wants a column
        like that — and this ORM shouts instead of letting through what is almost certainly a slip.
        """
        if self.max_length is not None and self.max_length < 1:
            raise SnakeModelDefinitionError(
                f"A VARCHAR has to fit at least one character, and max_length={self.max_length} "
                f"was asked for. For unbounded text, do not declare max_length at all: "
                f"snake_str() already emits TEXT."
            )
        if self.fixed and self.max_length is None:
            # A bare `CHAR` is `CHAR(1)` in SQL. Guessing it would mean taking a decision the user
            # never took on their behalf, and a one-character column where text was expected does
            # not show up until something gets truncated.
            raise SnakeModelDefinitionError(
                "A fixed-length column has to say HOW MANY characters: declare "
                "snake_str(max_length=n, fixed=True). A CHAR without a length is CHAR(1) in SQL, "
                "and that is almost never what anyone wants."
            )

    @property
    def python_type(self) -> type:
        """The Python type this family belongs to. The compiler's guard uses it."""
        return str

    def accepts(self, python_type: object) -> bool:
        """The family covers EXACTLY its type. By identity, not by inheritance: `bool` is a
        subclass of `int` and accepting it would size a boolean column as an integer.

        The ORIGIN is what gets compared, so `dict[str, object]` is a `dict` — which is the only
        way to declare a JSON column without a bare `dict` and the `Any` it drags in. It does not
        loosen the identity: `get_origin(bool)` is `None`, so `bool` still compares as itself."""
        return base_type(python_type) is self.python_type

    @property
    def declarator(self) -> str:
        """The name of the field specifier that declares them. It goes into the error messages, so
        the warning says WHAT to write and not just what is wrong."""
        return "snake_str"


@dataclass(frozen=True, slots=True)
class SnakeDecimalParams:
    """Parameters of a `Decimal` column: the NUMERIC's digits.

    `precision` is mandatory: a NUMERIC without it accepts any number of digits, so rounding stops
    being declared and starts depending on whatever comes in.

    Only what is absurd on ANY engine is rejected here. The ceiling —1000 digits in Postgres, 65 in
    MySQL— is engine knowledge and lives in its dialect, like `max_bind_params`.

    On scale: Postgres 15 accepts negative scales and scales greater than the precision, as its own
    extension. It is not exposed, on purpose. The standard demands `0 <= scale <= precision`, MySQL
    demands it, and Postgres demanded it up to 15; opening it would make a model stop being portable
    depending on the VERSION of the server behind it, which is exactly what the Dialect/Driver axis
    avoids.
    """

    precision: int
    scale: int | None = None

    def __post_init__(self) -> None:
        """Heads off the three impossible numbers at construction, the earliest point there is."""
        if self.precision < 1:
            raise SnakeModelDefinitionError(
                f"A NUMERIC has to have at least one digit, and "
                f"precision={self.precision} was asked for. Precision is the TOTAL number of "
                f"digits; the decimal places go in scale."
            )
        if self.scale is None:
            return
        if self.scale < 0:
            raise SnakeModelDefinitionError(
                f"The scale of a NUMERIC cannot be negative (scale={self.scale} was asked for). "
                f"It is the decimal places: 2 for money, 0 for exact integers."
            )
        if self.scale > self.precision:
            raise SnakeModelDefinitionError(
                f"The scale cannot exceed the precision: {self.scale} decimal places were asked "
                f"for inside {self.precision} total digits, leaving nothing for the integer "
                f"part. Raise precision or lower scale."
            )

    @property
    def python_type(self) -> type:
        """The Python type this family belongs to. The compiler's guard uses it."""
        return Decimal

    def accepts(self, python_type: object) -> bool:
        """The family covers EXACTLY its type. By identity, not by inheritance: `bool` is a
        subclass of `int` and accepting it would size a boolean column as an integer.

        The ORIGIN is what gets compared, so `dict[str, object]` is a `dict` — which is the only
        way to declare a JSON column without a bare `dict` and the `Any` it drags in. It does not
        loosen the identity: `get_origin(bool)` is `None`, so `bool` still compares as itself."""
        return base_type(python_type) is self.python_type

    @property
    def declarator(self) -> str:
        """The name of the field specifier that declares them. It goes into the error messages, so
        the warning says WHAT to write and not just what is wrong."""
        return "snake_decimal"


@dataclass(frozen=True, slots=True)
class SnakeJsonParams:
    """Parameters of a `dict` column: which DB object backs it."""

    storage: SnakeJsonStorage = SnakeJsonStorage.JSONB

    @property
    def python_type(self) -> type:
        """The Python type this family belongs to. The compiler's guard uses it."""
        return dict

    def accepts(self, python_type: object) -> bool:
        """The family covers EXACTLY its type. By identity, not by inheritance: `bool` is a
        subclass of `int` and accepting it would size a boolean column as an integer.

        The ORIGIN is what gets compared, so `dict[str, object]` is a `dict` — which is the only
        way to declare a JSON column without a bare `dict` and the `Any` it drags in. It does not
        loosen the identity: `get_origin(bool)` is `None`, so `bool` still compares as itself."""
        return base_type(python_type) is self.python_type

    @property
    def declarator(self) -> str:
        """The name of the field specifier that declares them. It goes into the error messages, so
        the warning says WHAT to write and not just what is wrong."""
        return "snake_json"


@dataclass(frozen=True, slots=True)
class SnakeDateTimeParams:
    """Parameters of a date column: whether the column carries a zone, and its resolution.

    `tz` is NOT a knob you pick by hand: the declarator sets it (`snake_datetimetz()` sets it to
    `True`, `snake_datetime()` to `False`) and a compiler guard demands it match the annotation.
    That way the MODEL says which column gets created —just as `snake_int(size=SMALLINT)` says
    SMALLINT— without the redundancy being able to lie. Same treatment as `snake_enum(Status)` over
    a `SnakeColumn[Status]`.

    `precision` is the fractional-second digits: `0` whole seconds, `3` milliseconds, `6` the
    Postgres default (exactly the resolution of Python's `datetime`).

    Only what means nothing on ANY engine is rejected here —a negative digit count—. The CEILING is
    set by each dialect: Postgres and MySQL stop at 6, SQL Server reaches 7 and Oracle 9, so pinning
    it here would put a specific engine inside the model, and the project's golden rule is that the
    metadata graph stays agnostic.
    """

    tz: bool = False
    precision: int | None = None

    def __post_init__(self) -> None:
        """Heads off a negative precision at construction, the earliest point there is."""
        if self.precision is not None and self.precision < 0:
            raise SnakeModelDefinitionError(
                f"The precision of a date cannot be negative ({self.precision} was asked for). "
                f"It is the fractional-second digits: 0 is whole seconds, 3 milliseconds and "
                f"6 microseconds, which is the resolution of Python's datetime."
            )

    @property
    def python_type(self) -> type:
        """The Python type this family belongs to. The compiler's guard uses it."""
        return datetime

    def accepts(self, python_type: object) -> bool:
        """The family covers `datetime` AND `SnakeUtc`, which is a subclass of it.

        The other families compare by identity; this one cannot, because `SnakeUtc` is the same data
        type with a guarantee on top.
        """
        return isinstance(python_type, type) and issubclass(python_type, datetime)

    @property
    def declarator(self) -> str:
        """The name of the field specifier that declares them. It goes into the error messages, so
        the warning says WHAT to write and not just what is wrong."""
        return "snake_datetime"


@dataclass(frozen=True, slots=True)
class SnakeFloatParams:
    """Parameters of a `float` column: its WIDTH in bytes.

    A Python `float` is double precision, so 8 is the default and it does not change: changing it
    would make an already-written model lose precision silently on upgrade. Declaring 4 is a storage
    decision —half the bytes per row— taken knowing what you lose.
    """

    size: int = 8

    def __post_init__(self) -> None:
        """Only 4 and 8: there is no engine with any other floating-point width.

        Like every other structural guard, what means nothing on ANY engine dies at declaration
        time. Per-engine ceilings are another matter and live in the dialect.
        """
        if self.size not in (4, 8):
            raise SnakeModelDefinitionError(
                f"A float is either 4 or 8 bytes, and size={self.size} was asked for. 4 is single "
                f"precision (REAL/FLOAT) and 8 is double (DOUBLE PRECISION/DOUBLE), which is what a "
                f"Python float is and the default of this ORM."
            )

    @property
    def python_type(self) -> type:
        """The Python type this family belongs to. The compiler's guard uses it."""
        return float

    def accepts(self, python_type: object) -> bool:
        """The family covers EXACTLY its type, by identity and not by inheritance."""
        return python_type is self.python_type

    @property
    def declarator(self) -> str:
        """The name of the field specifier that declares them, so the error says WHAT to write."""
        return "snake_float"


@dataclass(frozen=True, slots=True)
class SnakeTimeParams:
    """Parameters of a `time` column: whether it carries a ZONE.

    Two declarators, as with dates (`snake_datetime` / `snake_datetimetz`), and for the same reason:
    the column SAYS which type it creates instead of it depending on whether the first value that
    arrived carried an offset. A bare `TIME` throws the zone away, and an opening time stops meaning
    the same thing when seen from somewhere else.
    """

    with_timezone: bool = False

    @property
    def python_type(self) -> type:
        """The Python type this family belongs to. The compiler's guard uses it."""
        return time

    def accepts(self, python_type: object) -> bool:
        """The family covers EXACTLY its type, by identity and not by inheritance."""
        return python_type is self.python_type

    @property
    def declarator(self) -> str:
        """The name of the field specifier that declares them, so the error says WHAT to write."""
        return "snake_timetz" if self.with_timezone else "snake_time"


SnakeTypeParams = (
    SnakeIntParams
    | SnakeStrParams
    | SnakeDecimalParams
    | SnakeJsonParams
    | SnakeDateTimeParams
    | SnakeFloatParams
    | SnakeTimeParams
)
"""The parameters of ONE family. `None` on a column that has none (`bool`, `date`...)."""
