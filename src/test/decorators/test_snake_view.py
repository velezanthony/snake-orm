"""The @snake_view decorator compiles a VIEW: typed columns + is_view + the stored definition.

A view shares the whole column pipeline of a model, but its metadata node ends up marked with
`is_view=True` and keeps the SELECT that defines it. The source of that definition is EXACTLY one:
`sql=` (raw) or `query=` (a compiled SnakeQuery). Passing both —or neither— is a definition error.
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import snake_model, snake_table, snake_view
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import SnakeColumn, snake_column, snake_int, snake_str
from snakeorm.migration.ddl import view_fingerprint

from snakeorm.model import SnakeModel, SnakeView
from snakeorm.query import SnakeQuery


@snake_view(sql="SELECT user_id, class_name FROM enrollments")
class DecUserClasses(SnakeView):
    """Read-only view with two typed columns."""

    user_id: SnakeColumn[int] = snake_int()
    class_name: SnakeColumn[str] = snake_str()


def test_snake_view_compiles_typed_columns_and_marks_is_view() -> None:
    """The view compiles its typed columns and its table ends up marked with is_view=True."""
    table = snake_table(DecUserClasses)
    assert table.is_view is True
    assert [column.name for column in table.columns] == ["user_id", "class_name"]
    assert table.get_column("user_id").python_type is int  # type: ignore[union-attr]
    assert table.get_column("class_name").python_type is str  # type: ignore[union-attr]


def test_snake_view_stores_the_raw_sql_definition() -> None:
    """With `sql=` the definition is stored raw, exactly as given: the user owns the SELECT."""
    table = snake_table(DecUserClasses)
    assert table.view_definition == "SELECT user_id, class_name FROM enrollments"


def test_snake_view_does_not_require_a_primary_key() -> None:
    """A view may have no PK: the compiler does NOT demand one, unlike with a model."""
    table = snake_table(DecUserClasses)
    assert table.primary_key.columns == ()


def test_snake_view_can_be_defined_from_a_query() -> None:
    """With `query=` the view keeps the SnakeQuery and its body compiles where it should, no params.

    It is checked through the FINGERPRINT and not through `view_definition`: that field now carries
    only the raw SELECT of the `sql=` path. Compiling inside the decorator froze the body into the
    dialect of one engine.
    """

    @snake_model(table="dec_view_src_rows")
    class DecViewSource(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        name: SnakeColumn[str] = snake_str()

    @snake_view(query=SnakeQuery(DecViewSource), name="dec_view_from_query")
    class DecFromQuery(SnakeView):
        id: SnakeColumn[int] = snake_int()
        name: SnakeColumn[str] = snake_str()

    table = snake_table(DecFromQuery)
    assert table.is_view is True
    assert table.view_query is not None
    fingerprint = view_fingerprint(table)
    assert "dec_view_src_rows" in fingerprint
    assert "SELECT" in fingerprint


def test_snake_view_query_inlines_literals_from_filters() -> None:
    """A query with a literal filter compiles with the literal inlined: a view takes no params."""

    @snake_model(table="dec_view_src2_rows")
    class DecViewSource2(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        active: SnakeColumn[bool] = snake_column()

    @snake_view(
        query=SnakeQuery(DecViewSource2).filter(DecViewSource2.active == True),  # noqa: E712
        name="dec_view_active",
    )
    class DecActive(SnakeView):
        id: SnakeColumn[int] = snake_int()
        active: SnakeColumn[bool] = snake_column()

    definition = view_fingerprint(snake_table(DecActive))
    assert (
        "%s" not in definition
    )  # the literal was inlined, no placeholder was left behind
    assert "TRUE" in definition


def test_snake_view_rejects_both_sql_and_query() -> None:
    """Passing `sql=` AND `query=` at once is ambiguous: SnakeModelDefinitionError."""
    with pytest.raises(
        SnakeModelDefinitionError,
        match="@snake_view requires EXACTLY one source for the definition:",
    ):

        @snake_view(sql="SELECT 1", query=SnakeQuery(DecUserClasses))
        class _Both(SnakeView):
            user_id: SnakeColumn[int] = snake_int()


def test_snake_view_rejects_neither_sql_nor_query() -> None:
    """Passing neither `sql=` nor `query=` leaves the view undefined: SnakeModelDefinitionError."""
    with pytest.raises(
        SnakeModelDefinitionError,
        match="@snake_view requires EXACTLY one source for the definition:",
    ):

        @snake_view()
        class _Neither(SnakeView):
            user_id: SnakeColumn[int] = snake_int()


def test_a_view_can_be_declared_in_an_isolated_registry() -> None:
    """`@snake_view` accepts `registry=`, just like the other two declaration surfaces.

    It was the only one of the three that did not, and that asymmetry forced the view tests to dirty
    the global registry — which is literally how bug #14 was found, the foreign key pointing at the
    table of another model that happened to share its name.
    """
    from snakeorm.registry import SnakeRegistry
    from snakeorm.registry import registry as global_registry

    reg = SnakeRegistry()

    @snake_view(sql="SELECT 1 AS id", name="vista_aislada", registry=reg)
    class VistaAislada(SnakeView):
        """View declared outside the global registry."""

        id: SnakeColumn[int] = snake_int()

    assert reg.table_of(VistaAislada) is not None
    assert global_registry.table_of(VistaAislada) is None, (
        "it must not touch the global one"
    )
