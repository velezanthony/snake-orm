"""A `python_type` the engines spell the same way is the SAME column, and refining one is not a migration.

`_column_changed` walks `SnakeColumnInfo`'s own fields, so `python_type` was compared by identity.
`dict` and `dict[str, object]` are not identical, so refining the annotation of a JSON column
produced an `AlterColumn` — and `emit_alter_column` then rendered it as NOTHING, on all three
dialects, because it compares the SQL type and the SQL type never moved.

That gap is not cosmetic. The operation asks for `ALTER TABLE ... ALTER COLUMN ... TYPE JSONB` on a
column that is already JSONB: a full table rewrite, holding a lock, to change nothing. An ORM that
demands an outage because somebody typed their `dict` properly is punishing the one rule this
project cares most about — and it happened here, to this repository's own demos, the day
`SnakeColumn[dict]` became `SnakeColumn[dict[str, object]]`.

WHY THIS IS NOT AN UNWRAP OF THE ORIGIN, which is the fix that looks obvious and is wrong. Measured
on Postgres: `list[int]` is `BIGINT[]` and `list[str]` is `TEXT[]`. Comparing origins would call
those one column and lose a real schema change — the opposite defect, and the worse one, because
this one is loud and that one is silent. A `dict` is one opaque JSON value in all three engines and
its parameters genuinely never reach SQL; a `list`'s element type does. So the normalisation is
narrow on purpose, and it is measured rather than assumed.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration.ddl import emit_alter_column
from snakeorm.migration.diff import _column_changed

_DIALECTS = [PostgresDialect(), MySQLDialect(), SQLiteDialect()]


def _column(python_type: object) -> SnakeColumnInfo:
    """One JSON-ish column differing only in how its annotation is parameterised."""
    return SnakeColumnInfo(name="attrs", python_type=python_type, attr_name="attrs")  # type: ignore[arg-type]


def test_parameterising_a_dict_is_not_a_column_change() -> None:
    """THE test. `dict` -> `dict[str, object]` is the same column in every engine."""
    assert not _column_changed(_column(dict), _column(dict[str, object]))


def test_two_differently_parameterised_dicts_are_the_same_column() -> None:
    """And the parameters do not matter among themselves either: JSON is one opaque type."""
    assert not _column_changed(_column(dict[str, int]), _column(dict[str, str]))


def test_the_element_type_of_a_list_is_still_a_column_change() -> None:
    """The floor, and the reason the normalisation is narrow.

    Without this, a fix that unwrapped the origin would pass the test above while losing
    `BIGINT[]` -> `TEXT[]`, which is a real change to a real column.
    """
    assert _column_changed(_column(list[int]), _column(list[str]))


def test_a_dict_is_still_not_a_list() -> None:
    """Normalising within a base type never merges two different ones."""
    assert _column_changed(_column(dict[str, object]), _column(list[int]))


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
def test_the_engines_agree_there_was_nothing_to_do(dialect: object) -> None:
    """The measurement the fix rests on: the emitter already renders this pair as no statements.

    This is what makes the claim above a fact rather than a reading of the type mapping. If some
    engine ever did spell the two differently, this goes red and the normalisation has to go.
    """
    identifier = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="skus",
        columns=(identifier, _column(dict)),
        primary_key=SnakePrimaryKeyInfo(columns=(identifier,)),
    )

    assert (
        emit_alter_column(table, _column(dict), _column(dict[str, object]), dialect)  # type: ignore[arg-type]
        == []
    )
