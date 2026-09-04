"""Integration tests for the CLI `migrate` and `rollback` against a REAL Postgres.

`makemigrations` does not touch the DB (that goes in `test_cli.py`); `migrate`/`rollback` do, so
here the REAL effect on the schema is checked: that the tables really are created/dropped (by
reading `information_schema`), that `migrate` is idempotent and that `rollback` undoes the last one
and cleans up its row in `snake_migrations`.

The CLI is invoked by calling its `main(argv)` function in process (not through `subprocess`)
because:
- it allows reusing the isolation of the global registry via `monkeypatch` (a subprocess would not
  see the patched dicts and would drag in the models of the WHOLE suite);
- it lets the output be captured with `capsys` and the SAME DB be queried in the same process;
- it gives a deterministic test, without depending on the `snakeorm` script being on the PATH.

The registry is a global singleton: `@snake_model` always registers there, so it is isolated with
`monkeypatch` over its internal dicts (same as in `test_cli.py`). The tables and the
`snake_migrations` rows are cleaned before and after each test so as not to contaminate the others.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.cli import main
from snakeorm.registry import registry
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

# UNIQUE names for this module so as not to clash with other tests in the suite.
_AUTHORS = "cli_mig_authors"
_BOOKS = "cli_mig_books"
_VERSION_TOKEN = "climig"  # the `--name` carries this token so its rows can be cleaned

_MODELS_SOURCE = f'''\
from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_str, snake_to_one

from snakeorm.model import SnakeModel


@snake_model(table="{_AUTHORS}")
class Author(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="{_BOOKS}")
class Book(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    title: SnakeColumn[str] = snake_str()
    author_id: SnakeColumn[int] = snake_int()
    author: SnakeToOne[Author] = snake_to_one(author_id)
'''


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the global registry: empty at the start, restored at the end (monkeypatch)."""
    monkeypatch.setattr(registry, "_tables", {})
    monkeypatch.setattr(registry, "_by_name", {})
    monkeypatch.setattr(registry, "_model_by_name", {})
    monkeypatch.setattr(registry, "_table_owner", {})


def _scalar(cursor: psycopg2.extensions.cursor) -> object:
    """First value of the cursor's single row (with a guard for mypy and for an empty result)."""
    row = cursor.fetchone()
    assert row is not None  # SELECT COUNT(*)/to_regclass always returns one row
    return row[0]


def _reset_database(connection: psycopg2.extensions.connection) -> None:
    """Drops the test tables and the `snake_migrations` rows of this module."""
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {_BOOKS}, {_AUTHORS} CASCADE")
        cursor.execute("SELECT to_regclass('public.snake_migrations')")
        if _scalar(cursor) is not None:
            cursor.execute(
                "DELETE FROM snake_migrations WHERE version LIKE %s",
                (f"%{_VERSION_TOKEN}%",),
            )


@pytest.fixture
def connection() -> Iterator[psycopg2.extensions.connection]:
    """Connection to the real Postgres (autocommit) with schema cleanup before and after."""
    try:
        conn = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    conn.autocommit = True
    _reset_database(conn)
    try:
        yield conn
    finally:
        _reset_database(conn)
        conn.close()


def _write_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str
) -> None:
    """Writes the models module into tmp_path and makes it importable by name."""
    (tmp_path / f"{module_name}.py").write_text(_MODELS_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))


def _table_exists(connection: psycopg2.extensions.connection, table: str) -> bool:
    """Queries `information_schema.tables`: does the table exist in the public schema?"""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return _scalar(cursor) == 1


def _columns_of(connection: psycopg2.extensions.connection, table: str) -> set[str]:
    """The column names of a table according to `information_schema.columns`."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}


def _foreign_keys_of(connection: psycopg2.extensions.connection, table: str) -> int:
    """The number of FOREIGN KEY constraints of a table (to prove snake_link resolved)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = %s "
            "AND constraint_type = 'FOREIGN KEY'",
            (table,),
        )
        return cast("int", _scalar(cursor))


def _applied_versions(connection: psycopg2.extensions.connection) -> set[str]:
    """The versions recorded in `snake_migrations` for this module."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT version FROM snake_migrations WHERE version LIKE %s",
            (f"%{_VERSION_TOKEN}%",),
        )
        return {row[0] for row in cursor.fetchall()}


def test_migrate_creates_real_tables_and_fk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    connection: psycopg2.extensions.connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """migrate creates the REAL tables (with their columns) and the FK snake_link resolved."""
    _write_models(tmp_path, monkeypatch, "cli_mig_create")
    mig_dir = tmp_path / "migrations"

    assert (
        main(
            [
                "makemigrations",
                "--models",
                "cli_mig_create",
                "--dir",
                str(mig_dir),
                "--name",
                _VERSION_TOKEN,
            ]
        )
        == 0
    )
    # The migration includes the FK: if the CLI did not call snake_link(), there would be no AddForeignKey.
    migration_file = mig_dir / f"0001_{_VERSION_TOKEN}.py"
    assert "AddForeignKey(" in migration_file.read_text()
    capsys.readouterr()

    code = main(
        ["migrate", "--models", "cli_mig_create", "--dir", str(mig_dir), "--dsn", dsn()]
    )

    assert code == 0
    assert "Applied 1 migration(s)" in capsys.readouterr().out
    assert _table_exists(connection, _AUTHORS)
    assert _table_exists(connection, _BOOKS)
    assert _columns_of(connection, _AUTHORS) == {"id", "name"}
    assert _columns_of(connection, _BOOKS) == {"id", "title", "author_id"}
    assert _foreign_keys_of(connection, _BOOKS) == 1  # snake_link resolved Book.author


def test_migrate_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    connection: psycopg2.extensions.connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A second pass of migrate reapplies nothing and says so: idempotence."""
    _write_models(tmp_path, monkeypatch, "cli_mig_idem")
    mig_dir = tmp_path / "migrations"
    main(
        [
            "makemigrations",
            "--models",
            "cli_mig_idem",
            "--dir",
            str(mig_dir),
            "--name",
            _VERSION_TOKEN,
        ]
    )
    main(["migrate", "--models", "cli_mig_idem", "--dir", str(mig_dir), "--dsn", dsn()])
    capsys.readouterr()  # discards the output of the first application

    code = main(
        ["migrate", "--models", "cli_mig_idem", "--dir", str(mig_dir), "--dsn", dsn()]
    )

    assert code == 0
    assert "All up to date" in capsys.readouterr().out
    assert _applied_versions(connection) == {
        f"0001_{_VERSION_TOKEN}"
    }  # there is still ONE row


def test_rollback_drops_tables_and_unrecords(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    connection: psycopg2.extensions.connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """rollback undoes the last applied one: the tables disappear and its row is deleted."""
    _write_models(tmp_path, monkeypatch, "cli_mig_rollback")
    mig_dir = tmp_path / "migrations"
    main(
        [
            "makemigrations",
            "--models",
            "cli_mig_rollback",
            "--dir",
            str(mig_dir),
            "--name",
            _VERSION_TOKEN,
        ]
    )
    main(
        [
            "migrate",
            "--models",
            "cli_mig_rollback",
            "--dir",
            str(mig_dir),
            "--dsn",
            dsn(),
        ]
    )
    assert _table_exists(
        connection, _BOOKS
    )  # precondition: it exists before the rollback
    capsys.readouterr()

    code = main(
        [
            "rollback",
            "--models",
            "cli_mig_rollback",
            "--dir",
            str(mig_dir),
            "--dsn",
            dsn(),
        ]
    )

    assert code == 0
    assert f"Rolled back migration 0001_{_VERSION_TOKEN}" in capsys.readouterr().out
    assert not _table_exists(connection, _BOOKS)
    assert not _table_exists(connection, _AUTHORS)
    assert _applied_versions(connection) == set()  # no record of the version is left


def test_full_cycle_make_migrate_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    connection: psycopg2.extensions.connection,
) -> None:
    """The full makemigrations → migrate → rollback cycle leaves the schema as it started."""
    _write_models(tmp_path, monkeypatch, "cli_mig_cycle")
    mig_dir = tmp_path / "migrations"

    assert not _table_exists(connection, _BOOKS)
    assert (
        main(
            [
                "makemigrations",
                "--models",
                "cli_mig_cycle",
                "--dir",
                str(mig_dir),
                "--name",
                _VERSION_TOKEN,
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "migrate",
                "--models",
                "cli_mig_cycle",
                "--dir",
                str(mig_dir),
                "--dsn",
                dsn(),
            ]
        )
        == 0
    )
    assert _table_exists(connection, _BOOKS)
    assert (
        main(
            [
                "rollback",
                "--models",
                "cli_mig_cycle",
                "--dir",
                str(mig_dir),
                "--dsn",
                dsn(),
            ]
        )
        == 0
    )
    assert not _table_exists(connection, _BOOKS)
    assert not _table_exists(connection, _AUTHORS)
