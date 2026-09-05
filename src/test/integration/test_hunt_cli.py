"""HUNT 6 — the CLI end to end, which is the surface the user touches.

The new commands and flags —`--database`, `--check`, `scaffold create/update`, `check`— were
built and tested from the inside. Nobody has run `main(argv)` with them. And the CLI is exactly
where things that live apart in the unit tests come together: DSN resolution, per-connection
directory, import of the models module and linking.

It skips gracefully if there is no Postgres.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import PostgresDialect, PsycopgDriver
from snakeorm.migration import MigrationRunner
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_MODULE = "examples.shop.models"
_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    """Runs the CLI as a PROCESS, which is what it is.

    Calling `main()` inside the test interpreter makes `makemigrations` walk the GLOBAL registry,
    where the suite has been registering throwaway models —some with a `lambda` as a factory,
    which the renderer rightly rejects—. That is contamination of the test bench, not a bug in the
    ORM: in a real application models are declared once.

    A clean process imports ONLY the models module it is asked for, which is exactly what a user
    does. And along the way the real entry point gets tested.
    """
    global _LAST_OUTPUT
    result = subprocess.run(  # noqa: S603
        ["uv", "run", "snakeorm", *argv],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        check=False,
    )
    _LAST_OUTPUT = result.stdout + result.stderr
    return result.returncode


_LAST_OUTPUT = ""


def output() -> str:
    """What the last call to the CLI printed."""
    return _LAST_OUTPUT


_TABLES = ("shop_orders", "shop_customers")


@pytest.fixture
def clean() -> Iterator[PsycopgDriver]:
    """Database with no trace of the store, before and after."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    def drop() -> None:
        for table in _TABLES:
            driver.execute(f"DROP TABLE IF EXISTS {table} CASCADE", ())
        driver.execute(
            "DELETE FROM snake_migrations WHERE version LIKE %s", ("%shop%",)
        )
        driver.commit()

    MigrationRunner(driver, PostgresDialect()).ensure_tracking_table()
    drop()
    try:
        yield driver
    finally:
        drop()
        driver.close()


def test_makemigrations_check_reports_pending_work(
    clean: PsycopgDriver, tmp_path: Path
) -> None:
    """`--check` is the CI gate: exit code != 0 when migrations are missing, and writing nothing."""
    target = tmp_path / "migrations"
    code = main(
        [
            "makemigrations",
            "--models",
            _MODULE,
            "--dir",
            str(target),
            "--name",
            "shop",
            "--check",
        ]
    )

    assert code != 0, "migrations are missing: the gate has to fail"
    assert "Missing migrations" in output()
    assert not target.exists(), "--check must NOT write the file"


def test_makemigrations_then_migrate_then_rollback(
    clean: PsycopgDriver, tmp_path: Path
) -> None:
    """The user cycle, run through the real CLI: generate, apply and undo."""
    target = tmp_path / "migrations"

    assert (
        main(
            [
                "makemigrations",
                "--models",
                _MODULE,
                "--dir",
                str(target),
                "--name",
                "shop",
            ]
        )
        == 0
    )
    assert list(target.glob("*.py")), "it must have written a migration"

    assert main(["migrate", "--models", _MODULE, "--dir", str(target)]) == 0
    existing = {
        str(row[0])
        for row in clean.fetch_all(
            "SELECT table_name FROM information_schema.tables WHERE table_name LIKE %s",
            ("shop_%",),
        )
    }
    assert {"shop_customers", "shop_orders"} <= existing

    assert main(["rollback", "--models", _MODULE, "--dir", str(target)]) == 0


def test_check_is_clean_right_after_migrating(
    clean: PsycopgDriver, tmp_path: Path
) -> None:
    """After migrating, `check` must see no drift: the code and the DB say the same thing."""
    target = tmp_path / "migrations"
    main(
        [
            "makemigrations",
            "--models",
            _MODULE,
            "--dir",
            str(target),
            "--name",
            "shop",
        ]
    )
    main(["migrate", "--models", _MODULE, "--dir", str(target)])

    code = main(["check", "--models", _MODULE])

    assert code == 0, f"there must be no drift right after migrating:\n{output()}"


def test_check_detects_a_column_added_by_hand(
    clean: PsycopgDriver, tmp_path: Path
) -> None:
    """THE REAL CASE of drift: someone does an ALTER by hand and nobody records it."""
    target = tmp_path / "migrations"
    main(
        [
            "makemigrations",
            "--models",
            _MODULE,
            "--dir",
            str(target),
            "--name",
            "shop",
        ]
    )
    main(["migrate", "--models", _MODULE, "--dir", str(target)])

    clean.execute("ALTER TABLE shop_customers ADD COLUMN parche TEXT", ())
    clean.commit()

    code = main(["check", "--models", _MODULE])

    assert code != 0
    assert "parche" in output()


def test_scaffold_create_refuses_to_overwrite(
    clean: PsycopgDriver, tmp_path: Path
) -> None:
    """`create` does not overwrite; `update` does. It is the only promise scaffolding makes about your files."""
    target = tmp_path / "migrations"
    main(
        [
            "makemigrations",
            "--models",
            _MODULE,
            "--dir",
            str(target),
            "--name",
            "shop",
        ]
    )
    main(["migrate", "--models", _MODULE, "--dir", str(target)])

    mirror = tmp_path / "mirror.py"
    assert main(["scaffold", "create", "--out", str(mirror)]) == 0
    assert mirror.exists()

    assert main(["scaffold", "create", "--out", str(mirror)]) != 0, (
        "create cannot overwrite"
    )
    assert "update" in output(), "and it has to say what the alternative is"

    assert main(["scaffold", "update", "--out", str(mirror)]) == 0


def test_the_scaffolded_mirror_is_importable_python(
    clean: PsycopgDriver, tmp_path: Path
) -> None:
    """What the CLI generates has to COMPILE: a mirror that does not import is worth nothing."""
    target = tmp_path / "migrations"
    main(
        [
            "makemigrations",
            "--models",
            _MODULE,
            "--dir",
            str(target),
            "--name",
            "shop",
        ]
    )
    main(["migrate", "--models", _MODULE, "--dir", str(target)])
    mirror = tmp_path / "mirror.py"
    main(["scaffold", "create", "--out", str(mirror)])

    compile(mirror.read_text(), str(mirror), "exec")


def test_an_unknown_database_fails_with_a_useful_message(tmp_path: Path) -> None:
    """A connection with no declared DSN must NOT fall back to the defaults: it would migrate the wrong DB."""
    code = main(
        [
            "migrate",
            "--models",
            _MODULE,
            "--dir",
            str(tmp_path / "migrations"),
            "--database",
            "inexistente",
        ]
    )
    assert code != 0
    assert "SNAKEORM_DSN_INEXISTENTE" in output(), (
        "the message has to say WHICH variable is missing"
    )
