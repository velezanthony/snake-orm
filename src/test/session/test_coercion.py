"""Coercion tests: driver values → the declared python_type.

Drivers do not always return the exact type (psycopg2 hands UUIDs over as str). Coercion is
IDEMPOTENT (it leaves alone a value that already has the right type) and driver-agnostic.
"""

from __future__ import annotations

import pytest

from datetime import date, time, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeUtc,
    snake_column,
    snake_datetimetz,
    snake_enum,
    snake_int,
    snake_model,
    snake_table,
)
from snakeorm.core.exceptions import SnakeValueError
from snakeorm.session.coercion import coerce, converter_for
from snakeorm.session.mapper import hydrate

_UUID_STR = "11111111-1111-1111-1111-111111111111"


class _Color(StrEnum):
    """Enum used for the test."""

    ROJO = "rojo"
    AZUL = "azul"


@snake_model(table="coe_nullables")
class _Nullables(SnakeModel):
    """One nullable column per type with a converter, to hydrate an all-NULL row."""

    id: SnakeColumn[int | None] = snake_int(primary_key=True)
    b: SnakeColumn[bool | None] = snake_column()
    u: SnakeColumn[UUID | None] = snake_column()
    f: SnakeColumn[float | None] = snake_column()
    d: SnakeColumn[Decimal | None] = snake_column()
    y: SnakeColumn[bytes | None] = snake_column()
    dt: SnakeColumn[SnakeUtc | None] = snake_datetimetz()
    da: SnakeColumn[date | None] = snake_column()
    t: SnakeColumn[time | None] = snake_column()
    td: SnakeColumn[timedelta | None] = snake_column()
    j: SnakeColumn[dict | None] = snake_column()
    c: SnakeColumn[_Color | None] = snake_enum(_Color)


def test_coerce_str_to_uuid() -> None:
    """Verifies that a str is converted to the declared UUID (the psycopg2 case)."""
    result = coerce(_UUID_STR, UUID)
    assert isinstance(result, UUID)
    assert str(result) == _UUID_STR


def test_coerce_uuid_is_idempotent() -> None:
    """Verifies that a value that is already a UUID is returned untouched (the asyncpg case)."""
    value = UUID(_UUID_STR)
    assert coerce(value, UUID) is value


def test_coerce_none_stays_none() -> None:
    """Verifies that NULL (None) is kept as it is, with no attempt to convert it."""
    assert coerce(None, UUID) is None


def test_coerce_passthrough_for_types_without_converter() -> None:
    """Verifies that types with no registered converter pass through unchanged."""
    assert coerce(5, int) == 5
    assert coerce("Ana", str) == "Ana"
    assert coerce(True, bool) is True


def test_hydration_keeps_null_for_every_type_with_a_converter() -> None:
    """Hydrating a NULL leaves it as None for ANY type with a converter. Corruption avoided.

    What is tested is the BEHAVIOUR —hydrating—, not the shape of the converter. The first version
    of this test demanded `converter_for(T)(None) is None`, that is, that the raw converter be
    None-safe. And that was achieved by wrapping it in a closure... which cost +132 ns per column on
    the hottest path of the ORM, in the very file that exists so as not to pay indirection per row.
    Measuring the shape of the converter invited that expensive solution; measuring hydration leaves
    the HOW free, and the right how is an `or value is None` inline in the loop, for free.

    The bug it covers: `_to_bool(None)` gave `False` and `_to_uuid(None)` blew up. A `bool | None`
    column holding NULL read back as `False`, and on the first write `false` got persisted, killing
    the three-valued logic of the database without an error. A silent failure, on the hot path.
    """
    columns = [c.attr_name or c.name for c in snake_table(_Nullables).columns]
    row = tuple(None for _ in columns)  # the whole row is NULL, id included

    hidratada = hydrate(_Nullables, snake_table(_Nullables), row)

    no_none = {
        c: getattr(hidratada, c) for c in columns if getattr(hidratada, c) is not None
    }
    assert no_none == {}, (
        f"these types did not preserve the NULL on hydration: {no_none}"
    )


def test_coerce_speaks_the_same_vocabulary_as_converter_for() -> None:
    """`coerce()` converts EVERYTHING `converter_for()` converts. One vocabulary, not two.

    They are the two doors into the same wardrobe: `converter_for` serves the read path
    (`all()`, `hydrate`) and `coerce` serves the write-back path (the RETURNING of `add()`/
    `refresh()`, `session.py:1032`) and the annotate/prefetch path (`planning.py:132,164,212`).
    A value that entered through one door and left through the other came back as a different
    TYPE, which is the one thing this ORM promises never happens.

    `coerce` used to reimplement a SUBSET: it handled enums and the internal registry and skipped
    the two branches that matter — `from_db_for` (the user's `register_converter`) and the
    `list[...]` generic alias. Measured before the fix: `converter_for(list[str])('["a","b"]')`
    gave `['a', 'b']` and `coerce('["a","b"]', list[str])` gave the raw string.

    So the assertion is the AGREEMENT and not a table of types: a table would have to be
    remembered, and the next type added to one door would go missing from the other exactly the
    way `list` did.
    """
    from snakeorm.session.coercion import converter_for

    class _Level(StrEnum):
        PRO = "pro"

    samples: list[tuple[object, object]] = [
        ('["a","b"]', list[str]),
        ("[1,2]", list[int]),
        (_UUID_STR, UUID),
        ("1", int),
        ("pro", _Level),
        ("plain", str),
    ]

    divergentes: dict[object, tuple[object, object]] = {}
    for value, declared in samples:
        converter = converter_for(declared)
        through_read = converter(value) if converter is not None else value
        through_write = coerce(value, declared)
        if through_write != through_read:
            divergentes[declared] = (through_write, through_read)

    assert divergentes == {}, (
        f"coerce() and converter_for() disagree on these declared types: {divergentes}. "
        f"They are the same wardrobe seen from two doors; a value must not change type "
        f"depending on which one it came out of."
    )


# -- MySQL hands a `time` back as a `timedelta` -----------------------------------------------------


def test_a_mysql_duration_becomes_the_declared_time() -> None:
    """MySQL's `TIME` is a DURATION, so PyMySQL hands over a `timedelta`. It must arrive as declared.

    Found by adding MySQL to `test_type_round_trip.py`, which had only ever run Postgres and SQLite:
    a column declared `time` was coming back as `timedelta(seconds=54566)` and the matrix that exists
    to catch exactly this had never asked the third engine.
    """
    converter = converter_for(time)

    assert converter is not None
    assert converter(timedelta(hours=15, minutes=9, seconds=26)) == time(15, 9, 26)


def test_a_duration_longer_than_a_day_is_refused_instead_of_wrapping() -> None:
    """`timedelta(hours=30)` is not `06:00`, and answering that would be a wrong answer that passes.

    MySQL's `TIME` reaches 838:59:59, so this is reachable data and not a hypothetical. The message
    names the alternative, because the fix is the user's: declare the column `timedelta`.
    """
    converter = converter_for(time)

    assert converter is not None
    with pytest.raises(SnakeValueError, match="838:59:59"):
        converter(timedelta(hours=30))


def test_a_parameterised_dict_comes_back_as_a_dict() -> None:
    """`dict[str, object]` gets the same converter as a bare `dict`, or the raw JSON reaches the user.

    This is the half that makes the compiler fix safe. Letting `accepts()` through without this
    would move the failure from IMPORT to read time, and on the engines where a JSON column is TEXT
    it would not fail at all: the attribute declared `dict[str, object]` would quietly hold the
    string `'{"a": 1}'`.

    `list[str]` already had this, with a comment explaining that same trap. `dict` did not, because
    nothing could reach it — the compiler refused a parameterised dict before anybody got here.
    """
    convert = converter_for(dict[str, object])

    assert convert is not None, (
        "a parameterised dict has no converter: the raw JSON gets through"
    )
    assert convert('{"a": 1}') == {"a": 1}


def test_a_bare_dict_still_works_the_same_way() -> None:
    """The floor: widening to the origin must not change what the unparameterised form does."""
    convert = converter_for(dict)

    assert convert is not None
    assert convert('{"a": 1}') == {"a": 1}
