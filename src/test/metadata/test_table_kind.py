"""`SnakeTableKind`: a single axis for what a node IS and who governs it.

There used to be an `is_view: bool`, and behind it came a `managed: bool` (mirror models of
`@snake_db_first`) and a `database: str`. Two booleans are four combinations with only three
meanings; three are eight, of which five are illegal —an external view that we do manage?—. The
enum makes those five unwritable, which is the discipline of this project.

`is_view` and `is_managed` still exist as DERIVED properties: they are legitimate questions, and
having them computed keeps anyone from storing them separately and letting them drift apart.
"""

from __future__ import annotations

from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTableKind,
)

_ID = SnakeColumnInfo(name="id", python_type=int)


def _node(kind: SnakeTableKind) -> SnakeTableInfo:
    """Minimal node of the given kind."""
    return SnakeTableInfo(
        name="n",
        columns=(_ID,),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        kind=kind,
    )


def test_a_table_is_the_default() -> None:
    """Checks that a node without an explicit `kind` is a table of ours, managed."""
    node = SnakeTableInfo(
        name="n", columns=(_ID,), primary_key=SnakePrimaryKeyInfo(columns=(_ID,))
    )
    assert node.kind is SnakeTableKind.TABLE
    assert node.is_view is False
    assert node.is_managed is True


def test_a_view_is_a_view_and_still_managed() -> None:
    """Checks that a view is read-only but IS still governed by the migrations."""
    view = _node(SnakeTableKind.VIEW)
    assert view.is_view is True
    assert view.is_managed is True  # CREATE/REPLACE/DROP VIEW are ours


def test_an_external_mirror_is_not_managed_and_is_not_a_view() -> None:
    """Checks the gap `@snake_db_first` will fill: a queryable mirror the autogen IGNORES.

    An `EXTERNAL` is queried and written like any other model —it is a real table—, but it is not
    the source of truth of its own schema: the database is.
    """
    external = _node(SnakeTableKind.EXTERNAL)
    assert external.is_managed is False
    assert external.is_view is False


def test_the_three_kinds_are_mutually_exclusive() -> None:
    """Checks that the three kinds are mutually distinct: there are no combinations to model."""
    kinds = {SnakeTableKind.TABLE, SnakeTableKind.VIEW, SnakeTableKind.EXTERNAL}
    assert len(kinds) == 3
    assert len(SnakeTableKind) == 3
