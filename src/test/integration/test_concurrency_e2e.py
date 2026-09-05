"""INTEGRATION: locking and isolation against a real Postgres, with TWO genuine connections.

This cannot be proved with a single connection, which is why it lives here. `SKIP LOCKED` only means
something when somebody else already holds the row locked; isolation only means something when
somebody else commits while you are reading. With one connection, both are decorative SQL.

It skips gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeIsolation,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="cc_jobs")
class Job(SnakeModel):
    """A queue's jobs: the case where SKIP LOCKED earns its keep."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    payload: SnakeColumn[str] = snake_str()


@pytest.fixture
def two_sessions() -> Iterator[tuple[SnakeSession, SnakeSession]]:
    """Two sessions over DIFFERENT connections, with the queue seeded."""
    import psycopg2

    try:
        first = PsycopgDriver.connect(dsn())
        second = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    first.execute("DROP TABLE IF EXISTS cc_jobs", ())
    first.execute(emit_create_table(snake_table(Job), PostgresDialect()), ())
    for identifier in (1, 2, 3):
        first.execute(
            "INSERT INTO cc_jobs (id, payload) VALUES (%s, %s)",
            (identifier, f"job{identifier}"),
        )
    first.commit()
    try:
        yield (
            SnakeSession(first, PostgresDialect()),
            SnakeSession(second, PostgresDialect()),
        )
    finally:
        second.rollback()
        second.close()
        first.execute("DROP TABLE IF EXISTS cc_jobs", ())
        first.commit()
        first.close()


def test_skip_locked_lets_a_second_worker_take_another_row(
    two_sessions: tuple[SnakeSession, SnakeSession],
) -> None:
    """THE REAL CASE: two workers over the same queue neither collide nor block each other.

    The first claims row 1. The second, with SKIP LOCKED, does NOT wait: it takes the next free one.
    Without SKIP LOCKED it would sit there until the first one committed.
    """
    worker_a, worker_b = two_sessions

    taken_by_a = worker_a.all(SnakeQuery(Job).filter(Job.id == 1).for_update())
    assert [job.id for job in taken_by_a] == [1]

    taken_by_b = worker_b.all(
        SnakeQuery(Job).order_by(Job.id).limit(1).for_update(skip_locked=True)
    )
    assert [job.id for job in taken_by_b] == [2], (
        "the second one should skip the locked row"
    )


def test_nowait_fails_instead_of_waiting(
    two_sessions: tuple[SnakeSession, SnakeSession],
) -> None:
    """Verifies that `NOWAIT` fails on the spot instead of sitting there waiting."""
    import psycopg2

    worker_a, worker_b = two_sessions
    worker_a.all(SnakeQuery(Job).filter(Job.id == 1).for_update())

    with pytest.raises(psycopg2.errors.LockNotAvailable):
        worker_b.all(SnakeQuery(Job).filter(Job.id == 1).for_update(nowait=True))


def test_repeatable_read_keeps_a_stable_snapshot(
    two_sessions: tuple[SnakeSession, SnakeSession],
) -> None:
    """Verifies isolation for real: inside REPEATABLE READ the snapshot does NOT change.

    The reader opens its transaction and counts. The writer inserts and commits. The reader counts
    again and has to see THE SAME: that is the whole difference from READ COMMITTED, and it can only
    be demonstrated with two connections.
    """
    writer, reader = two_sessions

    reader.set_isolation(SnakeIsolation.REPEATABLE_READ)
    before = reader.count(SnakeQuery(Job))

    writer.add(Job(id=99, payload="tardío"))
    writer.commit()

    assert reader.count(SnakeQuery(Job)) == before, (
        "the REPEATABLE READ snapshot must be stable"
    )


def test_read_committed_sees_what_others_commit(
    two_sessions: tuple[SnakeSession, SnakeSession],
) -> None:
    """Verifies the contrast: under READ COMMITTED the second read DOES see what was committed.

    It is Postgres's default, and the classic surprise for anyone who assumes two identical reads
    inside one transaction give the same answer.
    """
    writer, reader = two_sessions

    reader.set_isolation(SnakeIsolation.READ_COMMITTED)
    before = reader.count(SnakeQuery(Job))

    writer.add(Job(id=99, payload="tardío"))
    writer.commit()

    assert reader.count(SnakeQuery(Job)) == before + 1
