"""Asynchronous migration runtime: same logic, the other execution seam.

SQL generation has no "colour" (`up_sql()` does not execute), so diff, DDL, `realize()` and the
operations are reused as they are; only who talks to the DB changes. The real difference: DATA
migrations do NOT run here — `RunPython` receives a SYNCHRONOUS `SnakeSession`, which would block the
event loop — and it stops dead rather than marking them applied with the data never executed.
"""

from __future__ import annotations

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.migration.operations import (
    SnakeDataOperation,
    SnakeMigrationOperation,
    SnakeOperation,
)
from snakeorm.migration.realize import realize
from snakeorm.migration.runner import (
    Migration,
    explain_rebuild_failure,
    squash_already_done,
    tracking_table_ddl,
)
from snakeorm.sql.refs import qualified

_TRACKING_TABLE = "snake_migrations"
_SCHEMA = DEFAULT_SCHEMA


class AsyncMigrationRunner:
    """Applies/reverts migrations over an `AsyncDriver`, with the same tracking as the sync one."""

    def __init__(self, driver: AsyncDriver, dialect: SnakeDialect) -> None:
        self._driver = driver
        self._dialect = dialect

    async def ensure_tracking_table(self) -> None:
        """Creates the tracking table if it does not exist (idempotent)."""
        await self._driver.execute(tracking_table_ddl(self._dialect), ())
        await self._driver.commit()

    async def applied_versions(self) -> set[str]:
        """Returns the set of versions already applied."""
        version = self._dialect.quote_ident("version")
        rows = await self._driver.fetch_all(
            f"SELECT {version} FROM {self._table_ref()}", ()
        )
        return {str(row[0]) for row in rows}

    async def apply(self, migrations: list[Migration]) -> list[str]:
        """Applies the pending migrations in order. Returns the versions applied just now.

        Same semantics as the synchronous one: idempotent, atomic per migration with transactional
        DDL, and a hard stop if a squash replaces a history that was applied HALFWAY.
        """
        await self.ensure_tracking_table()
        already = await self.applied_versions()
        replaced = {
            version for migration in migrations for version in migration.replaces
        }
        newly: list[str] = []
        for migration in migrations:
            if migration.version in already or migration.version in replaced:
                continue
            if migration.replaces and squash_already_done(migration, already):
                await self._record(migration.version)
                await self._driver.commit()
                newly.append(migration.version)
                continue
            if self._dialect.supports_transactional_ddl:
                await self._apply_atomic(migration)
            else:
                await self._apply_stepwise(migration)
            newly.append(migration.version)
        return newly

    async def rollback(self, migration: Migration) -> None:
        """Reverts a migration (operations in reverse order) and deletes its record."""
        for operation in reversed(realize(migration.operations, self._dialect)):
            await self._backward(operation)
        await self._unrecord(migration.version)
        await self._driver.commit()

    async def _apply_atomic(self, migration: Migration) -> None:
        """Applies a migration wrapped in the engine's transaction: all or nothing."""
        plan = realize(migration.operations, self._dialect)
        try:
            for operation in plan:
                await self._forward(operation)
            await self._record(migration.version)
            await self._driver.commit()
        except Exception as error:
            await self._driver.rollback()
            # The SAME sentence the synchronous runner gives, out of the same function: a rebuild
            # that the deferred keys could not cover fails identically here, and this repository has
            # already paid for one complaint told two ways.
            explained = explain_rebuild_failure(plan, self._dialect, error)
            if explained is not None:
                raise explained from error
            raise

    async def _apply_stepwise(self, migration: Migration) -> None:
        """Applies operation by operation (engine without transactional DDL); on error, reports how many."""
        applied = 0
        plan = realize(migration.operations, self._dialect)
        try:
            for operation in plan:
                await self._forward(operation)
                applied += 1
            await self._record(migration.version)
            await self._driver.commit()
        except SnakeMigrationError:
            raise
        except Exception as error:
            raise SnakeMigrationError(
                f"Migration '{migration.version}' failed after applying {applied} of "
                f"{len(plan)} operation(s): {error}. The engine does not support "
                f"transactional DDL, so the database was left half-way: review it and "
                f"fix it by hand."
            ) from error

    async def _forward(self, operation: SnakeMigrationOperation) -> None:
        """Emits a schema operation's DDL; a data one cannot be executed here."""
        _reject_data_operation(operation)
        if isinstance(operation, SnakeOperation):
            for sql in operation.up_sql(self._dialect):
                await self._driver.execute(sql, ())

    async def _backward(self, operation: SnakeMigrationOperation) -> None:
        """Emits a schema operation's reverse DDL."""
        _reject_data_operation(operation)
        if isinstance(operation, SnakeOperation):
            for sql in operation.down_sql(self._dialect):
                await self._driver.execute(sql, ())

    def _table_ref(self) -> str:
        """Reference to the tracking table, qualified only if the engine has schemas."""
        return qualified(_SCHEMA, _TRACKING_TABLE, self._dialect)

    async def _record(self, version: str) -> None:
        column = self._dialect.quote_ident("version")
        await self._driver.execute(
            f"INSERT INTO {self._table_ref()} ({column}) "
            f"VALUES ({self._dialect.placeholder(1)})",
            (version,),
        )

    async def _unrecord(self, version: str) -> None:
        column = self._dialect.quote_ident("version")
        await self._driver.execute(
            f"DELETE FROM {self._table_ref()} WHERE {column} = {self._dialect.placeholder(1)}",
            (version,),
        )


def _reject_data_operation(operation: SnakeMigrationOperation) -> None:
    """Stops dead at a DATA migration: skipping it would mark it applied with the data never run,
    and that never raises an error, only wrong rows months later."""
    if isinstance(operation, SnakeDataOperation):
        raise SnakeMigrationError(
            "The async runner cannot execute a data operation (`RunPython`): its "
            "`forward`/`backward` take a SYNCHRONOUS `SnakeSession`, and running it here would "
            "block the event loop for the whole migration. Apply that migration with "
            "`MigrationRunner` (synchronous) over a synchronous driver; the schema ones do go here."
        )
