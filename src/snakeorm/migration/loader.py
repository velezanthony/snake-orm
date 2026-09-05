"""Loading the migration history from disk.

Files named `NNNN_<slug>.py`; the order comes from the NUMBER (linear, no gaps and no duplicates),
there is no `down_revision`. Each one exposes `migration: Migration`. A gap or a duplicate is caught
here, before touching the DB.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.migration.runner import Migration

_FILENAME = re.compile(r"^(?P<number>\d+)_.+\.py$")


def load(directory: str | Path) -> list[Migration]:
    """Discovers, validates and loads a directory's migrations, ordered by number.

    Returns `[]` if the directory does not exist or has no migrations. Raises `SnakeMigrationError`
    if there are duplicate numbers or gaps in the sequence.
    """
    directory_path = Path(directory)
    if not directory_path.is_dir():
        return []

    numbered: list[tuple[int, Path]] = []
    for path in directory_path.iterdir():
        if not path.is_file():
            continue
        match = _FILENAME.match(path.name)
        if match is None:
            continue  # ignores __init__.py, notes, etc.
        numbered.append((int(match.group("number")), path))

    if not numbered:
        return []

    numbered.sort(key=lambda pair: pair[0])
    _validate_sequence([number for number, _ in numbered])
    return [_load_one(path) for _, path in numbered]


def _validate_sequence(numbers: list[int]) -> None:
    """Demands linear numbering with no duplicates and no gaps (1, 2, 3, ..., N)."""
    seen: set[int] = set()
    for number in numbers:
        if number in seen:
            raise SnakeMigrationError(
                f"Duplicate migration number: {number:04d}. Every migration must have a unique "
                f"number."
            )
        seen.add(number)
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        raise SnakeMigrationError(
            f"The migration numbering has gaps: {expected} was expected and {numbers} was found. "
            f"They must be linear from 0001 with no jumps."
        )


def _load_one(path: Path) -> Migration:
    """Imports a migration file by path and returns its `migration: Migration`."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SnakeMigrationError(f"The import of {path} could not be prepared.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migration = getattr(module, "migration", None)
    if not isinstance(migration, Migration):
        raise SnakeMigrationError(
            f"The migration file {path.name} does not expose `migration: Migration`."
        )
    return migration
