"""Tests for the index advisor: it spots filter/FK columns with no index (statically and by SQL).

Cross-checking against the metadata avoids suggesting what is ALREADY indexed (PK, unique or a
declared index). The test models are written into a temporary module and imported (as in the CLI
tests): that way the linker's `get_type_hints` resolves the refs against that module's globals,
not against a local.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from snakeorm.advisor import (
    index_hints_from_records,
    index_hints_from_sql,
    unindexed_foreign_keys,
)
from snakeorm.linker.linker import snake_link
from snakeorm.metadata import SnakeTableInfo
from snakeorm.migration import current_schema
from snakeorm.registry import registry

_MODELS_SOURCE = """\
from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_auto, snake_int, snake_to_one

from snakeorm.model import SnakeModel


@snake_model(table="authors")
class Author(SnakeModel):
    id: SnakeColumn[int] = snake_auto()


@snake_model(table="books")
class Book(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    author_id: SnakeColumn[int] = snake_int()          # FK SIN índice
    author: SnakeToOne[Author] = snake_to_one(author_id)
    editor_id: SnakeColumn[int] = snake_int(index=True)  # FK CON índice
    editor: SnakeToOne[Author] = snake_to_one(editor_id)
"""


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the global registry (empty on entry, restored on exit)."""
    monkeypatch.setattr(registry, "_tables", {})
    monkeypatch.setattr(registry, "_by_name", {})
    monkeypatch.setattr(registry, "_model_by_name", {})
    monkeypatch.setattr(registry, "_table_owner", {})


def _tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str
) -> list[SnakeTableInfo]:
    """Writes and imports the test models and returns their schema (metadata)."""
    (tmp_path / f"{module_name}.py").write_text(_MODELS_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.import_module(module_name)
    snake_link()
    return current_schema()


def test_unindexed_fks_flags_only_the_unindexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """`unindexed_foreign_keys` flags the FK with no index and NOT the one that already has one."""
    hints = unindexed_foreign_keys(_tables(tmp_path, monkeypatch, "adv_models_a"))
    assert ("books", "author_id") in hints
    assert ("books", "editor_id") not in hints


def test_index_hints_from_correlated_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """A correlated subquery over an unindexed column is suggested; over an indexed one, it is not."""
    tables = _tables(tmp_path, monkeypatch, "adv_models_b")
    unindexed = (
        'SELECT (SELECT COUNT(*) FROM "books" AS e0 WHERE e0."author_id" = "authors"."id") '
        'FROM "authors"'
    )
    assert ("books", "author_id") in index_hints_from_sql([unindexed], tables)

    indexed = 'SELECT * FROM "books" WHERE "editor_id" = ?'
    assert index_hints_from_sql([indexed], tables) == []


def test_index_hints_ignore_unknown_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """A column that does not exist in the table is NOT suggested (avoids false hits from optimistic parsing)."""
    tables = _tables(tmp_path, monkeypatch, "adv_models_c")
    sql = 'SELECT * FROM "books" WHERE "nope" = ?'
    assert index_hints_from_sql([sql], tables) == []


_CORRELATED_SQL = (
    'SELECT (SELECT COUNT(*) FROM "books" AS e0 WHERE e0."author_id" = "authors"."id") '
    'FROM "authors"'
)


def test_records_ignore_fast_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """A FAST query over an unindexed column is NOT suggested: an index there would be noise."""
    tables = _tables(tmp_path, monkeypatch, "adv_models_d")
    hints = index_hints_from_records([(_CORRELATED_SQL, 3.0)], tables, min_ms=10.0)
    assert hints == []


def test_records_flag_slow_queries_with_worst_ms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """A SLOW query over an unindexed column is suggested, with the WORST duration that triggered it."""
    tables = _tables(tmp_path, monkeypatch, "adv_models_e")
    rows = [(_CORRELATED_SQL, 42.0), (_CORRELATED_SQL, 120.0)]
    hints = index_hints_from_records(rows, tables, min_ms=10.0)
    assert hints == [("books", "author_id", 120.0)]


def test_records_sort_by_worst_ms_descending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """With several slow columns, the suggestions run from the slowest to the least slow."""
    tables = _tables(tmp_path, monkeypatch, "adv_models_f")
    author_sql = _CORRELATED_SQL
    book_sql = (
        'SELECT * FROM "books" WHERE "author_id" = ?'  # same column, another shape
    )
    hints = index_hints_from_records(
        [(author_sql, 30.0), (book_sql, 200.0)], tables, min_ms=10.0
    )
    assert hints[0][2] == 200.0  # the worst one wins
