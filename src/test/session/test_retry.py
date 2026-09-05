"""Retrying on transient concurrency conflicts.

The plan had put this as a DRIVER decorator, next to logging and the timeout, and there it was
wrong. When Postgres aborts a transaction over a serialization failure, the WHOLE transaction is
left unusable: the next statement answers "current transaction is aborted". Retrying the STATEMENT
fixes nothing. The unit of work has to be redone from the start, with its rollback in between, and
that can only be done from the session.
"""

from __future__ import annotations

import pytest

from snakeorm.session.retry import is_transient, with_retry


class _FakeError(Exception):
    """Driver error carrying a SQLSTATE, like the ones psycopg2 raises."""

    def __init__(self, pgcode: str) -> None:
        super().__init__(pgcode)
        self.pgcode = pgcode


class _FakeSession:
    """Pretend session that notes down commits and rollbacks."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_serialization_failure_and_deadlock_are_transient() -> None:
    """Verifies what counts as transient: SQLSTATE class 40, straight from the SQL standard."""
    assert is_transient(_FakeError("40001")) is True  # serialization failure
    assert is_transient(_FakeError("40P01")) is True  # deadlock


def test_a_real_error_is_not_transient() -> None:
    """Verifies that a real error is NOT retried: repeating it is repeating the same failure.

    And with a constraint violation it would be worse than useless: it could duplicate effects.
    """
    assert is_transient(_FakeError("23505")) is False  # unique_violation
    assert is_transient(_FakeError("42601")) is False  # syntax_error
    assert is_transient(ValueError("nothing to do with it")) is False


def test_it_commits_and_returns_on_the_first_try() -> None:
    """Verifies the happy path: one pass, one commit, and the value handed back."""
    session = _FakeSession()
    result = with_retry(session, lambda _: "hecho")  # type: ignore[arg-type]

    assert result == "hecho"
    assert (session.commits, session.rollbacks) == (1, 0)


def test_it_repeats_the_whole_unit_of_work() -> None:
    """WHAT MATTERS: the WHOLE unit of work is redone, with a rollback between attempts."""
    session = _FakeSession()
    intentos: list[int] = []

    def work(_: object) -> str:
        intentos.append(len(intentos) + 1)
        if len(intentos) < 3:
            raise _FakeError("40001")
        return "third time lucky"

    assert with_retry(session, work, attempts=3) == "third time lucky"  # type: ignore[arg-type]
    assert intentos == [1, 2, 3]
    assert session.rollbacks == 2, "every failed attempt leaves the connection usable"
    assert session.commits == 1


def test_it_gives_up_after_the_last_attempt_and_reraises() -> None:
    """Verifies that it does not retry forever and that the original error reaches the caller."""
    session = _FakeSession()

    def work(_: object) -> None:
        raise _FakeError("40001")

    with pytest.raises(_FakeError):
        with_retry(session, work, attempts=2)  # type: ignore[arg-type]

    assert session.rollbacks == 2
    assert session.commits == 0


def test_a_non_transient_error_is_raised_immediately() -> None:
    """Verifies that a real error comes out on the first pass, without burning attempts."""
    session = _FakeSession()
    calls: list[int] = []

    def work(_: object) -> None:
        calls.append(1)
        raise _FakeError("23505")

    with pytest.raises(_FakeError):
        with_retry(session, work, attempts=5)  # type: ignore[arg-type]

    assert calls == [1], "an error that will not get better is not retried"
    assert session.rollbacks == 1


def test_zero_attempts_is_refused() -> None:
    """Verifies that asking for zero attempts is refused: running nothing is never what you want."""
    with pytest.raises(ValueError, match="attempts has to be at least 1"):
        with_retry(_FakeSession(), lambda _: None, attempts=0)  # type: ignore[arg-type]


def test_a_transient_conflict_is_recognised_from_EVERY_driver_this_project_ships() -> (
    None
):
    """`is_transient` reads the conflict off the real exceptions, not off one library's spelling.

    Every test above builds a `_FakeError` carrying the very attribute the code reads, so none of
    them could ever notice that the actual drivers spell it differently — and all three of the
    others do. Measured on the installed libraries:

        psycopg3  SerializationFailure -> sqlstate='40001', pgcode=None
        pymysql   OperationalError     -> args=(1213, 'Deadlock found'), no sqlstate
        sqlite3   OperationalError     -> args=('database is locked',)

    Only `pgcode` was consulted, which is psycopg2's name for it. So `with_retry` — public, exported
    API — retried nothing on psycopg3, MySQL or SQLite. psycopg3 is this project's OWN async driver,
    which means the retry never worked on the asynchronous path at all.

    The double is what hid it. A test whose fixture is shaped like the implementation is not
    testing the implementation, it is agreeing with it.
    """
    import sqlite3

    import psycopg
    import pymysql

    genuinely_transient = [
        ("psycopg3 serialisation", psycopg.errors.SerializationFailure("conflict")),
        ("pymysql deadlock", pymysql.err.OperationalError(1213, "Deadlock found")),
        ("pymysql lock wait", pymysql.err.OperationalError(1205, "Lock wait timeout")),
        ("sqlite busy", sqlite3.OperationalError("database is locked")),
    ]
    not_transient = [
        ("psycopg3 unique violation", psycopg.errors.UniqueViolation("dup")),
        ("pymysql bad syntax", pymysql.err.ProgrammingError(1064, "syntax")),
        ("sqlite no such table", sqlite3.OperationalError("no such table: x")),
    ]

    missed = [name for name, error in genuinely_transient if not is_transient(error)]
    assert missed == [], (
        f"these real conflicts were not recognised as transient, so with_retry would give up "
        f"on them: {missed}"
    )
    wrong = [name for name, error in not_transient if is_transient(error)]
    assert wrong == [], (
        f"these were treated as transient; repeating them repeats the failure: {wrong}"
    )
