"""`dict` with `SnakeJsonStorage`: JSONB by default, JSON optional to preserve the exact text.

`JSONB` (the default) is binary, indexable and it NORMALIZES (reorders keys, drops duplicates,
normalizes numbers → loses `100.0` vs `100`). It is what almost everybody wants. `JSON` stores the
text as it came: not indexable, but it preserves formatting, order and duplicates. Choosing `JSON`
has one further, subtle effect: it makes Postgres MATCH SQLite (which stores JSON as TEXT), closing
the normalization divergence that the property test found.

Like `SnakeEnumStorage`: an agnostic knob the dialect translates. SQLite only has TEXT.
"""

from __future__ import annotations

import pytest

from snakeorm import SnakeColumn, SnakeModel, snake_int, snake_json, snake_model

from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import AlterColumn, diff_schema, emit_create_table

_PG = PostgresDialect()
_LITE = SQLiteDialect()


def _table(doc: SnakeColumnInfo) -> SnakeTableInfo:
    """The 'events' table with whatever JSON column is passed in."""
    pk = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="events", columns=(pk, doc), primary_key=SnakePrimaryKeyInfo(columns=(pk,))
    )


def test_dict_defaults_to_jsonb() -> None:
    """Verifies that a `dict` with no knob is JSONB: indexable and normalized, what 99% want."""
    doc = SnakeColumnInfo(name="payload", python_type=dict)
    assert '"payload" JSONB NOT NULL' in emit_create_table(_table(doc), _PG)


def test_dict_with_json_storage_is_json() -> None:
    """Verifies that asking for JSON emits JSON (exact text), not JSONB."""
    doc = SnakeColumnInfo(
        name="payload",
        python_type=dict,
        type_params=SnakeJsonParams(storage=SnakeJsonStorage.JSON),
    )
    assert '"payload" JSON NOT NULL' in emit_create_table(_table(doc), _PG)


def test_sqlite_stores_json_as_text_either_way() -> None:
    """Verifies that SQLite emits TEXT whatever the knob says: it only has one text affinity."""
    jsonb = SnakeColumnInfo(name="payload", python_type=dict)
    json = SnakeColumnInfo(
        name="payload",
        python_type=dict,
        type_params=SnakeJsonParams(storage=SnakeJsonStorage.JSON),
    )
    assert '"payload" TEXT NOT NULL' in emit_create_table(_table(jsonb), _LITE)
    assert '"payload" TEXT NOT NULL' in emit_create_table(_table(json), _LITE)


def test_changing_the_storage_is_a_column_change() -> None:
    """Verifies that the diff sees the JSONB↔JSON change: not cosmetic, it changes the column semantics."""
    before = _table(SnakeColumnInfo(name="payload", python_type=dict))
    after = _table(
        SnakeColumnInfo(
            name="payload",
            python_type=dict,
            type_params=SnakeJsonParams(storage=SnakeJsonStorage.JSON),
        )
    )

    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_the_same_storage_converges() -> None:
    """Verifies that an identical column produces no operations: the autogen has to converge."""
    doc = SnakeColumnInfo(
        name="payload",
        python_type=dict,
        type_params=SnakeJsonParams(storage=SnakeJsonStorage.JSON),
    )
    assert diff_schema([_table(doc)], [_table(doc)]) == []


def test_json_storage_on_a_non_dict_is_rejected() -> None:
    """Verifies that putting `json_storage` on a non-`dict` column fails at compile time (fail loud)."""
    with pytest.raises(SnakeModelDefinitionError, match="snake_json"):

        @snake_model(table="js_bad")
        class Bad(SnakeModel):
            id: SnakeColumn[int] = snake_int(primary_key=True)
            name: SnakeColumn[str] = snake_json(storage=SnakeJsonStorage.JSON)
