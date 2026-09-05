"""SQLite transactions have to WORK: a rollback undoes, it is not a no-op.

The bug this file closes was the worst one in the whole project, and it had been hiding behind a
single-engine suite. The SQLite driver opens with `isolation_level=None` (autocommit) on the idea,
written down in its own docstring, that "transactions are handled by the session with its explicit
BEGIN". But NOBODY emitted `BEGIN`: not the session, not the runner. So every statement was
committed on the spot and `rollback()` undid absolutely nothing.

The consequence: a `with SnakeSession(...) as s:` that failed halfway left the writes half done
—silently—, which is the opposite of what a context manager promises. Postgres worked (its driver
keeps an implicit transaction open), so the bug lived in SQLite alone: the "correct on N-1 out of N
engines" pattern this project does not get to escape.

The fix: the driver opens the transaction LAZILY on the first statement and closes it on
commit/rollback, which is exactly what psycopg2 does implicitly. These tests pin it down by running
the semantics, not by reading the driver.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_auto,
    snake_int,
    snake_link,
    snake_model,
)
from snakeorm.migration import emit_create_table
from snakeorm.registry import registry as _REG


@snake_model(table="txs_item")
class Item(SnakeModel):
    """Minimal model for watching what persists and what gets reverted."""

    id: SnakeColumn[int] = snake_auto()
    n: SnakeColumn[int] = snake_int()


snake_link()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """In-memory SQLite session with the table created and one row already committed."""
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    table = _REG.table_of(Item)
    assert table is not None
    driver.execute(emit_create_table(table, dialect), ())
    driver.commit()
    s = SnakeSession(driver, dialect)
    s.add(Item(n=1))
    s.commit()
    try:
        yield s
    finally:
        driver.close()


def test_rollback_actually_undoes_an_uncommitted_write(session: SnakeSession) -> None:
    """`rollback()` undoes an uncommitted `add`. It used to be a no-op and the row persisted."""
    session.add(Item(n=2))

    session.rollback()

    assert session.count(SnakeQuery(Item)) == 1, "the uncommitted row had to disappear"


def test_commit_persists_and_survives_a_later_rollback(session: SnakeSession) -> None:
    """What was committed is NOT undone by a later rollback: the commit closes the transaction."""
    session.add(Item(n=2))
    session.commit()
    session.add(Item(n=3))
    session.rollback()

    assert session.count(SnakeQuery(Item)) == 2, (
        "the commit persists; only what came after falls"
    )


def test_the_context_manager_commits_on_clean_exit() -> None:
    """`with session:` commits when it exits without an exception."""
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    table = _REG.table_of(Item)
    assert table is not None
    driver.execute(emit_create_table(table, dialect), ())
    driver.commit()
    try:
        with SnakeSession(driver, dialect) as s:
            s.add(Item(n=7))
        assert SnakeSession(driver, dialect).count(SnakeQuery(Item)) == 1
    finally:
        driver.close()


def test_the_context_manager_rolls_back_on_exception() -> None:
    """`with session:` reverts if the block raises. With no real transaction, the row would stay."""
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    table = _REG.table_of(Item)
    assert table is not None
    driver.execute(emit_create_table(table, dialect), ())
    driver.commit()
    try:
        with pytest.raises(ValueError):
            with SnakeSession(driver, dialect) as s:
                s.add(Item(n=7))
                raise ValueError("boom")
        assert SnakeSession(driver, dialect).count(SnakeQuery(Item)) == 0, (
            "the failed block's write was NOT meant to persist"
        )
    finally:
        driver.close()


def test_a_savepoint_reverts_only_its_own_block(session: SnakeSession) -> None:
    """A savepoint that blows up undoes ONLY its own block; what is outside stays."""
    try:
        with session.savepoint():
            session.add(Item(n=99))
            raise ValueError("boom")
    except ValueError:
        pass
    session.commit()

    assert session.count(SnakeQuery(Item)) == 1, (
        "only the savepoint's block is rolled back"
    )


def test_nested_savepoints_both_commit(session: SnakeSession) -> None:
    """Two nested savepoints that exit cleanly commit both rows."""
    with session.savepoint():
        session.add(Item(n=10))
        with session.savepoint():
            session.add(Item(n=20))
    session.commit()

    assert session.count(SnakeQuery(Item)) == 3
