"""The MAPPING from an engine's code to the ORM's exception, without an engine.

TWO HALVES, AND THIS FILE IS ONLY ONE OF THEM. Here the doubles carry a code and the question is
which exception comes out. That is genuinely useful — MariaDB reports a CHECK as 4025 and MySQL 8 as
3819, and keeping both in the table is not something you want to need three servers to verify — and
it is also the exact shape that once fooled this repository: `is_transient`'s tests built a double
carrying the attribute the code read, so the fixture agreed with the implementation by construction
and neither could see the bug.

So the claim here is narrow ON PURPOSE: given this code, that exception. Whether the engine really
sends that code is `test_driver_failures_e2e.py`'s question, asked of a live server. A double cannot
answer it and this file does not pretend to.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import (
    SnakeCheckViolation,
    SnakeForeignKeyViolation,
    SnakeIntegrityError,
    SnakeNotNullViolation,
    SnakeUniqueViolation,
)
from snakeorm.drivers.failures import translate, translating_failures


class _Postgres(Exception):
    """Shaped like psycopg2's: the SQLSTATE hangs off `pgcode`."""

    def __init__(self, pgcode: str) -> None:
        super().__init__("the server refused it")
        self.pgcode = pgcode


class _Psycopg3(Exception):
    """psycopg3 spells the same attribute `sqlstate`, and reading only one is a bug this ORM had."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__("the server refused it")
        self.sqlstate = sqlstate


class _SQLite(Exception):
    """Shaped like `sqlite3`'s from Python 3.11: the extended result code, by name."""

    def __init__(self, name: str) -> None:
        super().__init__("the server refused it")
        self.sqlite_errorname = name


class _MySQL(Exception):
    """pymysql puts the errno in `args[0]` and exposes no SQLSTATE attribute at all."""

    def __init__(self, errno: int) -> None:
        super().__init__(errno, "the server refused it")


@pytest.mark.parametrize(
    "error, expected",
    [
        (_Postgres("23505"), SnakeUniqueViolation),
        (_Postgres("23503"), SnakeForeignKeyViolation),
        (_Postgres("23502"), SnakeNotNullViolation),
        (_Postgres("23514"), SnakeCheckViolation),
        (_Psycopg3("23505"), SnakeUniqueViolation),
        (_MySQL(1062), SnakeUniqueViolation),
        (_MySQL(1452), SnakeForeignKeyViolation),
        (_MySQL(1451), SnakeForeignKeyViolation),
        (_MySQL(1048), SnakeNotNullViolation),
        (_MySQL(3819), SnakeCheckViolation),
        (_MySQL(4025), SnakeCheckViolation),
        (_SQLite("SQLITE_CONSTRAINT_UNIQUE"), SnakeUniqueViolation),
        (_SQLite("SQLITE_CONSTRAINT_PRIMARYKEY"), SnakeUniqueViolation),
        (_SQLite("SQLITE_CONSTRAINT_FOREIGNKEY"), SnakeForeignKeyViolation),
        (_SQLite("SQLITE_CONSTRAINT_NOTNULL"), SnakeNotNullViolation),
        (_SQLite("SQLITE_CONSTRAINT_CHECK"), SnakeCheckViolation),
    ],
    ids=lambda value: (
        getattr(value, "__name__", None) or str(value.args[-1])[:0] or "case"
    ),
)
def test_a_code_maps_to_its_exception(
    error: Exception, expected: type[SnakeIntegrityError]
) -> None:
    """One case per code, including the pairs where the two MySQL forks disagree.

    `1451` and `1452` are the two SIDES of a foreign key —the row that is not there and the row that
    is still pointed at— and both are the same problem to whoever catches it. `3819` and `4025` are
    MySQL 8's and MariaDB's names for a failed CHECK.
    """
    translated = translate(error)

    assert type(translated) is expected


def test_what_is_not_a_constraint_is_left_alone() -> None:
    """A syntax error, a dropped connection, a timeout: they keep flying untouched.

    Wrapping what was not diagnosed would put an ORM name on a problem the ORM did not understand,
    which reads as an answer and is worse than the raw exception it replaced.
    """
    assert translate(_Postgres("42601")) is None
    assert translate(_MySQL(2006)) is None
    assert translate(_SQLite("SQLITE_BUSY")) is None
    assert translate(ValueError("nothing to do with a database")) is None


def test_the_original_and_the_code_are_kept() -> None:
    """What the wrapper was built from stays reachable, and the code says WHY this subtype."""
    original = _MySQL(4025)

    translated = translate(original)

    assert isinstance(translated, SnakeCheckViolation)
    assert translated.driver_error is original
    assert translated.code == 4025


def test_the_context_manager_chains_instead_of_hiding() -> None:
    """`raise ... from`, so the traceback prints both and `__cause__` holds the driver's."""
    original = _Postgres("23505")

    with pytest.raises(SnakeUniqueViolation) as caught:
        with translating_failures():
            raise original

    assert caught.value.__cause__ is original
    assert caught.value.driver_error is original


def test_the_context_manager_re_raises_what_it_does_not_understand() -> None:
    """Unchanged, not swallowed and not renamed: the same object comes back out."""
    original = _Postgres("42601")

    with pytest.raises(_Postgres) as caught:
        with translating_failures():
            raise original

    assert caught.value is original
