"""Tests of `RunPython`: the DATA operation that RUNS logic with the typed ORM.

`RunPython` emits no SQL: it takes a `SnakeSession` and runs code (`forward`/`backward`). It is
verified with a FAKE driver (no database) that: the runner runs the `forward` on apply and the
`backward` on rollback; that a `RunPython` without `backward` raises when undoing is attempted;
and that its `apply_to_state` is a no-op (no table shows up in the replay).

The `forward`/`backward` functions are declared at MODULE LEVEL (not lambdas): that is the contract
the render demands and the realistic use inside a migration file.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.fields import SnakeColumn, snake_int

from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    CreateTable,
    Migration,
    MigrationRunner,
    RunPython,
)
from snakeorm.migration.autodetect import replay
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession


@snake_model(table="rp_ledger")
class _Ledger(SnakeModel):
    """Test model: `forward` fills `doubled` from `balance`."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    balance: SnakeColumn[int] = snake_int()
    doubled: SnakeColumn[int] = snake_int()


def forward(session: SnakeSession) -> None:
    """Data migration: copies `balance` into `doubled` for every row."""
    session.update_where(
        SnakeQuery(_Ledger).filter(_Ledger.id > 0),
        [(_Ledger.doubled, _Ledger.balance)],
    )


def backward(session: SnakeSession) -> None:
    """Reverse: puts `doubled` to 0."""
    session.update_where(
        SnakeQuery(_Ledger).filter(_Ledger.id > 0),
        [(_Ledger.doubled, 0)],
    )


class _FakeDriver:
    """Fake driver: records the executed SQL and returns predefined applied versions."""

    def __init__(self, applied: list[str] | None = None) -> None:
        self._applied_rows: list[tuple[object, ...]] = [
            (version,) for version in (applied or [])
        ]
        self.executed: list[str] = []
        self.committed = 0

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return self._applied_rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.executed.append(sql)
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:  # pragma: no cover
        ...

    def savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def release_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def rollback_to_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover
        ...


def test_runner_runs_forward_on_apply() -> None:
    """On apply, the runner runs the `forward`: the UPDATE that fills `doubled` gets emitted."""
    driver = _FakeDriver()
    runner = MigrationRunner(driver, PostgresDialect())
    runner.apply([Migration("rp_001", (RunPython(forward, backward),))])
    assert any("UPDATE" in sql and '"doubled"' in sql for sql in driver.executed)


def test_runner_runs_backward_on_rollback() -> None:
    """On rollback, the runner runs the `backward` (the reverse of the data migration)."""
    driver = _FakeDriver()
    runner = MigrationRunner(driver, PostgresDialect())
    runner.rollback(Migration("rp_001", (RunPython(forward, backward),)))
    assert any("UPDATE" in sql and '"doubled"' in sql for sql in driver.executed)
    assert any(
        "DELETE FROM" in sql and "snake_migrations" in sql for sql in driver.executed
    )


def test_runner_runs_schema_and_data_ops_together() -> None:
    """A MIXED migration (schema + data): the runner runs BOTH operations with no fragile branches."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="rp_extra",
        columns=(id_col,),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    driver = _FakeDriver()
    runner = MigrationRunner(driver, PostgresDialect())
    runner.apply(
        [Migration("rp_002", (CreateTable(table), RunPython(forward, backward)))]
    )
    assert any("CREATE TABLE" in sql and '"rp_extra"' in sql for sql in driver.executed)
    assert any("UPDATE" in sql and '"doubled"' in sql for sql in driver.executed)


def test_run_python_without_backward_raises_on_unrun() -> None:
    """A `RunPython` without `backward` is not reversible: `unrun` raises `SnakeMigrationError`."""
    driver = _FakeDriver()
    runner = MigrationRunner(driver, PostgresDialect())
    with pytest.raises(SnakeMigrationError, match="backward"):
        runner.rollback(Migration("rp_003", (RunPython(forward),)))


def test_run_python_does_not_change_schema_state() -> None:
    """`apply_to_state` is a no-op: replaying a data migration produces no tables."""
    state = replay([Migration("rp_004", (RunPython(forward, backward),))])
    assert list(state.tables()) == []
