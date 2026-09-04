"""Capping how long a statement may run is an EMISSION of the dialect, like the rest of the SQL.

`TimeoutDriver` wrote `SET statement_timeout = <ms>` itself — pure Postgres — under a name that
promises nothing about engines. Measured: MySQL answers `1193 Unknown system variable` and SQLite a
syntax error, so the production knob that keeps one hung query from draining the pool worked on one
engine out of three, and said nothing about it.

THE FORK, and it is worth knowing before reading the MySQL answer: MySQL and MariaDB do not share
this variable and neither accepts the other's. MariaDB has `max_statement_time`, in SECONDS;
Oracle's MySQL has `max_execution_time`, in milliseconds. One dialect, two spellings, no overlap.
The ORM emits MariaDB's — the fork it tests against — and on the other one the server refuses by
name at wrapping time, which is loud and fixable rather than silent.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect, SnakeDialect

_DIALECTS = (PostgresDialect(), MySQLDialect(), SQLiteDialect())


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
def test_every_dialect_answers_how_to_cap_a_statement(dialect: SnakeDialect) -> None:
    """All three answer, and `None` is a legitimate answer: it means the engine has no such thing.

    In the Protocol so a fourth engine cannot arrive without answering, which is the mechanism `Cap`
    already uses. What is not allowed is one engine's SQL leaking out under an agnostic name.
    """
    answer = dialect.statement_timeout_sql(5_000)

    assert answer is None or isinstance(answer, str)


def test_postgres_caps_in_milliseconds() -> None:
    """Postgres takes the value in milliseconds, which is the unit the API is written in."""
    assert (
        PostgresDialect().statement_timeout_sql(5_000) == "SET statement_timeout = 5000"
    )


def test_mysql_converts_to_the_seconds_its_variable_expects() -> None:
    """MariaDB's `max_statement_time` is in SECONDS, so 5000 ms has to travel as 5.

    Handing it 5000 would not fail — it would accept a timeout a THOUSAND times longer than asked
    for, which is the shape of bug that only shows up the day something hangs.
    """
    statement = MySQLDialect().statement_timeout_sql(5_000)

    assert statement is not None
    assert "max_statement_time" in statement and "= 5" in statement
    assert "5000" not in statement


def test_sqlite_says_it_has_none_instead_of_inventing_one() -> None:
    """SQLite has no server-side statement timeout, and `busy_timeout` is NOT one.

    `busy_timeout` waits for a LOCK to free up; it does nothing about a query that is simply slow.
    Returning it here would be answering a different question with a plausible-looking value.
    """
    assert SQLiteDialect().statement_timeout_sql(5_000) is None
