"""Retrying a UNIT OF WORK in the face of a transient concurrency conflict."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from snakeorm.session.session import SnakeSession

T = TypeVar("T")

# SQLSTATE class 40 ("transaction rollback"): conflicts the engine resolves by aborting the
# transaction, and which get resolved by repeating it (40001 serialisation, 40P01 deadlock). It is
# standard SQL, not Postgres jargon.
_TRANSIENT_SQLSTATE_CLASS = "40"

# Where each DBAPI puts the SQLSTATE. `pgcode` is psycopg2's name and `sqlstate` is psycopg3's, and
# consulting only the first is what made this function answer False for psycopg3 — which is this
# project's OWN async driver, so the retry never worked on the asynchronous path.
_SQLSTATE_ATTRIBUTES = ("sqlstate", "pgcode")

# Engines that do not report a SQLSTATE at all, and what they report instead. Declared with the
# reason rather than sniffed, so adding an engine is answering a question and not remembering one.
_MYSQL_TRANSIENT_ERRNOS = frozenset(
    {
        1213,  # ER_LOCK_DEADLOCK: the server picked this transaction as the deadlock victim
        1205,  # ER_LOCK_WAIT_TIMEOUT: the lock did not come free in time; it may next time
    }
)
"""MySQL reports its own errno in `args[0]`; pymysql exposes no SQLSTATE attribute."""

_SQLITE_TRANSIENT_MESSAGES = ("database is locked", "database table is locked")
"""SQLite has neither SQLSTATE nor a stable errno on `OperationalError`: the message IS the code.

Matching on a message is the thing this module's docstring says not to do, and it is done here on
purpose and only here, because SQLite offers nothing else. It is narrow —two exact phrases from the
C library, not a substring hunt— and it is the difference between a busy database being retried and
being raised at the caller.
"""


def is_transient(error: BaseException) -> bool:
    """Whether the error is a concurrency conflict that makes sense to retry.

    The SQLSTATE is what gets looked at where there is one, not the message nor the driver's class.
    Syntax, constraint or network errors are NOT transient: retrying them repeats the failure (and a
    constraint could duplicate side effects).

    It reads every spelling the shipped drivers use, because it used to read exactly one. The tests
    could not see that: they built a double carrying the attribute the code read, so the fixture was
    shaped like the implementation and agreed with it by construction.
    """
    for attribute in _SQLSTATE_ATTRIBUTES:
        code = getattr(error, attribute, None)
        if isinstance(code, str) and code.startswith(_TRANSIENT_SQLSTATE_CLASS):
            return True
    if error.args and isinstance(error.args[0], int):
        return error.args[0] in _MYSQL_TRANSIENT_ERRNOS
    return any(str(error) == message for message in _SQLITE_TRANSIENT_MESSAGES)


def with_retry(
    session: SnakeSession,
    work: Callable[[SnakeSession], T],
    *,
    attempts: int = 3,
) -> T:
    """Runs `work` and REPEATS it if the engine aborted the transaction over a transient conflict.

        seat = with_retry(session, lambda s: reserve_seat(s, course_id))

    It lives in the session, not in the driver: an abort renders the WHOLE transaction useless
    ("current transaction is aborted"), so the entire unit of work has to be redone along with its
    `rollback` — not the statement. It goes hand in hand with
    `set_isolation(REPEATABLE_READ | SERIALIZABLE)`, which abort on conflict. `work` must be
    IDEMPOTENT with respect to external side effects (do not send the email inside it).
    """
    if attempts < 1:
        raise ValueError(f"attempts has to be at least 1; got {attempts}.")

    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = work(session)
            session.commit()
        except Exception as error:
            session.rollback()  # leaves the connection usable for the next attempt
            if not is_transient(error):
                raise  # a real error does not get better by being repeated
            last = error
            continue
        else:
            return result

    assert last is not None  # the loop is only left by exhausting transient attempts
    raise last
