"""`snake_column(index=True)` must produce an index, not just a flag in the metadata.

The compiler stored `SnakeColumnInfo.index=True` and then built `table.indexes` SOLELY out of
`SnakeIndexes`. The upshot: the flag emitted no `CREATE INDEX` at all and the column ended up with
no index in the database, silently. A promise made by the API that the DDL never kept.

One non-unique index is generated per column with `index=True`, under the default name that
`emit_create_index` already knows how to build (`ix_<table>_<column>`). If `SnakeIndexes` already
declares an index over exactly those columns, nothing is duplicated: the explicit declaration wins.
"""

from __future__ import annotations

from snakeorm.compiler import compile_model
from snakeorm.fields import SnakeColumn, SnakeIndex, snake_int, snake_str


class Indexed:
    """Model with one column indexed through the flag and another one left alone."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    slug: SnakeColumn[str] = snake_str(index=True)
    body: SnakeColumn[str] = snake_str()


class ExplicitlyIndexed:
    """The same column indexed through the flag AND through `SnakeIndexes`: no duplicate."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    slug: SnakeColumn[str] = snake_str(index=True)

    SnakeIndexes = [SnakeIndex(slug, unique=True, name="uq_slug")]


class RenamedIndexed:
    """The column overrides its SQL name: the index goes over the SQL name."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    slug: SnakeColumn[str] = snake_str(name="url_slug", index=True)


def test_index_flag_produces_an_index() -> None:
    """A column with `index=True` shows up in `table.indexes`, non-unique."""
    table = compile_model(Indexed, table="indexed")
    assert [(index.columns, index.unique) for index in table.indexes] == [
        (("slug",), False)
    ]


def test_columns_without_the_flag_are_not_indexed() -> None:
    """Only the columns carrying the flag generate an index: `body` is absent."""
    table = compile_model(Indexed, table="indexed")
    indexed_columns = {column for index in table.indexes for column in index.columns}
    assert "body" not in indexed_columns


def test_explicit_index_wins_over_the_flag() -> None:
    """If `SnakeIndexes` already covers those columns, no duplicate is added."""
    table = compile_model(ExplicitlyIndexed, table="explicit")
    assert len(table.indexes) == 1
    assert table.indexes[0].name == "uq_slug"
    assert table.indexes[0].unique is True


def test_index_uses_the_sql_column_name() -> None:
    """With a `name=` override, the index is declared over the SQL name of the column."""
    table = compile_model(RenamedIndexed, table="renamed")
    assert table.indexes[0].columns == ("url_slug",)
