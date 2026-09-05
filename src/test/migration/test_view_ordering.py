"""Topological ordering of dependent views in the diff + `depends_on` round-trip.

A view B that reads from another view A must be CREATED after A. `depends_on` declares that relation
(only between VIEWS; a view is always created after ALL the tables). The diff orders the CreateView
by dependency (the depended-upon one first) and the DropView the other way round (first the one that
depends). A cycle between views raises SnakeMigrationError. The render round-trips `depends_on`.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTableKind,
)
from snakeorm.migration import (
    CreateView,
    DropView,
    Migration,
    diff_schema,
    render_migration,
)


def _view(name: str, definition: str, depends_on: Sequence[str] = ()) -> SnakeTableInfo:
    """Minimal view (one column) with its definition and its dependencies on other views."""
    column = SnakeColumnInfo(name="x", python_type=int)
    return SnakeTableInfo(
        name=name,
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=()),
        kind=SnakeTableKind.VIEW,
        view_definition=definition,
        depends_on=tuple(depends_on),
    )


def test_dependent_view_is_created_after_its_dependency() -> None:
    """Even if 'b' is passed before 'a', the diff creates 'a' (depended upon) before 'b'."""
    # 'b' depends on 'a'; 'b' is passed first to force the topological reordering.
    b = _view("b", "SELECT x FROM a", depends_on=("a",))
    a = _view("a", "SELECT 1 AS x")
    operations = diff_schema([], [b, a])
    created = [op.view.name for op in operations if isinstance(op, CreateView)]
    assert created == ["a", "b"]


def test_dependent_view_is_dropped_before_its_dependency() -> None:
    """The drop inverts the order: first 'b' (the one that depends), then 'a' (the depended one)."""
    b = _view("b", "SELECT x FROM a", depends_on=("a",))
    a = _view("a", "SELECT 1 AS x")
    operations = diff_schema([b, a], [])
    dropped = [op.view.name for op in operations if isinstance(op, DropView)]
    assert dropped == ["b", "a"]


def test_a_cycle_between_views_raises() -> None:
    """Two views that depend on each other have no valid order → SnakeMigrationError."""
    a = _view("a", "SELECT x FROM b", depends_on=("b",))
    b = _view("b", "SELECT x FROM a", depends_on=("a",))
    with pytest.raises(
        SnakeMigrationError, match="Dependency cycle among views: 'a' takes part in a"
    ):
        diff_schema([], [a, b])


def test_render_round_trips_depends_on() -> None:
    """The render writes `depends_on` and on re-execution rebuilds the same creation order."""
    b = _view("b", "SELECT x FROM a", depends_on=("a",))
    a = _view("a", "SELECT 1 AS x")
    operations = diff_schema([], [b, a])
    source = render_migration("001", operations)
    assert "depends_on" in source

    namespace: dict[str, object] = {}
    exec(compile(source, "<generated-migration>", "exec"), namespace)  # noqa: S102
    migration = namespace["migration"]
    assert isinstance(migration, Migration)
    created = [
        op.view.name for op in migration.operations if isinstance(op, CreateView)
    ]
    assert created == ["a", "b"]
