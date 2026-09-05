"""Indexes: SnakeIndexes in the model body → SnakeIndexInfo in the graph.

An index references the LOCAL columns directly (typed, no magic strings); the names are resolved at
compile time.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model, snake_table
from snakeorm.fields import SnakeColumn, SnakeIndex, snake_int, snake_str

from snakeorm.model import SnakeModel


@snake_model
class Article(SnakeModel):
    """Model with indexes declared in its body."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    slug: SnakeColumn[str] = snake_str()
    author: SnakeColumn[str] = snake_str()

    SnakeIndexes = [
        SnakeIndex(slug, unique=True),
        SnakeIndex(author, slug),
    ]


@snake_model
class Plain(SnakeModel):
    """Model with no indexes."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


def test_indexes_compiled() -> None:
    """The SnakeIndexes in the body compile into indexes of the graph."""
    assert len(snake_table(Article).indexes) == 2


def test_single_column_unique_index() -> None:
    """A single-column index captures the column and the unique flag."""
    index = snake_table(Article).indexes[0]
    assert index.columns == ("slug",)
    assert index.unique is True


def test_composite_index_preserves_order() -> None:
    """A composite index captures the columns in order."""
    index = snake_table(Article).indexes[1]
    assert index.columns == ("author", "slug")
    assert index.unique is False


def test_no_indexes_defaults_empty() -> None:
    """With no SnakeIndexes the table has no indexes at all."""
    assert snake_table(Plain).indexes == ()
