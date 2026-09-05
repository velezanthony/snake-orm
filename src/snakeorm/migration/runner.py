"""Migration runtime: applies and reverts migrations, with tracking in the database.

The order comes from the files' linear numbering (there is no `down_revision`). The applied versions
are stored in `snake_migrations`, which makes `apply` IDEMPOTENT. Every migration is ATOMIC if the
engine has transactional DDL; if it does not, on error it reports how many operations were applied.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers import SnakeDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import SnakeStrParams
from snakeorm.migration.operations import (
    RebuildTable,
    SnakeDataOperation,
    SnakeMigrationOperation,
    SnakeOperation,
)
from snakeorm.migration.realize import realize
from snakeorm.session import SnakeSession
from snakeorm.sql.refs import qualified

_TRACKING_TABLE = "snake_migrations"
_SCHEMA = DEFAULT_SCHEMA


@dataclass(frozen=True, slots=True)
class Migration:
    """A versioned unit of operations (schema and/or data). The order comes from its number."""

    version: str
    operations: tuple[SnakeMigrationOperation, ...]
    replaces: tuple[str, ...] = ()
    """Versions this migration REPLACES (a squash). Empty in a normal migration.

    It allows a history to be collapsed without breaking the databases where the originals were
    already applied: there the squash is marked applied without being executed. See `apply`.
    """


def squash_already_done(migration: Migration, already: set[str]) -> bool:
    """Is this squash's work already done by the migrations it replaces?

    - ALL applied -> yes. The DB is already in that state; running it would repeat a `CREATE TABLE`.
    - NONE applied -> no. Fresh install: it runs.
    - SOME yes and others no -> it STOPS. Running it would repeat what is done and marking it would
      skip what is missing; both corrupt, so it is flagged and the human decides.

    A loose function (not a method) so both runners share THE SAME answer: a duplicated criterion
    that drifts decides differently in silence.
    """
    done = [version for version in migration.replaces if version in already]
    if not done:
        return False
    if len(done) == len(migration.replaces):
        return True
    missing = [version for version in migration.replaces if version not in already]
    raise SnakeMigrationError(
        f"The squash '{migration.version}' replaces a history that was applied HALF-WAY: "
        f"{sorted(done)} are already there and {sorted(missing)} are missing. It can neither "
        f"be run (it would repeat what is done) nor be marked as applied (it would skip what is "
        f"missing). Apply the missing ones first with the original history and try again."
    )


def explain_rebuild_failure(
    plan: Sequence[SnakeMigrationOperation], dialect: SnakeDialect, error: Exception
) -> SnakeMigrationError | None:
    """Turns a rebuild's integrity failure into a sentence, or `None` if that is not what happened.

    A loose function, like `squash_already_done` and `tracking_table_ddl`, and for the same reason:
    the two runners must not be able to answer this differently.

    WHAT IT IS EXPLAINING, measured on SQLite 3.50. A rebuild drops the old table halfway through,
    and that orphans every row of every OTHER table whose foreign key names it. The keys are
    deferred, so nothing fails there — but SQLite counts deferred violations instead of rechecking
    them, and putting the table back three statements later does not bring the counter down. So the
    COMMIT refuses with four words, `PRAGMA foreign_key_check` says the database is clean, and the
    person reading the deploy log has no way in.

    It does not repair anything: the migration has already rolled back, which is correct. What it
    adds is the name of the table, the reason the check disagrees, and the one instrument that lifts
    the limit — `PRAGMA foreign_keys = OFF` on a connection with NO transaction open, which is where
    that pragma stops being a no-op.

    IT ANSWERS A SECOND FAILURE, and the two do not look alike. A rebuild finishes with a `RENAME`,
    and on this engine a rename REPARSES the whole schema — so a view standing over the table makes
    that statement fail with `error in view <v>: no such table: main.<t>`, naming a table the reader
    can see with their own eyes and a view nobody touched. The generator emits the rebuild bare on
    purpose, because which tables a view reads is not something the metadata says, so this turns the
    engine's sentence into the two operations the migration was missing.
    """
    if dialect.syntax.defer_constraints_statement is None:
        return None
    rebuilt = [
        operation.after.name
        for operation in plan
        if isinstance(operation, RebuildTable)
    ]
    if not rebuilt:
        return None
    message = str(error).lower()
    if "error in view" in message:
        return SnakeMigrationError(
            f"The rebuild of {', '.join(sorted(set(rebuilt)))} could not be applied: this engine "
            f"has to DROP the table to change a constraint on it and RENAME the replacement into "
            f"place, and a RENAME reparses the WHOLE schema — every view in it. A view whose SELECT "
            f"names the table is unparseable at that instant, so the RENAME is what failed, not the "
            f"drop, and the engine's own words ({error}) name a table that does exist. Nothing was "
            f"applied: the migration rolled back whole. Surround the rebuild with the two "
            f"operations that say it out loud — a DropView of that view BEFORE it and a CreateView "
            f"of the same view AFTER it — and the rename has nothing left to reparse. The "
            f"generator does not write them for you, and cannot: nothing in the metadata says "
            f"which TABLES a view reads (a `sql=` view is raw text, and `depends_on` only names "
            f"other views), so which view has to come down is a decision only you can make."
        )
    if "foreign key" not in message:
        return None
    return SnakeMigrationError(
        f"The rebuild of {', '.join(sorted(set(rebuilt)))} could not be committed: this engine has "
        f"to DROP the table to change a constraint on it, and a foreign key from another table "
        f"still names it. The keys were deferred, so the drop went through and the COMMIT is what "
        f"refused — and `PRAGMA foreign_key_check` will tell you the database is clean, because "
        f"deferred violations are COUNTED at the moment they happen and not re-checked at the end. "
        f"Nothing was applied: the migration rolled back whole. To let it through, the foreign keys "
        f"have to be off, and `PRAGMA foreign_keys = OFF` is a no-op inside a transaction — it has "
        f"to be issued on the connection BEFORE the migration opens one."
    )


_VERSION_MAX_LENGTH = 255
"""Length of the tracking table's `version` column.

Not a random number: it is the classic one that fits a MySQL index under any collation, and this
column IS the table's primary key. A migration name does not come anywhere close to it.
"""


def tracking_table_ddl(dialect: SnakeDialect) -> str:
    """The `CREATE TABLE IF NOT EXISTS` for `snake_migrations`, for either runner.

    A loose function, like `squash_already_done`, and for the same reason made concrete: the two
    runners must not be able to answer this differently. They already did. The synchronous one
    learned the hard way that a hard-wired `TEXT` makes MySQL reject the entire table — "BLOB/TEXT
    column used in key specification without a key length", error 1170, because this column IS the
    primary key — and asked the dialect for the type instead, with the reason written down. The
    async runner was written later, copied the shape rather than the lesson, and carried the bug on
    the FIRST statement of its `apply()`: on MySQL the async migration system never started.

    Nothing caught it. The parity test between the runners compared method NAMES, and both are
    called `ensure_tracking_table`.

    With a declared length each engine emits its own: `VARCHAR(255)` on Postgres and MySQL, `TEXT`
    on SQLite, which does not distinguish.
    """
    table = qualified(_SCHEMA, _TRACKING_TABLE, dialect)
    version = dialect.quote_ident("version")
    applied_at = dialect.quote_ident("applied_at")
    version_type = dialect.map_type(
        str, params=SnakeStrParams(max_length=_VERSION_MAX_LENGTH)
    )
    return (
        f"CREATE TABLE IF NOT EXISTS {table} "
        f"({version} {version_type} NOT NULL, "
        f"{applied_at} TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        f"PRIMARY KEY ({version}))"
    )


class MigrationRunner:
    """Applies/reverts migrations and records the applied ones in `snake_migrations`."""

    def __init__(self, driver: SnakeDriver, dialect: SnakeDialect) -> None:
        self._driver = driver
        self._dialect = dialect
        # A session over the SAME driver/dialect: the `RunPython`s run the ORM inside the
        # migration's transaction, atomic alongside the schema operations.
        self._session = SnakeSession(driver, dialect)

    def ensure_tracking_table(self) -> None:
        """Creates the tracking table if it does not exist (idempotent).

        The DDL itself is `tracking_table_ddl`, shared with the async runner. It used to live here,
        and the async one carried its own copy with the MySQL bug this one had already fixed — which
        is the reason it is a loose function now and not a method on each.
        """
        self._driver.execute(tracking_table_ddl(self._dialect), ())
        self._driver.commit()

    def applied_versions(self) -> set[str]:
        """Returns the set of versions already applied."""
        version = self._dialect.quote_ident("version")
        rows = self._driver.fetch_all(f"SELECT {version} FROM {self._table_ref()}", ())
        return {str(row[0]) for row in rows}

    def apply(self, migrations: list[Migration]) -> list[str]:
        """Applies the pending migrations in order. Returns the versions applied just now.

        Every migration is ATOMIC: its operations and the version record go together. With
        transactional DDL a failure halfway does a `rollback()`; without it, how many were applied is
        reported.
        """
        self.ensure_tracking_table()
        already = self.applied_versions()
        replaced = {
            version for migration in migrations for version in migration.replaces
        }
        newly: list[str] = []
        for migration in migrations:
            if migration.version in already:
                continue
            # A migration replaced by a squash in this batch is not applied: the squash does it.
            if migration.version in replaced:
                continue
            if migration.replaces and squash_already_done(migration, already):
                self._record(migration.version)
                self._driver.commit()
                newly.append(migration.version)
                continue
            if self._dialect.supports_transactional_ddl:
                self._apply_atomic(migration)
            else:
                self._apply_stepwise(migration)
            newly.append(migration.version)
        return newly

    def _apply_atomic(self, migration: Migration) -> None:
        """Applies a migration wrapped in the engine's transaction: all or nothing."""
        plan = realize(migration.operations, self._dialect)
        try:
            for operation in plan:
                self._forward(operation)
            self._record(migration.version)
            self._driver.commit()
        except Exception as error:
            self._driver.rollback()  # undoes the operations already emitted for THIS migration
            explained = explain_rebuild_failure(plan, self._dialect, error)
            if explained is not None:
                raise explained from error
            raise

    def _apply_stepwise(self, migration: Migration) -> None:
        """Applies operation by operation (engine without transactional DDL); on error, reports how many."""
        applied = 0
        plan = realize(migration.operations, self._dialect)
        try:
            for operation in plan:
                self._forward(operation)
                applied += 1
            self._record(migration.version)
            self._driver.commit()
        except Exception as error:
            raise SnakeMigrationError(
                f"Migration '{migration.version}' failed after applying {applied} of "
                f"{len(plan)} operation(s): {error}. The engine does not support "
                f"transactional DDL, so the database was left half-way: review it and "
                f"fix it by hand."
            ) from error

    def rollback(self, migration: Migration) -> None:
        """Reverts a migration (operations in reverse order) and deletes its record."""
        for operation in reversed(realize(migration.operations, self._dialect)):
            self._backward(operation)
        self._unrecord(migration.version)
        self._driver.commit()

    def _forward(self, operation: SnakeMigrationOperation) -> None:
        """Runs an operation forwards, dispatching by STRUCTURE.

        Data (`SnakeDataOperation`) has `run` and runs with the session; schema (`SnakeOperation`) has
        `up_sql` and executes its DDL. Both in the same transaction (a mixed migration is still
        all-or-nothing).
        """
        if isinstance(operation, SnakeDataOperation):
            operation.run(self._session)
        elif isinstance(operation, SnakeOperation):
            for sql in operation.up_sql(self._dialect):
                self._driver.execute(sql, ())

    def _backward(self, operation: SnakeMigrationOperation) -> None:
        """Reverts an operation: the DATA one runs its `unrun`; the SCHEMA one emits its reverse DDL."""
        if isinstance(operation, SnakeDataOperation):
            operation.unrun(self._session)
        elif isinstance(operation, SnakeOperation):
            for sql in operation.down_sql(self._dialect):
                self._driver.execute(sql, ())

    def _table_ref(self) -> str:
        """Reference to the tracking table, qualified ONLY if the engine has schemas.

        Qualifying `"public"."snake_migrations"` by hand broke on SQLite (`unknown database
        "public"`); `qualified()` exists for exactly this.
        """
        return qualified(_SCHEMA, _TRACKING_TABLE, self._dialect)

    def _record(self, version: str) -> None:
        column = self._dialect.quote_ident("version")
        self._driver.execute(
            f"INSERT INTO {self._table_ref()} ({column}) "
            f"VALUES ({self._dialect.placeholder(1)})",
            (version,),
        )

    def _unrecord(self, version: str) -> None:
        column = self._dialect.quote_ident("version")
        self._driver.execute(
            f"DELETE FROM {self._table_ref()} WHERE {column} = {self._dialect.placeholder(1)}",
            (version,),
        )
