"""SnakeORM CLI: makemigrations, migrate, rollback, status, fresh, scaffold, check, squash, tables, table, advise, dto.

The commands import the models module first and call `snake_link()`: without resolving the FKs, the diff and the FK DDL would come out incomplete.
"""

from __future__ import annotations

import argparse
import importlib
import os
import pathlib
import sys
import types
import warnings
from collections.abc import Sequence
from pathlib import Path

from snakeorm.cli.discovery import find_config
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.core.config import (
    DB_ENV_KEYS,
    DEFAULT_DATABASE,
    backend_name_for,
    dsn_for,
    dsn_from_env,
    load_env,
)
from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.dialects import (
    MySQLDialect,
    PostgresDialect,
    SnakeDialect,
    SQLiteDialect,
)
from snakeorm.drivers import PsycopgDriver, SnakeDriver
from snakeorm.core.exceptions import (
    SnakeConfigError,
    SnakeError,
    SnakeMigrationError,
    SnakeWarning,
)
from snakeorm.advisor import unindexed_foreign_keys
from snakeorm.introspection import (
    MySQLIntrospector,
    PostgresIntrospector,
    SnakeIntrospector,
    SQLiteIntrospector,
    drift,
    SnakeMirrorNames,
    render_models,
    unrepresentable,
)
from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto import specs_in_source, sync_file
from snakeorm.linker.linker import snake_link
from snakeorm.metadata import SnakeColumnInfo, SnakeTableInfo
from snakeorm.migration import (
    MigrationRunner,
    autodetect,
    current_schema,
    format_narrowing_hint,
    format_rename_hint,
    load,
    narrowing_warnings,
    rename_suggestions,
    render_migration,
    replay,
    squash,
    standing_view_warning,
)

# Imported through its private name because that is the name it has. It is the topological sort the
# diff already derives from the foreign keys, and `_wipe_order` needs exactly it — writing a second
# one would be two answers to one question, which is how the drop order came to disagree with the
# `snakeorm.migration`, and that edit belongs to `migration/`, not here.
from snakeorm.migration import drop_order
from snakeorm.core.signals import models_with_signals, signals_of
from snakeorm.decorators.model import snake_table

_DEFAULT_DIR = "migrations"


def report_failure(error: BaseException) -> None:
    """Writes a failure to STDERR, with the engine's own words when there are any.

    `rg -n "stderr" src/snakeorm/` used to return nothing at all: every message the package printed,
    error or not, went to stdout. So `snakeorm migrate --database prod > migration.log` put the
    failure INSIDE the file it was told to write, the `2>&1` of the calling script captured nothing,
    and CI was left with an exit code and no context.

    The `__cause__` travels with it, and ALWAYS rather than behind a `--traceback`. The wrapper says
    "the migration stopped after applying 2 of 5"; the cause says `column "slug" already exists`,
    which is the thing the command was run to find out. A flag you have to know about is a flag
    nobody sets on the run that already failed.

    What a command ANSWERS keeps going to stdout — `snakeorm check > drift.txt` is a CI writing a
    report, and the report is not an error.
    """
    print(f"Error: {error}", file=sys.stderr)
    cause = error.__cause__
    if cause is not None:
        print(f"  caused by: {type(cause).__name__}: {cause}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """The CLI entry point. It returns the exit code (0 = ok)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        handler = args.handler
        return int(handler(args))
    except SnakeError as error:
        report_failure(error)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser with the three subcommands."""
    parser = argparse.ArgumentParser(
        prog="snakeorm", description="SnakeORM migrations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    make = subparsers.add_parser(
        "makemigrations", help="Generate a migration with the schema changes."
    )
    make.add_argument(
        "--models",
        default=None,
        help="Module with the models (e.g. myapp.models). Optional: without it the app's entry "
        "point is used. REQUIRED with --only, which needs it to name the domain.",
    )
    make.add_argument("--dir", default=_DEFAULT_DIR, help="Migrations directory.")
    make.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help="Connection to operate on (multi-DB). Each one has its own history.",
    )
    make.add_argument("--name", default="auto", help="Slug for the migration name.")
    make.add_argument(
        "--check",
        action="store_true",
        help="Writes nothing: exits with a non-zero code if migrations are missing (CI gate).",
    )
    make.add_argument(
        "--only",
        action="store_true",
        help="PER-DOMAIN migration: only the tables of the models declared in --models (not the whole "
        "registry). FKs to other domains are resolved by name; apply them in dependency order.",
    )
    make.set_defaults(handler=_cmd_makemigrations)

    migrate = subparsers.add_parser("migrate", help="Apply the pending migrations.")
    migrate.add_argument(
        "--models",
        default=None,
        help="Module with the models. Optional: without it the app's entry point is used.",
    )
    migrate.add_argument("--dir", default=_DEFAULT_DIR, help="Migrations directory.")
    migrate.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help="Connection to operate on (multi-DB). Each one has its own history.",
    )
    migrate.add_argument(
        "--dsn", default=None, help="DSN of the database (or environment variables)."
    )
    migrate.set_defaults(handler=_cmd_migrate)

    rollback = subparsers.add_parser(
        "rollback", help="Undo the last applied migration."
    )
    rollback.add_argument(
        "--models",
        default=None,
        help="Module with the models. Optional: without it the app's entry point is used.",
    )
    rollback.add_argument("--dir", default=_DEFAULT_DIR, help="Migrations directory.")
    rollback.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help="Connection to operate on (multi-DB). Each one has its own history.",
    )
    rollback.add_argument(
        "--dsn", default=None, help="DSN of the database (or environment variables)."
    )
    rollback.set_defaults(handler=_cmd_rollback)

    scaffold = subparsers.add_parser(
        "scaffold",
        help="Generate MIRROR models by reading an existing database (DB-first).",
    )
    scaffold.add_argument(
        "mode",
        choices=("create", "update"),
        help="create: the first time; fails if the file already exists. update: overwrites it entirely.",
    )
    scaffold.add_argument("--out", required=True, help="Models file to generate.")
    scaffold.add_argument("--schema", default=DEFAULT_SCHEMA, help="Schema to read.")
    scaffold.add_argument(
        "--keep-underscores",
        action="store_true",
        help="Class names keep the table's underscores (Public_project_requests) instead of CapWords.",
    )
    scaffold.add_argument(
        "--no-schema-prefix",
        action="store_true",
        help="Class names drop the schema. Two schemas with the same table name then COLLIDE, and the collision is reported.",
    )
    scaffold.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help="Connection to read the schema from.",
    )
    scaffold.add_argument(
        "--dsn", default=None, help="DSN of the database (or environment variables)."
    )
    scaffold.set_defaults(handler=_cmd_scaffold)

    check = subparsers.add_parser(
        "check", help="Compare the models against the REAL schema and report the drift."
    )
    check.add_argument(
        "--models",
        default=None,
        help="Module with the models. Optional: without it the app's entry point is used.",
    )
    check.add_argument("--schema", default=DEFAULT_SCHEMA, help="Schema to read.")
    check.add_argument(
        "--database", default=DEFAULT_DATABASE, help="Connection to check."
    )
    check.add_argument(
        "--dsn", default=None, help="DSN of the database (or environment variables)."
    )
    check.set_defaults(handler=_cmd_check)

    sq = subparsers.add_parser(
        "squash",
        help="Collapse a stretch of the history into ONE migration that replaces it.",
    )
    sq.add_argument("--dir", default="migrations", help="Migrations directory.")
    sq.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help="Connection whose history gets collapsed.",
    )
    sq.add_argument(
        "--until", required=True, help="Last version of the stretch to collapse."
    )
    sq.add_argument("--name", required=True, help="Name of the resulting migration.")
    sq.set_defaults(handler=_cmd_squash)

    tables_p = subparsers.add_parser(
        "tables",
        help="List the tables of the models (or of the real DB with --from-db). --detail adds columns.",
    )
    tables_p.add_argument("--models", help="Module with the models (or use --from-db).")
    tables_p.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help="Connection to inspect (multi-DB).",
    )
    tables_p.add_argument(
        "--from-db",
        action="store_true",
        help="Read the REAL DB (introspection), not the models.",
    )
    tables_p.add_argument(
        "--schema", default=DEFAULT_SCHEMA, help="Schema to read with --from-db."
    )
    tables_p.add_argument("--dsn", default=None, help="DSN of the DB (for --from-db).")
    tables_p.add_argument(
        "--detail",
        action="store_true",
        help="Also show the columns of each table.",
    )
    tables_p.set_defaults(handler=_cmd_tables)

    table_p = subparsers.add_parser(
        "table",
        help="Detail of ONE table (columns and relations). Validates the name. --from-db reads the real DB.",
    )
    table_p.add_argument("name", help="Name of the table to inspect.")
    table_p.add_argument("--models", help="Module with the models (or use --from-db).")
    table_p.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help="Connection to inspect (multi-DB).",
    )
    table_p.add_argument(
        "--from-db",
        action="store_true",
        help="Read the REAL DB (introspection), not the models.",
    )
    table_p.add_argument(
        "--schema", default=DEFAULT_SCHEMA, help="Schema to read with --from-db."
    )
    table_p.add_argument("--dsn", default=None, help="DSN of the DB (for --from-db).")
    table_p.set_defaults(handler=_cmd_table)

    status = subparsers.add_parser(
        "status",
        help="List the migrations and which ones are applied (like migrate:status).",
    )
    status.add_argument("--dir", default=_DEFAULT_DIR, help="Migrations directory.")
    status.add_argument(
        "--database", default=DEFAULT_DATABASE, help="Connection (multi-DB)."
    )
    status.add_argument(
        "--dsn", default=None, help="DSN of the DB (or environment variables)."
    )
    status.set_defaults(handler=_cmd_status)

    fresh = subparsers.add_parser(
        "fresh",
        help="DROP every table and re-apply all the migrations (like migrate:fresh).",
    )
    fresh.add_argument(
        "--models",
        default=None,
        help="Module with the models. Optional: without it the app's entry point is used.",
    )
    fresh.add_argument("--dir", default=_DEFAULT_DIR, help="Migrations directory.")
    fresh.add_argument(
        "--database", default=DEFAULT_DATABASE, help="Connection (multi-DB)."
    )
    fresh.add_argument(
        "--dsn", default=None, help="DSN of the DB (or environment variables)."
    )
    fresh.set_defaults(handler=_cmd_fresh)

    advise = subparsers.add_parser(
        "advise",
        help="Audit the schema and suggest indexes for the FKs that lack one.",
    )
    advise.add_argument(
        "--models",
        default=None,
        help="Module with the models. Optional: without it the app's entry point is used.",
    )
    advise.add_argument(
        "--database", default=DEFAULT_DATABASE, help="Connection to audit (multi-DB)."
    )
    advise.set_defaults(handler=_cmd_advise)

    dto = subparsers.add_parser(
        "dto",
        help="Write the TypedDicts of every `snake_dto(...)` declaration into its own file.",
    )
    dto.add_argument(
        "--file",
        action="append",
        required=True,
        dest="files",
        help="File holding `snake_dto(...)` declarations. Repeatable.",
    )
    dto.add_argument(
        "--sync",
        action="store_true",
        help="WRITE the bodies. Without it the command only reports, and exits 1 if anything drifted.",
    )
    dto.set_defaults(handler=_cmd_dto)

    return parser


def _prepare_models(module_name: str | None) -> None:
    """Fill the registry with the models and link their relations (mandatory before diffing).

    With `--models` the named module is imported, which is what it always did. WITHOUT it the
    application's own entry point is found and imported instead — and that import IS the
    registration, so the flag went from being required to being an override.

    Which is the whole trick, and it is not a new mechanism: the module that boots the app already
    imports the models, and the `SnakeOrmConfig` it builds already holds the connections and the
    migrations directory. Asking for them again on the command line was a second source for a fact
    the application had already stated — and two sources for one fact eventually disagree.
    """
    if module_name:
        _import_named(module_name)  # registers the models in the global registry
    else:
        find_config()  # importing the entry point is what registers them
    snake_link()  # resolves the relations (FKs); without this the diff comes out incomplete


def _import_named(module_name: str) -> types.ModuleType:
    """Imports a module the user named on the command line, from the directory they are standing in.

    The working directory goes on the path first. A console script does not get it for free the way
    `python -m` does, so `--models main` failed with `ModuleNotFoundError` in the very directory
    holding `main.py` — while discovery, which adds the root it found, worked. Two routes to the
    same import behaving differently is the kind of gap somebody debugs for an hour before
    suspecting the tool.
    """
    cwd = str(pathlib.Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    return importlib.import_module(module_name)


def _connection_for(
    args: argparse.Namespace,
) -> tuple[SnakeDriver, SnakeDialect]:
    """Driver and dialect PAIRED, taken from the application when there is one.

    The CLI used to open a `PsycopgDriver` beside a `PostgresDialect` in seven places, so a project
    on SQLite or MySQL could not apply a migration from the command line at all — while
    `SnakeOrmConfig.migrate()` did it on all three, and said so in its own docstring: *"unlike the
    CLI, which is tied to Postgres"*. One of the two was the product and the other was the
    documented command.

    Nothing new pairs them here. `SnakeConnectionConfig.driver_and_dialect()` already builds the two
    together from the `backend`, which is what makes a driver joined to another engine's dialect
    impossible to express. The CLI simply was not asking.

    `--dsn` keeps its old meaning and its old shortcut: an explicit DSN is Postgres, and no
    application is looked for. That is the path of a script with no `SnakeOrmConfig` to find, and it
    worked before this change.
    """
    if args.dsn:
        return PsycopgDriver.connect(_resolve_dsn(args.dsn, args.database)), (
            PostgresDialect()
        )
    try:
        connection = find_config().databases[args.database]
    except SnakeConfigError:
        # No application to ask: fall back to the environment, which is how a bare project has
        # always resolved its database — but PAIRED BY BACKEND, not assumed to be Postgres.
        #
        # It used to build a `PsycopgDriver` with a `PostgresDialect` whatever the DSN said, so
        # `SNAKEORM_DSN_REPORTS=sqlite:///reports.db` handed psycopg2 a SQLite URL. That is the one
        # thing `SnakeConnectionConfig` exists to make INEXPRESSIBLE, bypassed by the one caller
        # that did not go through it. The engine is READ from the DSN's scheme by
        # `backend_name_for`, never guessed.
        resolved = _resolve_dsn(None, args.database)
        backend = SnakeBackend(backend_name_for(args.database))
        return SnakeConnectionConfig.from_dsn(resolved, backend).driver_and_dialect()
    except KeyError:
        raise SnakeConfigError(
            f"The application declares no connection named '{args.database}'. Its "
            f"SnakeOrmConfig lists: {', '.join(sorted(find_config().databases))}."
        ) from None
    return connection.driver_and_dialect()


def _introspector_for(driver: SnakeDriver, dialect: SnakeDialect) -> SnakeIntrospector:
    """The introspector that matches the engine, paired the same way driver and dialect are.

    Reading a schema is the THIRD axis beside writing the SQL and executing it, and the CLI used to
    hardcode the Postgres one — so `scaffold` and `check` did not work on the other two engines
    while `architecture.md` published a green tick for all three. The tick was the wish and the
    hardcoding was the product.

    It matches on the DIALECT and not on the driver because the dialect is what the pairing already
    goes through: a driver joined to another engine's dialect is not expressible, so matching on one
    is matching on both.
    """
    if isinstance(dialect, MySQLDialect):
        return MySQLIntrospector(driver)
    if isinstance(dialect, SQLiteDialect):
        return SQLiteIntrospector(driver)
    return PostgresIntrospector(driver)


def _migrations_dir(args: argparse.Namespace) -> Path:
    """Migrations directory of THIS connection: each DB has its own history and linear numbering.

    The default connection keeps the usual directory so single-DB projects do not break.
    """
    base = Path(args.dir)
    return base if args.database == DEFAULT_DATABASE else base / args.database


def _declared_tables(module_name: str) -> set[str]:
    """Table names of the models DECLARED/re-exported in `module_name` (per-domain migrations).

    A model carries `__snake_registry__`; a `@snake_result` does not (it is no table), so it stays
    out.
    """
    module = importlib.import_module(module_name)
    return {
        snake_table(obj).name
        for obj in vars(module).values()
        if isinstance(obj, type) and hasattr(obj, "__snake_registry__")
    }


def _cmd_makemigrations(args: argparse.Namespace) -> int:
    """Generate a new migration file if the schema changed with respect to the history."""
    module_name: str | None = args.models
    directory = _migrations_dir(args)
    _prepare_models(module_name)

    schema = current_schema(database=args.database)
    if args.only:
        # PER DOMAIN: only the tables of this module; the FKs to other domains are resolved by
        # autodetect by name through the global registry (the target table must exist when
        # APPLYING: migrate in order).
        #
        # This is the one place `--models` cannot be discovered away. Everywhere else the flag only
        # says "import this so the models register", and the application's entry point already does
        # that. Here it says something else entirely — WHICH domain this migration is for — and no
        # amount of discovery can guess which of ten domains you meant.
        if module_name is None:
            raise SnakeError(
                "`--only` needs `--models`: it generates the migration for ONE domain, and the "
                "module you name is what says which. Without it there is nothing to narrow the "
                "schema down to. Drop `--only` for a migration over the whole registry."
            )
        declared = _declared_tables(module_name)
        schema = [table for table in schema if table.name in declared]
    history = load(directory)
    operations = autodetect(history, schema)
    if not operations:
        print("No changes: the schema is already up to date with the history.")
        return 0

    if args.check:
        # A CI gate. Unlike `check` (code vs the real DB), this compares code vs the HISTORY: "am I missing a migration to generate?".
        print(
            f"Missing migrations: {len(operations)} operation(s) not recorded. "
            f"Run `makemigrations` without --check."
        )
        return 1

    number = len(history) + 1
    version = f"{number:04d}_{args.name}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version}.py"
    path.write_text(render_migration(version, operations))
    print(f"Created migration {path} with {len(operations)} operation(s).")
    # The diff sees a rename as drop + add, which DELETES the old column. It gets WARNED about so the human swaps it for a RenameColumn.
    hint = format_rename_hint(rename_suggestions(operations))
    if hint:
        print(hint)
    # Narrowing a type may not fit the existing rows: the warning comes when GENERATING, not once the deploy is already under way.
    narrowing = format_narrowing_hint(narrowing_warnings(operations))
    if narrowing:
        print(narrowing)
    # A destructive operation under standing views, warned HERE and not inside `autodetect()`. The
    # choice is deliberate and it has a cost worth writing down: `autodetect()` is called by tests
    # and by the demos' drift check on every run, where nobody is reading, so a warning raised
    # there would become background noise — and background noise is how a real warning gets
    # ignored. The cost is that somebody calling `autodetect()` from their own code does NOT get
    # this: the ORM says it at the one moment there is a person in front of the terminal, which is
    # `makemigrations`. The state is replayed a second time on purpose (`autodetect` does its own,
    # and does not hand it back); it is an in-memory walk over the history already loaded.
    standing = standing_view_warning(operations, replay(history).tables())
    if standing:
        warnings.warn(standing, SnakeWarning, stacklevel=2)
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Apply to the database the migrations of the directory that have not been applied yet."""
    module_name: str = args.models
    _prepare_models(module_name)

    # The connection is resolved FIRST, and that ordering is load-bearing: a typo in `--database`
    # used to exit 0 with "there are no migrations", reporting SUCCESS on a deploy command. It used
    # to be `_resolve_dsn` alone; now it opens the real pair, which validates the same thing and
    # more (an alias the application does not declare fails here, naming the ones it does).
    driver, dialect = _connection_for(args)

    migrations = load(_migrations_dir(args))
    if not migrations:
        driver.close()
        print(f"There are no migrations for connection '{args.database}'.")
        return 0

    try:
        runner = MigrationRunner(driver, dialect)
        applied = runner.apply(migrations)
    finally:
        driver.close()

    if applied:
        print(f"Applied {len(applied)} migration(s): {', '.join(applied)}.")
    else:
        print("All up to date: there were no pending migrations.")
    return 0


def _cmd_rollback(args: argparse.Namespace) -> int:
    """Undo the last applied migration (the highest-numbered one among those registered)."""
    module_name: str = args.models
    _prepare_models(module_name)

    # Opened before anything else: it validates the connection, same as it always did.
    driver, dialect = _connection_for(args)
    migrations = load(_migrations_dir(args))
    try:
        runner = MigrationRunner(driver, dialect)
        runner.ensure_tracking_table()
        applied = runner.applied_versions()
        registered = [
            migration for migration in migrations if migration.version in applied
        ]
        if not registered:
            print("There is no applied migration to undo.")
            return 0
        last = registered[
            -1
        ]  # the list is in linear order; the last one is the highest-numbered
        runner.rollback(last)
    finally:
        driver.close()

    print(f"Rolled back migration {last.version}.")
    return 0


def _cmd_scaffold(args: argparse.Namespace) -> int:
    """Generate the mirror models of an existing DB: `create` fails if the file exists, `update` overwrites it whole.

    There is no mode that preserves your edits: it is a mirror of the DB, your code goes in ANOTHER
    file.
    """
    destination = Path(args.out)
    if args.mode == "create" and destination.exists():
        raise SnakeConfigError(
            f"{destination} already exists. Use `scaffold update` to regenerate it whole, or delete "
            f"it if you prefer to start from scratch. `create` does not overwrite on purpose."
        )

    driver, dialect = _connection_for(args)
    try:
        introspector = _introspector_for(driver, dialect)
        tables = introspector.tables(args.schema)
        names = SnakeMirrorNames(
            capwords=not args.keep_underscores,
            include_schema=not args.no_schema_prefix,
        )
        unsupported = introspector.unsupported(args.schema) + unrepresentable(
            tables, names
        )
    finally:
        driver.close()

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_models(tables, unsupported, names))
    print(
        f"Generated {destination} with {len(tables)} table(s) from '{args.database}'."
    )
    # Whatever is not representable is ALWAYS warned about: silence reads as "all covered".
    for item in unsupported:
        print(f"  warning: not representable in the model -> {item}")
    return 0


def _cmd_dto(args: argparse.Namespace) -> int:
    """Bring every generated TypedDict in step with its specs — reporting, or writing.

    TWO modes and one answer, which is why they are one command. Without `--sync` it is a CHECK: it
    prints the drift and exits 1, so a DTO that stopped matching its model is a red build instead of
    a wrong response a front end finds out about. With `--sync` it writes exactly what the check
    would have complained about.

    It never imports the file it is about to rewrite. The declarations live under `if TYPE_CHECKING:`
    and are READ out of the source with `ast`; the only thing imported is the models module they
    name, because the compiled metadata is where the types and the nullability live. So the check
    mode executes nothing of the user's at all, and a DTO file that does not import is not this
    command's problem.

    Nothing changes in silence in either mode. Every field added, dropped or retyped is printed by
    name, because the file being edited is the user's.
    """
    changed = False
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            raise SnakeDtoError(f"{path} does not exist, so there is nothing to read.")
        # The working directory goes on the path so the MODELS module the file names can be
        # imported. A console script does not get it for free the way `python -m` does.
        cwd = str(pathlib.Path.cwd())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
        source = path.read_text(encoding="utf-8")
        if not specs_in_source(source, path=str(path)):
            # An ERROR and not a note, because the alternative reads exactly like success. A file
            # meant to hold declarations and holding none is almost always the wrong path, and
            # "nothing to do" is the one answer that hides it.
            raise SnakeDtoError(
                f"{path} declares no snake_dto(...), so nothing was read. Check the path: the "
                f"declarations go in the file the classes are written into, under "
                f"`if TYPE_CHECKING:`."
            )
        result = sync_file(path, write=args.sync)
        if not result.changed:
            print(f"{path}: up to date.")
            continue
        changed = True
        verb = "Wrote" if args.sync else "Would write"
        print(f"{path}: {verb} {len(result.changes)} change(s).")
        for change in result.changes:
            print(f"  {change.describe()}")
    if changed and not args.sync:
        print(
            "Run `snakeorm dto --sync` to write them, and read the diff: these classes live in "
            "your files."
        )
        return 1
    return 0


def _warn_signals_and_bulk() -> None:
    """Remind which models have signals connected and that the bulk path (update_where/delete_where) does NOT fire them.

    It does not return an error code: it is a design warning, not drift; turning it into a failure
    would block a legitimate use of the bulk path.
    """
    models = sorted(models_with_signals(), key=lambda model: model.__name__)
    if not models:
        return
    print("Connected signals (remember: update_where/delete_where do NOT fire them):")
    for model in models:
        names = ", ".join(signal.value for signal in signals_of(model))
        print(f"  - {model.__name__}: {names}")


def _cmd_squash(args: argparse.Namespace) -> int:
    """Collapse the history UP TO `--until` (a PREFIX, not an arbitrary stretch) into one migration that replaces it.

    It does not delete the originals: they are needed as long as a DB exists with only some of the
    replaced ones applied. Deleting them is a later decision of the human.
    """
    directory = _migrations_dir(args)
    history = load(directory)
    if not history:
        print(f"There are no migrations to collapse in {directory}.")
        return 1

    versions = [migration.version for migration in history]
    if args.until not in versions:
        print(
            f"'{args.until}' is not in the history. Available: {', '.join(versions)}",
            file=sys.stderr,
        )
        return 1

    to_squash = history[: versions.index(args.until) + 1]
    try:
        collapsed = squash(to_squash, version=f"{len(history) + 1:04d}_{args.name}")
    except SnakeMigrationError as error:
        print(f"Cannot collapse: {error}", file=sys.stderr)
        return 1

    path = directory / f"{collapsed.version}.py"
    path.write_text(
        render_migration(collapsed.version, collapsed.operations, collapsed.replaces)
    )
    print(
        f"Created {path}: {len(to_squash)} migration(s) collapsed into "
        f"{len(collapsed.operations)} operation(s)."
    )
    print(
        "The original files have NOT been deleted: they are needed as long as a database exists "
        "with only some of them applied."
    )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    """Compare the code against the REAL schema and return != 0 if there is drift (a CI gate).

    Unlike `makemigrations` (code vs the HISTORY), it answers "did somebody touch the DB from the
    outside?".
    """
    _prepare_models(args.models)
    driver, dialect = _connection_for(args)
    try:
        real = _introspector_for(driver, dialect).tables(args.schema)
    finally:
        driver.close()

    # `include_unmanaged`: a @snake_db_first mirror IS in the code, so its drift counts. What does
    # not count is a table the ORM does not declare: that one belongs to somebody else.
    declared = current_schema(database=args.database, include_unmanaged=True)
    _warn_signals_and_bulk()
    # The dialect is what makes the comparison honest: both sides are compared as the SQL type
    # this engine writes, not as a Python type only the code side has.
    differences = drift(declared, real, dialect)
    if not differences:
        print("No drift: the code and the database say the same thing.")
        return 0
    print(f"Drift detected ({len(differences)}):")
    for item in differences:
        print(f"  - {item}")
    return 1


def _format_column(column: SnakeColumnInfo) -> str:
    """One column line for the inspection: name, Python type and flags (NULL/NOT NULL, UNIQUE)."""
    flags = ["NULL" if column.nullable else "NOT NULL"]
    if column.unique:
        flags.append("UNIQUE")
    return f"{column.name:<18} {column.python_type.__name__:<10} {' '.join(flags)}"


def _tables_for_inspect(args: argparse.Namespace) -> list[SnakeTableInfo]:
    """The tables to inspect: from the REAL DB (`--from-db`, introspection) or from the models."""
    if args.from_db:
        driver, dialect = _connection_for(args)
        try:
            return _introspector_for(driver, dialect).tables(args.schema)
        finally:
            driver.close()
    # No guard on `--models` any more: without it `_prepare_models` finds the application's entry
    # point, and if there is no application either it raises naming every route it tried.
    _prepare_models(args.models)
    return current_schema(database=args.database)


def _cmd_tables(args: argparse.Namespace) -> int:
    """List the tables (from the models or from the real DB with `--from-db`). `--detail` adds columns."""
    tables = sorted(_tables_for_inspect(args), key=lambda table: table.name)
    if not tables:
        print("There are no tables registered for those models.")
        return 0
    print(f"{len(tables)} table(s):")
    for table in tables:
        kind = "view" if table.is_view else "table"
        pk = ", ".join(column.name for column in table.primary_key.columns)
        print(
            f"  {table.name:<22} {len(table.columns):>2} col · "
            f"{len(table.relationships)} rel · PK({pk})  [{kind}]"
        )
        if args.detail:
            for column in table.columns:
                print(f"      {_format_column(column)}")
    return 0


def _cmd_table(args: argparse.Namespace) -> int:
    """Detail of ONE table (columns + relations), from the models or from the real DB (`--from-db`).
    If the name does not exist, it FAILS listing the available ones."""
    by_name = {table.name: table for table in _tables_for_inspect(args)}
    table = by_name.get(args.name)
    if table is None:
        available = ", ".join(sorted(by_name)) or "(none)"
        raise SnakeError(f"unknown table '{args.name}'. Available tables: {available}")
    pk_names = {column.name for column in table.primary_key.columns}
    kind = "view" if table.is_view else "table"
    print(f"{kind}: {table.schema}.{table.name}")
    print(f"  columns ({len(table.columns)}):")
    for column in table.columns:
        pk = "  · PK" if column.name in pk_names else ""
        print(f"    {_format_column(column)}{pk}")
    if table.relationships:
        print(f"  relations ({len(table.relationships)}):")
        for relationship in table.relationships:
            target = relationship.target
            print(
                f"    {relationship.name:<18} -> {target}  [{relationship.kind.value}]"
            )
    return 0


def _format_status(versions: Sequence[str], applied: set[str]) -> str:
    """Migration status (applied vs pending) as text. Pure: testable without a DB."""
    lines = [f"{len(versions)} migration(s):"]
    pending = 0
    for version in versions:
        done = version in applied
        pending += 0 if done else 1
        lines.append(f"  {'✓ applied ' if done else '· PENDING'} {version}")
    lines.append("All applied." if pending == 0 else f"{pending} pending.")
    return "\n".join(lines)


def _cmd_status(args: argparse.Namespace) -> int:
    """List the migrations of the directory and which ones are applied in the DB (like migrate:status)."""
    migrations = load(_migrations_dir(args))
    if not migrations:
        print(f"There are no migrations for connection '{args.database}'.")
        return 0
    driver, dialect = _connection_for(args)
    try:
        runner = MigrationRunner(driver, dialect)
        runner.ensure_tracking_table()
        applied = runner.applied_versions()
    finally:
        driver.close()
    print(_format_status([migration.version for migration in migrations], applied))
    return 0


def _cmd_fresh(args: argparse.Namespace) -> int:
    """DROP ALL the tables of the models (+ tracking) and re-apply the migrations (migrate:fresh).

    To start from scratch in dev. DESTRUCTIVE: it deletes the data. Re-creating goes through the
    migrations, not through the model, so the DB ends up exactly as the history leaves it.
    """
    _prepare_models(args.models)
    migrations = load(_migrations_dir(args))
    driver, dialect = _connection_for(args)
    try:
        # The wipe is ASKED of the dialect, like every other piece of DDL. Writing
        # `DROP TABLE ... CASCADE` here made the one DESTRUCTIVE command Postgres-only: SQLite does
        # not parse the keyword and MySQL refuses to drop a referenced table, so on two engines out
        # of three it failed halfway through, which is the worst moment to learn about it.
        #
        # The tracking table goes in the same list: it is a table like the others, and leaving it
        # out left the history claiming migrations that no longer had a schema under them. It goes
        # LAST because nothing points at it, so it constrains nothing.
        names = _wipe_order(current_schema(database=args.database))
        for statement in dialect.drop_all_sql((*names, "snake_migrations")):
            driver.execute(statement, ())
        driver.commit()
        applied = MigrationRunner(driver, dialect).apply(migrations)
    finally:
        driver.close()
    print(f"Database recreated from scratch: {len(applied)} migration(s) applied.")
    return 0


def _wipe_order(tables: Sequence[SnakeTableInfo]) -> list[str]:
    """The table names for `drop_all_sql`, each holder of a foreign key before the table it points at.

    `drop_order` is the topological sort the diff already derives from the same foreign keys, so it
    is REUSED rather than written twice. DECLARATION order —what `current_schema()` returns, the
    order the `@snake_model` decorators ran— is not a drop order: a forward reference
    (`SnakeToOne["Parent"]`) is enough to invert it, and only SQLite says so
    (`FOREIGN KEY constraint failed`); Postgres's `CASCADE` and MySQL's session switch hide it.

    A CYCLE has no such order, so the tables come back unordered rather than not at all, which keeps
    the wipe working on all three engines. This is the only caller that may do that: a MIGRATION
    that cannot order its drops must stop and name the loop, because there the order is the whole
    guarantee.
    """
    try:
        ordered = drop_order(list(tables))
    except SnakeMigrationError:
        ordered = list(tables)
    return [table.name for table in ordered]


def _cmd_advise(args: argparse.Namespace) -> int:
    """STATIC audit of the schema: it lists the FKs without an index (the ones most filtered/joined).

    It is the dev half of the advisor (no DB, no queries): at scale, a correlated aggregate over an
    unindexed FK drags. The PER QUERY version, live, is what the debug panel gives.
    """
    _prepare_models(args.models)
    hints = unindexed_foreign_keys(current_schema(database=args.database))
    if not hints:
        print("No suggestions: every FK is indexed.")
        return 0
    print(f"{len(hints)} FK(s) without an index (worth indexing):")
    for table, column in hints:
        print(f"  {table}.{column}  ->  snake_column(index=True)")
    return 0


def _dsn_from_url_vars() -> str | None:
    """Return the full DSN defined by `DATABASE_URL`/`SNAKEORM_DSN`, or `None` if there is none."""
    for variable in ("DATABASE_URL", "SNAKEORM_DSN"):
        value = os.environ.get(variable)
        if value:
            return value
    return None


def _resolve_dsn(explicit: str | None, database: str = DEFAULT_DATABASE) -> str:
    """Resolve the DSN by priority: `--dsn`, then `DATABASE_URL`/`SNAKEORM_DSN` (environment and `.env`), then the `DB_*` pieces.

    If there is nothing, it raises `SnakeConfigError` enumerating the routes: it never falls back to
    a default DSN blindly.
    """
    if explicit:  # 1. the explicit argument has the highest priority
        return explicit
    if database != DEFAULT_DATABASE:
        # A named connection is declared separately: it cannot fall back to the devcontainer
        # defaults, or it would end up migrating the wrong database without saying a word.
        return dsn_for(database)
    from_env = _dsn_from_url_vars()  # 2. a full DSN from a real environment variable
    if from_env is not None:
        return from_env
    load_env()  # 3. load the .env (without stepping on what is already there)
    from_dotenv = _dsn_from_url_vars()  # DATABASE_URL/SNAKEORM_DSN defined in the .env
    if from_dotenv is not None:
        return from_dotenv
    if any(
        os.environ.get(key) for key in DB_ENV_KEYS
    ):  # the DB_* pieces (from the environment or from the .env)
        return dsn_from_env()
    raise SnakeConfigError(
        "Could not determine the database DSN. Provide it through one of these routes: "
        "(1) the --dsn <dsn> argument; "
        "(2) the DATABASE_URL or SNAKEORM_DSN environment variable; "
        "(3) the DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME variables (or a .env file with them)."
    )
