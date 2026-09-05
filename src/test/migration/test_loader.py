"""Tests of the history loader: linear order, and rejection of duplicates and gaps.

The order comes from the file NUMBER. A duplicate (two 0001) or a gap (0002 missing) are
history errors and must be caught before touching the database. The files are generated
with render_migration to exercise the real path (render → disk → loader)."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import CreateTable, render_migration
from snakeorm.migration.loader import load


def _write_migration(directory: Path, number: int, slug: str) -> str:
    """Writes a real NNNN_<slug>.py file (via render_migration) and returns its version."""
    version = f"{number:04d}_{slug}"
    id_col = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name=slug, columns=(id_col,), primary_key=SnakePrimaryKeyInfo(columns=(id_col,))
    )
    source = render_migration(version, [CreateTable(table)])
    (directory / f"{version}.py").write_text(source)
    return version


def test_loads_in_numeric_order(tmp_path: Path) -> None:
    """Migrations are returned sorted by number, not by discovery order."""
    _write_migration(tmp_path, 3, "gamma")
    _write_migration(tmp_path, 1, "alpha")
    _write_migration(tmp_path, 2, "beta")
    migrations = load(tmp_path)
    assert [m.version for m in migrations] == ["0001_alpha", "0002_beta", "0003_gamma"]


def test_empty_or_missing_directory_returns_empty(tmp_path: Path) -> None:
    """An empty (or non-existent) directory returns an empty list, not an error."""
    assert load(tmp_path) == []
    assert load(tmp_path / "no_existe") == []


def test_ignores_non_migration_files(tmp_path: Path) -> None:
    """Files that do not match the NNNN_*.py pattern (e.g. __init__.py, notes) are ignored."""
    _write_migration(tmp_path, 1, "alpha")
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "notas.txt").write_text("I am not a migration")
    assert [m.version for m in load(tmp_path)] == ["0001_alpha"]


def test_duplicate_numbers_raise(tmp_path: Path) -> None:
    """Two files with the same number are ambiguous: SnakeMigrationError."""
    _write_migration(tmp_path, 1, "alpha")
    _write_migration(tmp_path, 1, "other")
    with pytest.raises(SnakeMigrationError, match="Duplicate migration number"):
        load(tmp_path)


def test_gap_in_sequence_raises(tmp_path: Path) -> None:
    """A gap in the numbering (0002 missing) is a broken history: SnakeMigrationError."""
    _write_migration(tmp_path, 1, "alpha")
    _write_migration(tmp_path, 3, "gamma")
    with pytest.raises(SnakeMigrationError, match="migration numbering has gaps"):
        load(tmp_path)


def test_must_start_at_one(tmp_path: Path) -> None:
    """The numbering must start at 0001; starting at 0002 is a gap right at the front."""
    _write_migration(tmp_path, 2, "beta")
    with pytest.raises(
        SnakeMigrationError, match="They must be linear from 0001 with no"
    ):
        load(tmp_path)


def test_file_without_migration_object_raises(tmp_path: Path) -> None:
    """A file with a valid name but without `migration: Migration` is rejected."""
    (tmp_path / "0001_broken.py").write_text("x = 1\n")
    with pytest.raises(SnakeMigrationError, match="migration"):
        load(tmp_path)
