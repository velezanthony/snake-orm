"""Tests of the migration runtime: idempotent apply + rollback, with tracking.

Exercised with a FAKE driver (no database): verifies that the operations run, that the version
gets recorded, that what is already applied is skipped and that rollback undoes + unrecords.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import CreateTable, Migration, MigrationRunner


def _table(name: str) -> SnakeTableInfo:
    """Minimal test table."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name=name, columns=(id_col,), primary_key=SnakePrimaryKeyInfo(columns=(id_col,))
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
        self.executed.append(sql)
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


def test_apply_runs_operations_and_records_version() -> None:
    """Verifies that apply runs the CREATE TABLE, records the version and returns it."""
    driver = _FakeDriver()
    runner = MigrationRunner(driver, PostgresDialect())
    applied = runner.apply([Migration("001_users", (CreateTable(_table("users")),))])
    assert applied == ["001_users"]
    assert any("CREATE TABLE" in sql and '"users"' in sql for sql in driver.executed)
    assert any(
        "INSERT INTO" in sql and "snake_migrations" in sql for sql in driver.executed
    )


def test_apply_skips_already_applied() -> None:
    """Verifies that apply is idempotent: an already applied version is not re-run."""
    driver = _FakeDriver(applied=["001_users"])
    runner = MigrationRunner(driver, PostgresDialect())
    applied = runner.apply([Migration("001_users", (CreateTable(_table("users")),))])
    assert applied == []
    assert not any(
        "CREATE TABLE" in sql and '"users"' in sql for sql in driver.executed
    )


def test_apply_runs_pending_in_order() -> None:
    """Verifies that several pending migrations are applied in order."""
    driver = _FakeDriver()
    runner = MigrationRunner(driver, PostgresDialect())
    applied = runner.apply(
        [
            Migration("001", (CreateTable(_table("a")),)),
            Migration("002", (CreateTable(_table("b")),)),
        ]
    )
    assert applied == ["001", "002"]


def test_rollback_runs_down_and_unrecords() -> None:
    """Verifies that rollback runs the DROP TABLE (reverse) and deletes the record."""
    driver = _FakeDriver()
    runner = MigrationRunner(driver, PostgresDialect())
    runner.rollback(Migration("001_users", (CreateTable(_table("users")),)))
    assert any("DROP TABLE" in sql and '"users"' in sql for sql in driver.executed)
    assert any(
        "DELETE FROM" in sql and "snake_migrations" in sql for sql in driver.executed
    )


def test_ensure_tracking_table_is_if_not_exists() -> None:
    """Verifies that the tracking table is created with IF NOT EXISTS (idempotent)."""
    driver = _FakeDriver()
    MigrationRunner(driver, PostgresDialect()).ensure_tracking_table()
    assert any(
        "CREATE TABLE IF NOT EXISTS" in sql and "snake_migrations" in sql
        for sql in driver.executed
    )
