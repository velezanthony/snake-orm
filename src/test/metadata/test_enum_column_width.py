"""A `StrEnum` column knows its own WIDTH, and the metadata hands it over instead of throwing it away.

`SnakeColumnInfo` already derives ONE thing from `enum_type`: the base type, in `storage_type`, so
that the dialect never has to know what an enum is. The width is the SECOND thing derivable from the
very same place — a `StrEnum` has a longest member and its length is an exact number known at compile
time — and it used to be dropped on the floor: `type_params` stayed `None`, MySQL read "a `str` with
no declared length", wrote `TEXT`, and a composite index over that column blew up with
`1071, Specified key was too long`.

It is NOT a new knob. `snake_enum` grows no `max_length=`, because there is nothing for a user to
decide: the enum already said it. The rule of this ORM is that the type ALWAYS comes from Python, and
this is the ORM finally reading all of what Python said.
"""

from __future__ import annotations

from enum import Enum, IntEnum, StrEnum

from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeEnumStorage,
    SnakeStrParams,
)


class Flavour(StrEnum):
    """Three members of different lengths; `strawberry` (10) is the longest."""

    FIG = "fig"
    PEAR = "pear"
    STRAWBERRY = "strawberry"


class Priority(IntEnum):
    """An integer-backed enum: no width to derive from it."""

    LOW = 1
    HIGH = 2


class Single(StrEnum):
    """One single member: the boundary where `max` still has something to answer."""

    ONLY = "only"


class Empty(StrEnum):
    """No members at all: there is no longest value, so there is nothing to derive."""


def _column(enum_type: type[Enum]) -> SnakeColumnInfo:
    """An enum column as the compiler builds it: `enum_type` set and `type_params` left alone."""
    return SnakeColumnInfo(
        name="value",
        python_type=enum_type,
        enum_type=enum_type,
        enum_storage=SnakeEnumStorage.CHECK,
    )


def test_a_str_enum_derives_the_length_of_its_longest_member() -> None:
    """Verifies that `type_params` comes back as `SnakeStrParams` sized by the longest value."""
    column = _column(Flavour)

    assert column.type_params == SnakeStrParams(max_length=len("strawberry"))


def test_the_derived_length_is_readable_through_max_length() -> None:
    """Verifies that the usual reading face (`max_length`) sees the derived width too.

    The diff compares columns THROUGH this property, not through the raw params, so a derivation the
    property could not see would be invisible to `makemigrations`.
    """
    assert _column(Flavour).max_length == 10


def test_the_length_is_the_VALUE_and_not_the_member_name() -> None:
    """Verifies that what is measured is what gets STORED.

    `Flavour.STRAWBERRY` is 10 characters as a name and 10 as a value by coincidence; `Flavour.FIG`
    is 3 and 3. The measure has to follow the value, which is what `adapt_param` writes and what the
    `CHECK` enumerates — a column sized by the NAME would be wrong the moment the two differ.
    """

    class Shouty(StrEnum):
        """A name far longer than the value it stores."""

        AN_EXTREMELY_LONG_MEMBER_NAME = "x"

    assert _column(Shouty).type_params == SnakeStrParams(max_length=1)


def test_an_int_enum_derives_nothing() -> None:
    """Verifies that an `IntEnum` keeps `type_params` at `None`: an int has no length to derive."""
    assert _column(Priority).type_params is None


def test_an_enum_of_one_member_still_derives_its_width() -> None:
    """Verifies the lower boundary: one member is still a longest member."""
    assert _column(Single).type_params == SnakeStrParams(max_length=4)


def test_an_enum_with_no_members_derives_nothing() -> None:
    """Verifies that an empty enum derives nothing rather than an impossible `VARCHAR(0)`.

    `SnakeStrParams` rejects `max_length=0` on purpose, so guessing here would turn a strange model
    into a crash at import time. Falling back to no params leaves the column exactly as it was.
    """
    assert _column(Empty).type_params is None


def test_the_storage_does_not_change_the_derivation() -> None:
    """Verifies that `CHECK` and `PLAIN` derive the same width.

    `enum_storage` decides whether a DB object validates the members; it says nothing about how wide
    the column is, and the two must not get tangled.
    """
    checked = _column(Flavour)
    plain = SnakeColumnInfo(
        name="value",
        python_type=Flavour,
        enum_type=Flavour,
        enum_storage=SnakeEnumStorage.PLAIN,
    )

    assert checked.type_params == plain.type_params


def test_an_explicit_declaration_wins_over_the_derivation() -> None:
    """Verifies that params written out by hand are respected instead of being recomputed.

    This is what keeps a HISTORICAL migration honest: a generated file spells the width the enum had
    the day it was written, so replaying it rebuilds the column the database really has — and the
    diff can then see that today's longer member is a change. Re-deriving from the live enum class
    would make that change invisible.
    """
    column = SnakeColumnInfo(
        name="value",
        python_type=Flavour,
        enum_type=Flavour,
        enum_storage=SnakeEnumStorage.CHECK,
        type_params=SnakeStrParams(max_length=4),
    )

    assert column.type_params == SnakeStrParams(max_length=4)


def test_a_plain_str_column_is_untouched() -> None:
    """Verifies that a non-enum `str` keeps `type_params` at `None`: TEXT stays the faithful default."""
    assert SnakeColumnInfo(name="bio", python_type=str).type_params is None


def test_the_column_stays_frozen_and_slotted() -> None:
    """Verifies that deriving did not cost the metadata its immutability or its slots."""
    column = _column(Flavour)

    assert not hasattr(column, "__dict__")


def test_two_equal_enum_columns_stay_equal() -> None:
    """Verifies that the derivation is deterministic: equality by value survives it.

    The diff leans on `==` all the way down, so a derivation producing a different object each time
    would invent a change on every single `makemigrations`.
    """
    assert _column(Flavour) == _column(Flavour)
