"""Tests for the CLI `makemigrations` command (no DB, with tmp_path).

Checks that over a models module it writes the expected migration file, and that a second
pass with no changes writes nothing. The global registry is isolated per test (monkeypatch)
so the CLI sees ONLY the models of the test module, not those of the whole suite.

`migrate`/`rollback` are not tested here because they need a real Postgres (they go in integration).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from snakeorm.cli import main
from snakeorm.registry import registry

_MODELS_SOURCE = """\
from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel


@snake_model(table="gadgets")
class Gadget(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
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


def test_makemigrations_writes_expected_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """makemigrations over a new model writes 0001_<slug>.py with a CreateTable."""
    _write_models(tmp_path, monkeypatch, "cli_models_alpha")
    mig_dir = tmp_path / "migrations"

    code = main(
        [
            "makemigrations",
            "--models",
            "cli_models_alpha",
            "--dir",
            str(mig_dir),
            "--name",
            "initial",
        ]
    )

    assert code == 0
    written = mig_dir / "0001_initial.py"
    assert written.exists()
    content = written.read_text()
    assert "CreateTable(" in content
    assert "gadgets" in content
    assert "migration = Migration(" in content
    assert "Created migration" in capsys.readouterr().out


def test_makemigrations_no_changes_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After capturing the schema, a second pass finds no changes and writes no file."""
    _write_models(tmp_path, monkeypatch, "cli_models_beta")
    mig_dir = tmp_path / "migrations"

    # First pass: creates 0001.
    main(
        [
            "makemigrations",
            "--models",
            "cli_models_beta",
            "--dir",
            str(mig_dir),
            "--name",
            "initial",
        ]
    )
    capsys.readouterr()  # discards the output of the first pass

    # Second pass: the history already covers the current schema.
    code = main(
        [
            "makemigrations",
            "--models",
            "cli_models_beta",
            "--dir",
            str(mig_dir),
            "--name",
            "more",
        ]
    )

    assert code == 0
    assert not (mig_dir / "0002_more.py").exists()
    assert (
        "No changes: the schema is already up to date with the history."
        in capsys.readouterr().out
    )


def test_generated_migration_is_loadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
) -> None:
    """The file makemigrations writes is loadable by the loader (round trip to disk)."""
    from snakeorm.migration.loader import load

    _write_models(tmp_path, monkeypatch, "cli_models_gamma")
    mig_dir = tmp_path / "migrations"
    main(
        [
            "makemigrations",
            "--models",
            "cli_models_gamma",
            "--dir",
            str(mig_dir),
            "--name",
            "initial",
        ]
    )

    migrations = load(mig_dir)
    assert [m.version for m in migrations] == ["0001_initial"]


# --- The warning a destructive migration under a standing view gets -------------------------
#
# The knowledge used to live in a `views=` payload on `RebuildTable` with a guard demanding EVERY
# standing view — which made one app's rebuild answer for another app's view. That went away: the
# ORM cannot know which tables a view reads. What is left is that the failure would only surface
# during the DEPLOY, so it is said HERE instead, at the one moment there is a person reading.
# `standing_view_warning` is unit-tested in `src/test/migration/`; what this file owes is the wiring.

_TABLE_AND_VIEW_SOURCE = """\
from __future__ import annotations

from snakeorm.decorators import snake_model, snake_view
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel, SnakeView


@snake_model(table="widgets")
class Widget(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_view(sql='SELECT "id", "name" FROM "widgets"', name="widget_names")
class WidgetName(SnakeView):
    id: SnakeColumn[int] = snake_int()
    name: SnakeColumn[str] = snake_str()
"""

_VIEW_ONLY_SOURCE = """\
from __future__ import annotations

from snakeorm.decorators import snake_view
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeView


@snake_view(sql='SELECT "id", "name" FROM "widgets"', name="widget_names")
class WidgetName(SnakeView):
    id: SnakeColumn[int] = snake_int()
    name: SnakeColumn[str] = snake_str()
"""


def _reset_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empties the global registry again, so a SECOND models module starts from nothing."""
    monkeypatch.setattr(registry, "_tables", {})
    monkeypatch.setattr(registry, "_by_name", {})
    monkeypatch.setattr(registry, "_model_by_name", {})
    monkeypatch.setattr(registry, "_table_owner", {})


def test_makemigrations_warns_when_a_destructive_plan_meets_standing_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The warning REACHES the command: a DropTable with a view standing raises a SnakeWarning.

    Wiring, not content. `standing_view_warning` could be perfect and never be called, and then the
    person generating the migration learns about the dangling view during the deploy — which is the
    exact thing this warning exists to move earlier.
    """
    import warnings

    from snakeorm.core.exceptions import SnakeWarning

    (tmp_path / "cli_view_alpha.py").write_text(_TABLE_AND_VIEW_SOURCE)
    (tmp_path / "cli_view_beta.py").write_text(_VIEW_ONLY_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    mig_dir = tmp_path / "migrations"

    main(
        [
            "makemigrations",
            "--models",
            "cli_view_alpha",
            "--dir",
            str(mig_dir),
            "--name",
            "initial",
        ]
    )
    capsys.readouterr()

    # The table model is gone from the second module, so the diff wants to DROP the table while the
    # view stays declared: destruction with a view standing, which is the pair that warns.
    _reset_registry(monkeypatch)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        code = main(
            [
                "makemigrations",
                "--models",
                "cli_view_beta",
                "--dir",
                str(mig_dir),
                "--name",
                "drop_widgets",
            ]
        )

    assert code == 0
    raised = [w for w in caught if issubclass(w.category, SnakeWarning)]
    assert len(raised) == 1, [str(w.message) for w in caught]
    message = str(raised[0].message)
    assert "widgets" in message
    assert "widget_names" in message


def test_makemigrations_stays_quiet_when_nothing_is_destroyed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The first pass — CreateTable plus CreateView — warns about NOTHING, views and all.

    The double condition is what keeps the warning readable, and the command is where it would be
    lost first: a message printed on every single `makemigrations` is a message people stop seeing.
    """
    import warnings

    from snakeorm.core.exceptions import SnakeWarning

    (tmp_path / "cli_view_quiet.py").write_text(_TABLE_AND_VIEW_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    mig_dir = tmp_path / "migrations"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        code = main(
            [
                "makemigrations",
                "--models",
                "cli_view_quiet",
                "--dir",
                str(mig_dir),
                "--name",
                "initial",
            ]
        )

    assert code == 0
    assert "Created migration" in capsys.readouterr().out
    assert [w for w in caught if issubclass(w.category, SnakeWarning)] == []
