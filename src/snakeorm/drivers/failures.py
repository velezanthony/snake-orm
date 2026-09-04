"""Turning a driver's exception into the ORM's, by CODE and never by message.

A violated constraint came back as `psycopg2.errors.UniqueViolation`, `pymysql.err.IntegrityError`
and `sqlite3.IntegrityError`: three types for one condition, so the `except` that handled it was the
one part of an application this ORM could not carry between engines.

WHY BY CODE. Reading the message is how a detector fails open — it finds only what somebody already
thought to look for. It is also not needed: all three engines say precisely which constraint broke,
each in its own place.

    postgres  SQLSTATE           23505 / 23503 / 23502 / 23514
    mysql     errno              1062  / 1452  / 1048  / 4025
              (its SQLSTATE is 23000 for all four and says nothing)
    sqlite    sqlite_errorname   SQLITE_CONSTRAINT_UNIQUE / _FOREIGNKEY / _NOTNULL / _CHECK
              (Python 3.11+, which is this project's declared floor)

AND NEVER BY THE DRIVER'S CLASS, which is the trap this module exists to keep shut: on MySQL a CHECK
violation arrives as `OperationalError` while the other three arrive as `IntegrityError`. Keyed on
the class, that one lands in the wrong bucket on one engine only.

One function for the three engines, the same way `session/retry.py::is_transient` reads them: it
looks for each spelling in turn and does not need to know who raised.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import ParamSpec, TypeVar, cast

from snakeorm.core.exceptions import (
    SnakeCheckViolation,
    SnakeForeignKeyViolation,
    SnakeIntegrityError,
    SnakeNotNullViolation,
    SnakeUniqueViolation,
)

P = ParamSpec("P")
T = TypeVar("T")
AsyncMethod = TypeVar("AsyncMethod", bound=Callable[..., Awaitable[object]])
"""An asynchronous driver method, PRESERVED. Bound and not `ParamSpec` + return, because what
has to survive the decorator is the exact signature the Protocol declares, `CoroutineType`
included."""

_BY_SQLSTATE: dict[str, type[SnakeIntegrityError]] = {
    "23505": SnakeUniqueViolation,
    "23503": SnakeForeignKeyViolation,
    "23502": SnakeNotNullViolation,
    "23514": SnakeCheckViolation,
}
"""PostgreSQL, which is the only one whose SQLSTATE distinguishes the four."""

_BY_MYSQL_ERRNO: dict[int, type[SnakeIntegrityError]] = {
    1062: SnakeUniqueViolation,  # ER_DUP_ENTRY
    1586: SnakeUniqueViolation,  # ER_DUP_ENTRY_WITH_KEY_NAME
    1452: SnakeForeignKeyViolation,  # ER_NO_REFERENCED_ROW_2
    1451: SnakeForeignKeyViolation,  # ER_ROW_IS_REFERENCED_2 (the delete side)
    1048: SnakeNotNullViolation,  # ER_BAD_NULL_ERROR
    3819: SnakeCheckViolation,  # ER_CHECK_CONSTRAINT_VIOLATED (MySQL 8)
    4025: SnakeCheckViolation,  # ER_CONSTRAINT_FAILED (MariaDB)
}
"""MySQL and MariaDB. Two errnos per family where the engines disagree, and both are listed rather
than one guessed: MariaDB reports a CHECK as 4025 and MySQL 8 as 3819, and a foreign key breaks from
either side."""

_BY_SQLITE_NAME: dict[str, type[SnakeIntegrityError]] = {
    "SQLITE_CONSTRAINT_UNIQUE": SnakeUniqueViolation,
    "SQLITE_CONSTRAINT_PRIMARYKEY": SnakeUniqueViolation,
    "SQLITE_CONSTRAINT_FOREIGNKEY": SnakeForeignKeyViolation,
    "SQLITE_CONSTRAINT_NOTNULL": SnakeNotNullViolation,
    "SQLITE_CONSTRAINT_CHECK": SnakeCheckViolation,
}
"""SQLite's EXTENDED result codes. `PRIMARYKEY` is its own name for what the other two call a unique
violation, so it maps to the same exception rather than falling through to the generic family."""


_SAYS: dict[type[SnakeIntegrityError], str] = {
    SnakeUniqueViolation: "a UNIQUE constraint refused the write: that value is already there",
    SnakeForeignKeyViolation: (
        "a FOREIGN KEY refused the write: the row it points at is not there, or it is still "
        "pointed at"
    ),
    SnakeNotNullViolation: "a NOT NULL column was given nothing",
    SnakeCheckViolation: "a CHECK constraint refused the write",
}
"""What the ORM says, in its OWN words, before quoting the engine.

Passing the driver's text through unchanged was half a translation: the exception was portable and
the sentence it carried still was not, so anything reading the message was back to three engines.
In this ORM the message is the product.

The engine's own words follow, because they carry what these cannot — WHICH constraint, and the
value that collided. Two texts for one fact, in the right order: what happened, then who said so.
"""


def translate(error: BaseException) -> SnakeIntegrityError | None:
    """The ORM exception this driver error corresponds to, or `None` if it is not a constraint.

    `None` is the answer for everything else — a syntax error, a dropped connection, a timeout — and
    those keep flying untouched. Wrapping what is not understood would put an ORM name on a problem
    the ORM did not diagnose, which is worse than the raw exception it replaced.
    """
    for attribute in ("sqlstate", "pgcode"):
        sqlstate = getattr(error, attribute, None)
        if isinstance(sqlstate, str) and sqlstate in _BY_SQLSTATE:
            return _built(_BY_SQLSTATE[sqlstate], error, sqlstate)
    name = getattr(error, "sqlite_errorname", None)
    if isinstance(name, str) and name in _BY_SQLITE_NAME:
        return _built(_BY_SQLITE_NAME[name], error, name)
    errno = error.args[0] if error.args else None
    if isinstance(errno, int) and errno in _BY_MYSQL_ERRNO:
        return _built(_BY_MYSQL_ERRNO[errno], error, errno)
    return None


def _built(
    kind: type[SnakeIntegrityError], error: BaseException, code: str | int
) -> SnakeIntegrityError:
    """The exception, its message and what it was built from, in one place."""
    return kind(
        f"{_SAYS[kind]}. The engine said: {error}", driver_error=error, code=code
    )


@contextmanager
def translating_failures() -> Iterator[None]:
    """Runs a driver call and re-raises a constraint failure as the ORM's own, CHAINED.

    `from error` is the whole difference between wrapping and hiding: the original stays in
    `__cause__`, the traceback prints both, and whoever debugs still gets the server's own words
    about what it refused.
    """
    try:
        yield
    except Exception as error:
        translated = translate(error)
        if translated is None:
            raise
        raise translated from error


def translating(method: Callable[P, T]) -> Callable[P, T]:
    """Applies the translation to one synchronous driver method.

    A decorator and not a `with` inside each body, because it is the same line twenty times and a
    decorator is the version somebody can see is MISSING from a method.

    Not for `fetch_iter`: it is a generator, so this wrapper would return it without running a
    statement and the exception would escape untranslated during iteration. It is also not needed —
    it walks a SELECT, and a SELECT breaks no constraint.
    """

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        with translating_failures():
            return method(*args, **kwargs)

    return wrapper


def async_translating(method: AsyncMethod) -> AsyncMethod:
    """The same for an asynchronous driver method. The colour changes; the classification does not.

    It gives BACK the type it was handed, instead of describing the wrapper: a decorator that
    translates exceptions must not change what the method IS. Spelling the return as
    `Callable[P, Coroutine[object, object, T]]` looked equivalent and was not — an `async def`
    declared in a Protocol is a `CoroutineType`, which a plain `Coroutine` does not satisfy, so
    every driver wrapped by this stopped being an `AsyncDriver` for pyright while mypy said
    nothing. The one function that hands the pair out (`connection.py::driver_and_dialect`) was
    the visible casualty.
    """

    @functools.wraps(method)
    async def wrapper(*args: object, **kwargs: object) -> object:
        with translating_failures():
            return await method(*args, **kwargs)

    return cast("AsyncMethod", wrapper)
