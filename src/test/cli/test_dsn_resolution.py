"""Tests of DSN resolution in the CLI (unit tests, WITHOUT connecting to Postgres).

They verify the ORDER of precedence `_resolve_dsn` follows:

1. An explicit `--dsn` (highest priority).
2. `DATABASE_URL` / `SNAKEORM_DSN` from the environment (a complete DSN, taken as it is).
3. Loading `.env` (without trampling what is already there) and building the DSN from `DB_*`.

And that, when NO route is available, a clear error naming all three is raised. Everything with
`monkeypatch` over `os.environ` and over the cwd: no real connection is ever opened.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from snakeorm.cli.app import _resolve_dsn
from snakeorm.core.config import DB_ENV_KEYS
from snakeorm.core.exceptions import SnakeConfigError

_URL_KEYS = ("DATABASE_URL", "SNAKEORM_DSN")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DSN variable to start with, and the environment PUT BACK exactly as it was afterwards.

    Everything goes through `monkeypatch`, and it has to: a snapshot of my own restoring alongside
    it produced two undo stacks fighting each other, where whichever ran last won and the key ended
    up wrong either way.

    The `setenv` before the `delenv` is the load-bearing line, and it looks pointless. It is not:
    `monkeypatch.delenv(key, raising=False)` on a key that is ABSENT records NOTHING to restore, so
    when the code under test calls `load_env()` — which writes into `os.environ`, that being its
    job — the values it wrote stay in the process for the rest of the session. Setting the key first
    forces monkeypatch to record the original state, present or absent, and its undo then puts back
    exactly that no matter what was written in between.

    Measured before the fix: this module left `DB_HOST='host_del_env'` and `DB_NAME='bd_del_env'`
    behind, so `test_e2e_postgres.py` passed on its own and SKIPPED when this file ran first.
    Thirteen tests against a real server went green by absence, saved only by alphabetical order.
    The net in `test/conftest.py` now fails the test that leaks instead of the ones that follow.
    """
    for key in (*_URL_KEYS, *DB_ENV_KEYS):
        monkeypatch.setenv(key, os.environ.get(key, ""))
        monkeypatch.delenv(key, raising=False)


def test_explicit_dsn_wins_over_environment(
    monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    """An explicit `--dsn` wins outright: it beats a DATABASE_URL defined in the environment."""
    monkeypatch.setenv("DATABASE_URL", "host=fromenv dbname=env")
    assert _resolve_dsn("host=explicit dbname=cli") == "host=explicit dbname=cli"


def test_database_url_is_read_from_environment(
    monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_path: Path
) -> None:
    """With no `--dsn`, the environment's `DATABASE_URL` (route 2) is used as is, leaving DB_* alone."""
    monkeypatch.chdir(
        tmp_path
    )  # a tmp with no .env: isolates from any .env in the real tree
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    assert _resolve_dsn(None) == "postgresql://u:p@h/db"


def test_snakeorm_dsn_is_read_from_environment(
    monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_path: Path
) -> None:
    """`SNAKEORM_DSN` also works as a complete DSN (route 2)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SNAKEORM_DSN", "host=snk dbname=snk")
    assert _resolve_dsn(None) == "host=snk dbname=snk"


def test_dsn_built_from_db_vars_with_defaults(
    monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_path: Path
) -> None:
    """With no complete DSN, it is built from `DB_*`, filling the rest in with the defaults."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_NAME", "produccion")
    dsn = _resolve_dsn(None)
    assert "host=db.example" in dsn
    assert "dbname=produccion" in dsn
    assert "port=5432" in dsn  # default preservado
    assert "user=postgres" in dsn  # default preservado


def test_dsn_loaded_from_dotenv_file(
    monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_path: Path
) -> None:
    """A `.env` in the working directory feeds the `DB_*` (load_dotenv anchored to the cwd)."""
    (tmp_path / ".env").write_text("DB_HOST=host_del_env\nDB_NAME=bd_del_env\n")
    monkeypatch.chdir(tmp_path)
    dsn = _resolve_dsn(None)
    assert "host=host_del_env" in dsn
    assert "dbname=bd_del_env" in dsn


def test_environment_wins_over_dotenv_file(
    monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_path: Path
) -> None:
    """`load_dotenv` does NOT trample what is there: a real `DB_HOST` beats the `.env`'s."""
    (tmp_path / ".env").write_text("DB_HOST=host_del_env\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_HOST", "host_real")
    dsn = _resolve_dsn(None)
    assert "host=host_real" in dsn
    assert "host_del_env" not in dsn


def test_no_configuration_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_path: Path
) -> None:
    """No `--dsn`, no variables and no `.env`: a clear error naming all three routes."""
    monkeypatch.chdir(tmp_path)  # an empty tmp: there is no .env
    with pytest.raises(SnakeConfigError) as excinfo:
        _resolve_dsn(None)
    message = str(excinfo.value)
    assert "--dsn" in message
    assert "DATABASE_URL" in message
    assert "DB_HOST" in message
