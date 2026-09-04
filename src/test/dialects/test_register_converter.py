"""The SECOND axis of the type vocabulary: how the value TRAVELS, not how the column is written.

`register_type()` opened the vocabulary at one end only. It said an `Inet` is written `INET` on
Postgres and `TEXT` on SQLite, and that was that: `adapt_param` was a closed cascade of `isinstance`,
so the value never reached the base —the driver blew up with an error of its own, unwrapped— and
`converter_for` did not know how to rebuild it, so what came back was the base type.

The example published in `docs/users/guide/columns.md` did not work on any engine.

Two axes, two calls, each in its place:

- `dialect.register_type(type, sql)` — per DIALECT, because the same Python type is written
  differently on each engine.
- `register_converter(type, to_db=, from_db=)` — GLOBAL, because the value's trip does not depend on
  the engine... as long as `from_db` is IDEMPOTENT. That is the condition holding it all up: it is
  what lets a single converter swallow the `Decimal` Postgres returns and the `str` SQLite returns
  without asking which engine it is on. The eleven internal converters already satisfy it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import PostgresDialect, SQLiteDialect, register_converter
from snakeorm.core import converters
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.session.coercion import converter_for
from snakeorm.sql.adapt import adapt_param


class Inet:
    """An IP address from the user's domain. The ORM does not know it at all."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        """Two equal addresses are the same one; it is needed in order to assert the round trip."""
        return isinstance(other, Inet) and other.value == self.value

    def __hash__(self) -> int:
        """Defined alongside `__eq__`, so as not to leave the type without a hash."""
        return hash(self.value)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Leaves the global registry as it was.

    The value axis is GLOBAL on purpose —a domain type travels the same whatever engine it goes to—,
    and that means a test that registers something sneaks it into the following ones. Isolating it
    here is cheaper than finding out three weeks from now in a test that has nothing to do with it.
    """
    to_db = dict(converters._TO_DB)
    from_db = dict(converters._FROM_DB)
    yield
    converters._TO_DB.clear()
    converters._TO_DB.update(to_db)
    converters._FROM_DB.clear()
    converters._FROM_DB.update(from_db)


def test_a_registered_type_travels_there_and_back() -> None:
    """Verifies the WHOLE trip of a type the ORM does not know: DDL, writing and reading.

    It is what the documentation's example promised and did not do. The eight tests that existed
    compared `map_type` strings: none of them wrote and read, and that is why the missing half was
    invisible.
    """
    postgres, sqlite = PostgresDialect(), SQLiteDialect()
    postgres.register_type(Inet, "INET")
    sqlite.register_type(Inet, "TEXT")
    register_converter(
        Inet,
        to_db=lambda ip: ip.value,
        # The `if isinstance` is NOT defensive: it is the idempotence. Postgres with a native INET
        # type may already return the object and SQLite returns the text; the converter swallows both.
        from_db=lambda raw: raw if isinstance(raw, Inet) else Inet(str(raw)),
    )

    assert postgres.map_type(Inet) == "INET"
    assert sqlite.map_type(Inet) == "TEXT"

    written = adapt_param(Inet("10.0.0.1"), native_arrays=False)
    assert written == "10.0.0.1", (
        "without `to_db`, the driver gets an object it does not know how to send"
    )

    convertir = converter_for(Inet)
    assert convertir is not None
    assert convertir(written) == Inet("10.0.0.1")


def test_the_reader_must_be_idempotent_or_the_registry_lies() -> None:
    """Verifies that `from_db` is required to be idempotent, and that it is checked at register time.

    It is the condition that lets this axis be engine-agnostic. A `from_db` that only knows how to
    swallow SQLite's text would blow up the day someone points at Postgres, and it would blow up on a
    production READ, which is the worst place to find out.

    The counterexample is the one everybody writes —handing it the type's constructor— and that is why
    it deserves the guard: `Inet(Inet("10.0.0.1"))` does not fail, it NESTS, and the nested value only
    shows up when comparing or serializing it, much later.
    """
    with pytest.raises(SnakeConfigError, match="is not idempotent"):
        # The type: ignore is part of the test: mypy ALREADY sees that `Inet` does not fit the
        # `from_db` signature (it asks for `object`, and its `__init__` asks for `str`). The checker
        # catching half the cases does not remove the runtime guard — a badly written `lambda` passes
        # the checker and gets here all the same.
        register_converter(Inet, to_db=lambda ip: ip.value, from_db=Inet)  # type: ignore[arg-type]


def test_registering_a_converter_does_not_touch_the_built_in_ones() -> None:
    """Verifies that opening up the vocabulary does not rewrite the one already there.

    A global registry invites a third-party library, just by being imported, to change how a `Decimal`
    travels for the whole process. The types the ORM already handles are its own and do not get
    rewritten.
    """
    with pytest.raises(SnakeConfigError, match="is a type the ORM already handles"):
        from decimal import Decimal

        register_converter(Decimal, to_db=str, from_db=lambda raw: Decimal(str(raw)))


def test_an_unregistered_type_still_fails_loudly() -> None:
    """Verifies that registering NOTHING is still a loud error, not a weird value in the base.

    The TEXT fallback is for the types the ORM knows and the engine does not; a type nobody has
    declared has no reason to be guessed.
    """
    sqlite = SQLiteDialect()

    with pytest.raises(Exception):  # noqa: B017 - the dialect raises its own SnakeDialectError
        sqlite.map_type(Inet)
