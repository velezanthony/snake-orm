"""The TEXT fallback: a type with no equivalent in the engine is stored anyway, and the ORM says what it loses.

The rule that closes the three-engine support: **a model written once runs on all three**. Whatever an
engine does not have natively falls back to TEXT, the value goes in and comes out EXACT —text loses
nothing, the way back is a parse, not a conversion with risk— and what degrades is the SQL semantics:
ordering, comparing and operating. Startup warns about that, once per thing.

It used to be refused. `SnakeUtc` on MySQL and `list[T]` on SQLite and MySQL raised while compiling
the model, which meant the same model did NOT work on all three engines and the promise stayed half
kept. Refusing protected from a silent surprise, which was the right call while there was no way to
tell about it; with the capability catalog there is one, so now it stores and warns.

And one thing that does NOT change: the declared type is still the type you get. A `Decimal` stored
as TEXT comes back a `Decimal`, not a `str`. Without that half, the fallback would be a type leak
dressed up as compatibility — which is exactly what this ORM does not do.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from snakeorm import MySQLDialect, PostgresDialect, SnakeDialect, SQLiteDialect
from snakeorm.dialects.capabilities import Cap, Degraded
from snakeorm.session.coercion import converter_for
from snakeorm.sql.adapt import adapt_param
from snakeorm.times import SnakeUtc

_NO_ARRAYS = [MySQLDialect(), SQLiteDialect()]


@pytest.mark.parametrize("dialect", _NO_ARRAYS, ids=lambda d: type(d).__name__)
def test_a_list_falls_back_to_text_instead_of_refusing(dialect: SnakeDialect) -> None:
    """Verifies that `list[str]` no longer blows up on the engines without arrays: it falls back to TEXT.

    Refusing it made a model with a list column exist only on Postgres, and the project's promise is
    that the model is written once.
    """
    assert dialect.map_type(list[str]) == "TEXT"


def test_postgres_keeps_its_native_arrays() -> None:
    """Verifies the other half: where there ARE arrays, nothing degrades.

    A fallback that also applied to the engine that has the type would be a free loss.
    """
    assert PostgresDialect().map_type(list[str]) == "TEXT[]"


def test_mysql_stores_an_instant_instead_of_rejecting_it() -> None:
    """Verifies that `SnakeUtc` stops raising on MySQL and falls back to TEXT.

    MySQL has no type with a zone: `DATETIME` is not tz-aware. Storing it in ISO-8601 TEXT preserves
    the whole instant, zone included, which is more than a DATETIME would preserve.
    """
    assert MySQLDialect().map_type(SnakeUtc) == "TEXT"


def test_mysql_stores_a_duration_instead_of_dying_with_a_generic_message() -> None:
    """Verifies that `timedelta` falls back to TEXT on MySQL instead of dying with "no sabe traducir".

    It was the only type that was neither supported nor refused with a reason: it fell through to the
    generic message at the end of `map_type`, which does not say what to do about it.
    """
    assert MySQLDialect().map_type(timedelta) == "TEXT"


@pytest.mark.parametrize("dialect", _NO_ARRAYS, ids=lambda d: type(d).__name__)
def test_what_falls_back_is_declared_as_degraded_not_as_full(
    dialect: SnakeDialect,
) -> None:
    """Verifies that the fallback is DECLARED. Storing without warning would be the same old silent failure.

    It is the half that separates "compatible" from "compatible and you know it": the degraded
    capability is what makes the session emit the warning at startup.
    """
    assert isinstance(dialect.capabilities.support_for(Cap.ARRAYS), Degraded)


def test_a_list_travels_as_json_text_where_there_are_no_native_arrays() -> None:
    """Verifies that WRITING a list serializes it where the engine has no arrays.

    And that it is NOT touched where it does have them: psycopg2 adapts the list to a native array,
    and serializing it beforehand would store it as the text of a list inside an array column.
    """
    assert adapt_param(["a", "b"], native_arrays=False) == '["a", "b"]'
    assert adapt_param(["a", "b"], native_arrays=True) == ["a", "b"]


def test_a_list_comes_back_as_a_list_from_either_engine() -> None:
    """Verifies the WAY BACK, which is the half that holds up the project's thesis.

    The converter is IDEMPOTENT: it swallows the text SQLite returns and the list Postgres returns
    with the same code. That idempotence is what lets the converter registry be engine-agnostic while
    the SQL type is not.
    """
    convert = converter_for(list[str])
    assert convert is not None
    assert convert('["a", "b"]') == ["a", "b"]
    assert convert(["a", "b"]) == ["a", "b"]


def test_an_instant_comes_back_as_an_instant_from_text() -> None:
    """Verifies that a `SnakeUtc` stored as TEXT comes back a `SnakeUtc`, not a `str`.

    If it came back a `str`, the fallback would have traded a loud error for a silent type leak,
    which is worse: the model says `SnakeUtc` and the attribute holds something else.
    """
    convert = converter_for(SnakeUtc)
    assert convert is not None
    rebuilt = convert("2026-08-18T10:30:00+00:00")

    assert isinstance(rebuilt, SnakeUtc)
