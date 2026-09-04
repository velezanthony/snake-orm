"""`with_retry` against a REAL serialisation conflict, provoked rather than simulated.

The retry was covered by tests that built a double carrying the attribute the code happened to read
— `retry.py` says so itself: *"the fixture was shaped like the implementation and agreed with it by
construction"*. A double cannot tell you whether the engine's actual error is recognised, which is
the only thing that matters here: `is_transient` reads `sqlstate`, `pgcode`, a MySQL errno and two
exact SQLite phrases, and every one of those is a guess until a server produces it.

So the conflict is real. Two SERIALIZABLE transactions read what the other is about to change — the
write-skew from the Postgres manual — and the second to commit is aborted with SQLSTATE 40001. No
threads and no sleeping: two connections, sequenced by hand, so the same thing happens every run.

Postgres is the engine that gives a true serialisation failure. MySQL resolves the same shape by
LOCKING, so what it reports is a deadlock or a lock-wait timeout, which `is_transient` recognises by
errno; SQLite cannot even be asked for the isolation level — it answers `Cap.SET_ISOLATION: Nope`,
one writer at a time making its transactions serialisable already. Both are checked here as
declarations, not left as silence.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg2
import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeIsolation,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SQLiteDialect,
    snake_int,
    snake_model,
)
from snakeorm.decorators import snake_table
from snakeorm.drivers.base import SnakeDriver
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.migration import emit_create_table
from snakeorm.session.retry import is_transient, with_retry
from test.conftest import NO_SERVER_REASON
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="rt_tallies")
class Tally(SnakeModel):
    """Two rows in two classes: each transaction reads one class and writes the other."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    kind: SnakeColumn[int] = snake_int()
    amount: SnakeColumn[int] = snake_int()


def _fresh() -> tuple[SnakeDriver, SnakeSession]:
    """A Postgres connection of its own, and a session on it.

    The driver comes back too because DDL has nowhere else to go: `session.raw()` hydrates into a
    declared row shape, which a `CREATE TABLE` does not have.
    """
    try:
        driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    return driver, SnakeSession(driver, PostgresDialect())


@pytest.fixture
def table() -> Iterator[None]:
    """Create and drop the table around each test, through a session of its own."""
    driver, keeper = _fresh()
    driver.execute(f"DROP TABLE IF EXISTS {snake_table(Tally).name}", ())
    driver.execute(emit_create_table(snake_table(Tally), PostgresDialect()), ())
    driver.commit()
    keeper.add_all([Tally(id=1, kind=1, amount=10), Tally(id=2, kind=2, amount=20)])
    keeper.commit()
    yield None
    driver.execute(f"DROP TABLE IF EXISTS {snake_table(Tally).name}", ())
    driver.commit()
    keeper.close()


def _read_the_other_class(session: SnakeSession, kind: int) -> None:
    """Open a SERIALIZABLE transaction and read the class this side will NOT write."""
    session.set_isolation(SnakeIsolation.SERIALIZABLE)
    session.all(SnakeQuery(Tally).filter(Tally.kind == kind))


def _write_into(session: SnakeSession, kind: int, row_id: int) -> None:
    """Insert into the class the OTHER side read: that is what makes the pair conflict."""
    session.add(Tally(id=row_id, kind=kind, amount=1))


def test_a_real_serialisation_failure_is_recognised_as_transient(table: None) -> None:
    """Postgres aborts the second committer with SQLSTATE 40001, and `is_transient` says yes.

    The assertion nobody could make with a double. `is_transient` reads `sqlstate` and `pgcode`
    because psycopg2 and psycopg3 spell it differently, and reading only one of them is a bug this
    project has already had — on its own async driver, where the retry silently never fired.
    """
    (_, left), (_, right) = _fresh(), _fresh()
    try:
        _read_the_other_class(left, 2)
        _read_the_other_class(right, 1)
        _write_into(left, 2, 10)
        _write_into(right, 1, 11)

        left.commit()
        with pytest.raises(psycopg2.Error) as conflict:
            right.commit()

        assert is_transient(conflict.value), (
            "the engine's own serialisation failure was not recognised as retryable"
        )
        assert getattr(conflict.value, "pgcode", "").startswith("40")
    finally:
        right.rollback()
        left.close()
        right.close()


def test_with_retry_runs_the_work_again_and_gets_through(table: None) -> None:
    """The unit of work is repeated after a real abort and the second attempt commits.

    The conflicting party is driven from INSIDE `work`, on its first invocation only: that is what
    makes the failure happen once and the retry find a clear field. Sequencing it by hand rather
    than by sleeping is what keeps the test the same on a loaded machine as on an idle one.
    """
    (_, mine), (_, rival) = _fresh(), _fresh()
    attempts: list[int] = []

    def work(session: SnakeSession) -> int:
        attempts.append(len(attempts) + 1)
        _read_the_other_class(session, 2)
        if len(attempts) == 1:
            _read_the_other_class(rival, 1)
            _write_into(rival, 1, 21)
            rival.commit()
        _write_into(session, 2, 30 + len(attempts))
        return len(attempts)

    try:
        assert with_retry(mine, work) == 2, "it did not take a second attempt"
        assert len(attempts) == 2, "the work ran a number of times nobody asked for"
    finally:
        mine.close()
        rival.close()


def test_running_out_of_attempts_raises_the_engines_own_error(table: None) -> None:
    """With one attempt there is no second chance, and what surfaces is the ENGINE's error.

    Not a wrapper of the ORM's own: the caller needs the SQLSTATE to decide what to do next, and a
    retry helper that swallowed it would be hiding the only useful thing about the failure.
    """
    (_, mine), (_, rival) = _fresh(), _fresh()

    def work(session: SnakeSession) -> int:
        _read_the_other_class(session, 2)
        _read_the_other_class(rival, 1)
        _write_into(rival, 1, 41)
        rival.commit()
        _write_into(session, 2, 42)
        return 0

    try:
        with pytest.raises(psycopg2.Error) as exhausted:
            with_retry(mine, work, attempts=1)
        assert is_transient(exhausted.value)
    finally:
        mine.close()
        rival.close()


def test_a_real_error_is_not_retried(table: None) -> None:
    """A failure that repeating cannot fix is raised at once, and `work` runs exactly once."""
    driver, session = _fresh()
    ran: list[int] = []

    def work(inner: SnakeSession) -> int:
        ran.append(1)
        driver.execute("SELECT this_column_does_not_exist FROM rt_tallies", ())
        return 0

    try:
        with pytest.raises(psycopg2.Error):
            with_retry(session, work)
        assert len(ran) == 1, (
            "a syntax error was retried, which only repeats the failure"
        )
    finally:
        session.close()


@pytest.mark.parametrize(
    "dialect, capability",
    [(SQLiteDialect(), Cap.SET_ISOLATION)],
    ids=lambda value: getattr(value, "name", type(value).__name__),
)
def test_the_engine_that_cannot_be_asked_for_serialisable_declares_it(
    dialect: object, capability: Cap
) -> None:
    """SQLite is absent from the conflict tests because it DECLARES it has no isolation level.

    Written down so the absence is a decision. One writer at a time already makes its transactions
    serialisable, so there is nothing to raise the level to.
    """
    support = dialect.capabilities.support_for(capability)  # type: ignore[attr-defined]

    assert isinstance(support, Nope)
    assert "PRAGMA read_uncommitted" in support.reason


def test_mysql_reports_its_conflicts_by_errno_and_the_reader_knows_it() -> None:
    """MySQL has no SQLSTATE on pymysql's errors, so `is_transient` reads the errno instead.

    It resolves this shape by LOCKING rather than by aborting on commit, so what it reports is a
    deadlock (1213) or a lock-wait timeout (1205). Provoking one needs two connections blocking on
    each other and a timeout to elapse, which is the one thing this file refuses to do — a test that
    waits is a test that fails on a loaded machine. What is checked instead is that the two errnos
    the engine WOULD report are recognised, and that MySQL can be asked for the level at all.
    """
    import pymysql

    assert MySQLDialect().capabilities.can(Cap.SET_ISOLATION)

    for errno in (1213, 1205):
        assert is_transient(pymysql.err.OperationalError(errno, "provoked"))
    assert not is_transient(
        pymysql.err.OperationalError(1064, "you have an error in your SQL")
    )
