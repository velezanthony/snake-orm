"""The CLI against the THREE engines: it connects, it reads, and it names the connection it used.

The CLI was exercised end to end on Postgres. It is the surface a user actually touches and the
place where things that live apart in the unit tests come together — DSN resolution, the
per-connection directory, importing the models module and linking — so "it works" is a claim about
one engine unless it is asked of three.

The DSN travels in the SUBPROCESS's environment and never through `os.environ`. That is not
fastidiousness: `conftest.py` has an autouse guard asserting no test leaves the connection variables
changed, and a test that mutates them to check a CLI would be fighting the net that exists to catch
exactly that mistake.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from test import session_db

from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON
from test.scenarios.db import dsn
from test.scenarios.engines import mysql_kwargs

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
"""Giving a command its own source —`--from-db` here, `--dir` for `status`— is what puts the CLI on
the ENVIRONMENT VARIABLE route for a named connection. Without one it falls into config discovery,
a config file or an application entry point, and answers that it found none: a correct message about
a different question."""
_ENGINES = ["postgres", "mysql", "sqlite"]


def _dsn_for(engine: str, tmp_path: Path) -> str:
    """The connection string of each engine, in the one spelling the CLI reads."""
    if engine == "sqlite":
        # FOUR slashes: the third is the URL's separator, so an absolute path takes the fourth.
        return f"sqlite:///{tmp_path / 'cli.db'}"
    if engine == "mysql":
        kwargs = mysql_kwargs()
        return (
            f"mysql://{kwargs['user']}:{kwargs['password']}"
            f"@{kwargs['host']}:{kwargs['port']}/{kwargs['database']}"
        )
    return dsn()


def _run(argv: list[str], engine: str, tmp_path: Path) -> tuple[int, str]:
    """Runs the CLI as the PROCESS it is, with this engine's DSN in its own environment.

    The caller passes the command's OWN flags: they are not the same from one command to the next
    (`tables` takes no `--dir`, `status` takes no `--models`), and pretending otherwise turns a
    connection test into an argparse test.
    """
    environment = dict(os.environ)
    environment["SNAKEORM_DSN_CLIPROBE"] = _dsn_for(engine, tmp_path)
    result = subprocess.run(  # noqa: S603
        ["uv", "run", "snakeorm", *argv, "--database", "cliprobe"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env=environment,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def _demand_a_server(engine: str) -> None:
    """Skip unless the engine is REACHABLE, driver and server both.

    `importorskip` alone asks a different question: the driver can be installed with nothing
    listening, which is exactly what CI's sqlite leg arranges.
    """
    if engine == "postgres":
        pytest.importorskip("psycopg2", reason=NO_SERVER_REASON)
        connection = session_db.postgres_connection("postgres")
        if connection is None:
            pytest.skip(NO_SERVER_REASON)
        connection.close()
    if engine == "mysql":
        pytest.importorskip("pymysql", reason=NO_MYSQL_REASON)


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_cli_reaches_every_engine(engine: str, tmp_path: Path) -> None:
    """`tables --from-db` needs a live connection, so reaching the engine IS the assertion.

    A command that answers without connecting would prove nothing about the DSN, which is the piece
    this test exists for — the CLI is where the connection string stops being a string.
    """
    _demand_a_server(engine)

    code, printed = _run(["tables", "--from-db"], engine, tmp_path)

    assert code == 0, f"{engine}: the CLI failed to reach the database:\n{printed}"


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_command_that_needs_migrations_names_the_connection(
    engine: str, tmp_path: Path
) -> None:
    """`status` over an empty directory still has to CONNECT, and answer.

    The commands resolve the DSN before looking at the directory, so an unreachable engine fails
    here rather than answering "there are no migrations" — a sentence that is correct and useless.
    """
    _demand_a_server(engine)

    code, printed = _run(
        ["status", "--dir", str(tmp_path / "migrations")], engine, tmp_path
    )

    assert code == 0, f"{engine}: `status` failed:\n{printed}"
    assert printed.strip(), f"{engine}: `status` printed nothing at all"
