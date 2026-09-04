"""Tests of the CLI's INSPECTION commands: `tables` (a list) and `table <name>` (the detail).

They read the models' metadata (with no DB), like Laravel's `db:show`/`db:table` but over the
compiled graph. The global registry is isolated per test so the CLI sees ONLY the test models.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from snakeorm.cli import main
from snakeorm.cli.app import _format_status
from snakeorm.registry import registry

_MODELS_SOURCE = """\
from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_str, snake_to_one

from snakeorm.model import SnakeModel


@snake_model(table="users")
class User(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    email: SnakeColumn[str] = snake_str(unique=True)


@snake_model(table="posts")
class Post(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    title: SnakeColumn[str] = snake_str()
    author_id: SnakeColumn[int] = snake_int()
    author: SnakeToOne[User] = snake_to_one(author_id)
"""


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the global registry: empty at the start, restored at the end (monkeypatch)."""
    monkeypatch.setattr(registry, "_tables", {})
    monkeypatch.setattr(registry, "_by_name", {})
    monkeypatch.setattr(registry, "_model_by_name", {})
    monkeypatch.setattr(registry, "_table_owner", {})


def _write_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str
) -> None:
    """Writes a models module into tmp_path and makes it importable by name."""
    (tmp_path / f"{module_name}.py").write_text(_MODELS_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))


def test_tables_lists_all_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`tables` lists ALL the registered tables (with their count)."""
    _write_models(tmp_path, monkeypatch, "cli_inspect_a")
    code = main(["tables", "--models", "cli_inspect_a"])
    out = capsys.readouterr().out
    assert code == 0
    assert "2 table(s)" in out
    assert "users" in out and "posts" in out


def test_tables_detail_shows_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`tables --detail` adds each table's columns."""
    _write_models(tmp_path, monkeypatch, "cli_inspect_b")
    code = main(["tables", "--models", "cli_inspect_b", "--detail"])
    out = capsys.readouterr().out
    assert code == 0
    assert "email" in out and "title" in out


def test_table_detail_shows_columns_and_relations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`table posts` shows that table's columns (with their type) and its relations."""
    _write_models(tmp_path, monkeypatch, "cli_inspect_c")
    code = main(["table", "posts", "--models", "cli_inspect_c"])
    out = capsys.readouterr().out
    assert code == 0
    assert "title" in out and "author_id" in out
    assert "author" in out  # the relation to User


def test_advise_suggests_unindexed_fk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`advise` suggests indexing the unindexed FK (`posts.author_id` in the test models)."""
    _write_models(tmp_path, monkeypatch, "cli_inspect_e")
    code = main(["advise", "--models", "cli_inspect_e"])
    out = capsys.readouterr().out
    assert code == 0
    assert "posts.author_id" in out
    assert "index=True" in out


def test_status_format_marks_applied_and_pending() -> None:
    """`_format_status` marks applied vs pending and counts the pending ones (pure, no DB)."""
    out = _format_status(["0001_a", "0002_b", "0003_c"], {"0001_a", "0002_b"})
    assert "applied" in out and "PENDING" in out
    assert "0003_c" in out
    assert "1 pending." in out


def test_tables_requires_models_or_from_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`tables` with no source and no application to discover fails, naming every route it tried.

    `--models` stopped being required the day the CLI learned to find the application's own entry
    point — the module whose import already registers the models and already holds the
    `SnakeOrmConfig` with the connection. What must NOT happen is falling back to something: with
    nothing to go on it says so, and it says WHERE it looked, the same way `_resolve_dsn` refuses to
    invent a DSN.

    `monkeypatch.chdir(tmp_path)` is the whole setup: an empty directory has no `manage.py`, no
    `main.py` and no `app.py`, so discovery has nothing to find.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SNAKEORM_CONFIG", raising=False)

    code = main(["tables"])
    out = capsys.readouterr().err

    assert code == 1
    assert "--config" in out and "SNAKEORM_CONFIG" in out and "entry point" in out, (
        f"the refusal must name the three routes it tried; it said: {out}"
    )


def test_table_unknown_name_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`table <nonexistent>` FAILS (exit code 1) and lists the available tables."""
    _write_models(tmp_path, monkeypatch, "cli_inspect_d")
    code = main(["table", "nope", "--models", "cli_inspect_d"])
    out = capsys.readouterr().err
    assert code == 1
    assert "nope" in out  # dice cuál pediste
    assert "users" in out and "posts" in out  # and the ones that do exist
