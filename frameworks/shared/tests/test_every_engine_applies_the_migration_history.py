"""The history is APPLIED, by a real server, on each of the three engines. Not inspected — applied.

WHY THIS EXISTS BESIDE ITS SIBLING. `test_every_engine_accepts_the_migration_plans.py` asks `realize`
whether the SHAPE of a plan is something an engine knows how to perform, and it says out loud in its
own docstring what that can never reach: the SQL an operation CARRIES. A `CreateView` whose
`view_definition` was frozen as `FROM "public"."warehouse_stock"` is a perfectly shaped plan that
SQLite then refuses at the server — «view "low_stock" cannot reference objects in database public» —
and MySQL stopped at `orders/0001` with `1071, Specified key was too long` for a reason no static
check reaches either: the width a type mapping gives a column.

Both were found by hand, once, by somebody who ran the thing. That is the gap this file closes: it
runs the thing, every time.

WHAT IT DOES. Per engine it empties the database and applies the WHOLE history the way the demos do
at boot — `dependency_order` over `apps/*/migrations`, then `MigrationRunner.apply` — one migration
at a time, and records WHERE it stops. Not a sample and not a plan rebuilt some other way: the same
two calls `SnakeOrmConfig.migrate()` makes, so a green here means `DB_BACKEND=<engine>` brings the
demo up.

ONE STOP PER ENGINE, AND THAT IS THE HONEST SHAPE. A server cannot be asked what it would have done
after a migration it refused: everything downstream references tables that were never created. So
this file declares the FIRST stop per engine and nothing more. When one is fixed the test goes red
naming the NEXT one, which is the behaviour worth having — the sibling, which needs no server, is
where the full list of refusals lives.

WHAT IT CANNOT DO, as plainly as its sibling says its own limit. Two of the three need a SERVER, and
without docker those two SKIP — which is how a suite reports success over nothing. The repository
already has the answer and this file uses it: the Postgres skip carries the phrase the whole repo
announces a missing server with, so `conftest`'s existing hook turns it into a failure under
`SNAKEORM_REQUIRE_POSTGRES`, and the MySQL half reads `SNAKEORM_REQUIRE_MYSQL` itself with the same
spellings. SQLite needs nothing and never skips.

ONE HISTORY, THREE DEMOS, ONE RUN. The twenty files live once, in `shared/migrations/`, and each
demo's `apps/<domain>/migrations` is a symlink to them — held by the sibling's
`test_the_three_demos_share_one_history_on_disk`. So walking one demo walks all three, and this file
does not pay for the same twenty migrations three times over.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from collections.abc import Iterator

import pytest
from snakeorm import snake_table
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers import SnakeDriver
from snakeorm.migration import Migration, MigrationRunner, dependency_order, load

from shared.config import (
    _ensure_mysql_database,
    _ensure_pg_database,
    _mysql_params,
    _pg_dbname,
    _pg_params,
    drop_pg_database,
)
from shared.models import MODELS, VIEWS
from shared.session import current as current_session
from shared.tests.conftest import NO_SERVER_REASON

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The demo whose symlinks are followed. Any of the three reaches the same twenty files.
_DEMO = "flask"

_ENGINES = ("postgres", "mysql", "sqlite")

_NO_MYSQL_REASON = "MySQL is not reachable"
"""The MySQL half of the skip phrase, deliberately NOT the Postgres one.

`conftest` turns any skip carrying `NO_SERVER_REASON` into a failure under
`SNAKEORM_REQUIRE_POSTGRES`. Reusing that phrase here would make a missing MySQL fail a gate that
speaks about Postgres — a red that names the wrong service, which is the worst kind of red.
"""

# WHERE AN ENGINE STOPS TODAY, keyed `<engine>/<app>/<version>` and holding the reason. A declaration
# and not a skip list: each entry is an engine the demos do NOT come up on, and the test fails in
# BOTH directions — a stop that is not declared, and a declared stop that has stopped happening.
#
# NO ENTRY EVER CLOSES BY EDITING THIS FILE, and that is still the rule even though the dictionary is
# now empty. The MySQL one closed in `src/snakeorm/`; the SQLite one took BOTH — a new operation in
# `src/snakeorm/` and then the two migrations rewritten to use it in `frameworks/`. What never counts
# is deleting a line here.
#
# MYSQL WAS HERE AND IS NOT ANY MORE, and how it left is the argument of this whole file. Its entry
# said `orders/0001` died with `1071, Specified key was too long` because a `snake_enum` column
# reached the dialect as a bare `str` and MySQL answered TEXT. It was fixed by deriving the width
# from `enum_type` the way the base type already was — and this net SANG it on its own, in the
# direction nobody remembers to guard: «what is declared as stopping it now goes through». A
# declaration that has stopped being true is the wrong map for whoever reads it next.
#
# SQLITE WAS HERE TOO AND IS NOT ANY MORE, and its exit is worth writing down because the entry
# reasoned correctly about a world that has since changed. It said `inventory/0004` died on
# `Cap.ADD_CONSTRAINT` and that the portable way out was NOT available: rebuilding `warehouse_stock`
# would first have to remove the foreign key `stock_movements` holds into it, and `DropForeignKey`
# falls under the SAME capability. `RebuildTable` opened that door — the rebuild is now an operation
# WRITTEN IN THE FILE which defers the keys and recreates the whole table in one piece, so nobody has
# to take the other table's key out. `inventory/0004` and `taxonomy/0004` — the second one being the
# same closed door a domain over — are rewritten with it, and all three engines apply the twenty.
#
# THE DICTIONARY IS EMPTY AND THAT DOES NOT SWITCH IT OFF. With no entries the first of the two
# assertions below comes to read "no engine stops anywhere", which is exactly what this file exists
# to watch; the second stays trivially true until somebody declares a stop again.
_STOPS: dict[str, str] = {}


def _history() -> list[Migration]:
    """The twenty migrations in the order a demo's boot would apply them.

    Found by walking `apps/*/migrations` and ordered by FK dependency — the two calls
    `SnakeOrmConfig.migrate()` makes. A plan rebuilt any other way would measure a shape the demos
    never apply.
    """
    found: list[Migration] = []
    for directory in sorted((_ROOT / _DEMO / "apps").glob("*/migrations")):
        found.extend(load(str(directory)))
    return dependency_order(found)


def _app_of(version: str) -> str:
    """Which domain a version belongs to, for the `<engine>/<app>/<version>` key."""
    for directory in sorted((_ROOT / _DEMO / "apps").glob("*/migrations")):
        if any(path.stem == version for path in directory.glob("*.py")):
            return directory.parent.name
    return "?"


def _strict(engine: str) -> bool:
    """Whether a missing server for this engine must FAIL instead of skipping.

    Same contract and the same one-spelling-per-side the rest of the repository uses:
    `SNAKEORM_REQUIRE_POSTGRES` / `SNAKEORM_REQUIRE_MYSQL`, `true` or `false`.
    """
    return (
        os.environ.get(f"SNAKEORM_REQUIRE_{engine.upper()}", "false").strip().lower()
        == "true"
    )


def _connection(engine: str, directory: pathlib.Path) -> SnakeConnectionConfig:
    """The connection to a database of THIS FILE's own, on `engine`.

    It goes through `SnakeConnectionConfig` for the reason `shared/config.py` writes down at length:
    driver and dialect come out of it PAIRED, so nothing here can put a SQLite driver together with
    a Postgres dialect. The name is `history_*` and carries the run's session id, so this test never
    lands on the database a demo is serving from.
    """
    if engine == "sqlite":
        return SnakeConnectionConfig(
            backend=SnakeBackend.SQLITE, name=str(directory / "history.sqlite")
        )
    if engine == "postgres":
        name = _pg_dbname("history")
        _ensure_pg_database(name)
        return SnakeConnectionConfig(
            backend=SnakeBackend.POSTGRES, name=name, **_pg_params()
        )
    name = _pg_dbname("history")
    _ensure_mysql_database(name)
    return SnakeConnectionConfig(
        backend=SnakeBackend.MYSQL, name=name, **_mysql_params()
    )


def _discard(engine: str, name: str) -> None:
    """Removes the database this run created on `engine`. Silent when there is no server left.

    NOTHING IS DROPPED OUTSIDE A SESSION, the same guard `shared/config.close_session` states: with
    no session id the name is a real database somebody may be serving from, and dropping it because
    a test finished would be a far worse bug than the leak this prevents.

    A run that finishes normally cleans up after itself. Measured on the sibling suites before this
    was written: three runs left three abandoned databases standing, because nothing between them
    ever swept.
    """
    if current_session() is None:
        return
    if engine == "postgres":
        drop_pg_database(name)
        return
    import pymysql

    params = _mysql_params()
    try:
        connection = pymysql.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            password=params["password"],
        )
    except pymysql.err.OperationalError:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
        connection.commit()
    finally:
        connection.close()


def _empty(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Empties the database: every view, every table and the migration tracking.

    The tracking goes too, and that is the half that matters. Without it a second run finds every
    version already recorded, applies NOTHING and passes — the exact shape of a green that proves
    nothing.
    """
    for view in VIEWS:
        driver.execute(
            f"DROP VIEW IF EXISTS {dialect.quote_ident(snake_table(view).name)}", ()
        )
    for model in reversed(MODELS):
        driver.execute(
            f"DROP TABLE IF EXISTS {dialect.quote_ident(snake_table(model).name)}", ()
        )
    driver.execute("DROP TABLE IF EXISTS snake_migrations", ())
    driver.commit()


@pytest.fixture(params=_ENGINES)
def engine_runner(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[str, MigrationRunner]]:
    """A runner over an EMPTY database of the parametrised engine, or a skip when no server answers.

    Empty is the point: the demos drop everything and migrate from zero at boot, so a runner over a
    database that already carries the schema would be measuring "already applied" and reporting a
    green that never touched a server.
    """
    engine = str(request.param)
    with tempfile.TemporaryDirectory() as temporary:
        try:
            driver, dialect = _connection(
                engine, pathlib.Path(temporary)
            ).driver_and_dialect()
        except Exception as error:  # noqa: BLE001 - every driver spells "cannot connect" its own way
            if _strict(engine):
                pytest.fail(
                    f"SNAKEORM_REQUIRE_{engine.upper()}=true and no server answered: {error}"
                )
            reason = NO_SERVER_REASON if engine == "postgres" else _NO_MYSQL_REASON
            pytest.skip(f"{reason}: {error}")
        try:
            _empty(driver, dialect)
            yield engine, MigrationRunner(driver, dialect)
        finally:
            driver.close()
            if engine != "sqlite":
                _discard(engine, _pg_dbname("history"))


def test_the_history_has_something_in_it() -> None:
    """Every migration was found, before anything below claims an engine applied them.

    The trap of every test that discovers files: if the glob stops matching, "no engine stopped
    anywhere" holds over an empty history and the guard turns into decoration. It is an EQUALITY and
    not a floor because the count is a fact about this repository — twenty-one files over ten
    domains — and a floor would let half of them vanish quietly.
    """
    history = _history()

    assert len(history) == 21, [migration.version for migration in history]


def test_the_engine_applies_the_whole_history(
    engine_runner: tuple[str, MigrationRunner],
) -> None:
    """The server takes every migration, except at the one place this file declares it stops.

    Both directions in one test because they are one fact: an undeclared stop is a demo that does not
    come up with `DB_BACKEND=<engine>`, and a declared stop that no longer happens is an excuse
    outliving its reason. They are applied ONE AT A TIME so the message can name the migration —
    `apply` over the whole list reports only the failure's own words, and WHICH FILE it was is the
    half somebody fixing it needs.
    """
    engine, runner = engine_runner
    declared = {key for key in _STOPS if key.startswith(f"{engine}/")}
    stopped: dict[str, str] = {}

    for migration in _history():
        try:
            runner.apply([migration])
        except Exception as error:  # noqa: BLE001 - the engine's own words are the point
            cause: BaseException = error
            while cause.__cause__ is not None:
                cause = cause.__cause__
            key = f"{engine}/{_app_of(migration.version)}/{migration.version}"
            stopped[key] = f"{type(cause).__name__}: {cause}"
            break

    unexpected = sorted(set(stopped) - declared)
    healed = sorted(declared - set(stopped))

    assert unexpected == [], (
        f"{engine} refuses a migration nobody declared, so the demos do not come up with "
        f"`DB_BACKEND={engine}`: "
        + "; ".join(f"{key} — {stopped[key]}" for key in unexpected)
    )
    assert healed == [], (
        f"{engine} now gets past what is declared as stopping it: {healed}. Strike it off — a "
        f"declaration that has stopped being true is the next reader's wrong map. If the history "
        f"stops somewhere LATER, that place is the new entry."
    )
