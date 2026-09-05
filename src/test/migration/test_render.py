"""Tests of rendering the history to code: round-trip + rejection of what is not serializable.

The round-trip is THE proof that the snapshot stays frozen: it is rendered to code, executed and
the rebuilt operations produce EXACTLY the same up_sql/down_sql as the original ones. On top of
that it is checked that a lambda as a factory and a non-literal default are refused loudly.
"""

from __future__ import annotations

import datetime
import enum
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeEnumStorage,
    SnakeFkAction,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeServerDefault,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AddForeignKey,
    CreateIndex,
    CreateTable,
    DropIndex,
    Migration,
    RunPython,
    RunSQL,
    SnakeMigrationOperation,
    SnakeOperation,
    render_migration,
)
from snakeorm.migration.render import render_migration as _render


def _reconstruct(source: str) -> list[SnakeMigrationOperation]:
    """Executes the generated code in a clean namespace and returns its operations."""
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated-migration>", "exec"), namespace)  # noqa: S102
    migration = namespace["migration"]
    assert isinstance(migration, Migration)
    return list(migration.operations)


def _sql(
    operations: Sequence[SnakeMigrationOperation],
) -> list[tuple[list[str], list[str]]]:
    """The SQL signature (up/down) of each schema/RunSQL operation: what the round-trip preserves."""
    dialect = PostgresDialect()
    signatures: list[tuple[list[str], list[str]]] = []
    for op in operations:
        assert isinstance(
            op, SnakeOperation
        )  # only the ones that emit SQL have up_sql/down_sql
        signatures.append((op.up_sql(dialect), op.down_sql(dialect)))
    return signatures


def data_forward(session: object) -> None:
    """Test data-migration function: importable at module level (for the render)."""


def data_backward(session: object) -> None:
    """Test reverse: importable at module level."""


def test_render_exposes_migration_and_version() -> None:
    """The generated file exposes `version`, `operations` and `migration: Migration`."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="widgets",
        columns=(id_col,),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    source = render_migration("0001_initial", [CreateTable(table)])
    assert 'version = "0001_initial"' in source
    assert "migration = Migration(" in source
    assert "operations = [" in source


def test_round_trip_preserves_sql_for_create_table() -> None:
    """Round-trip of a CreateTable with assorted types, autoincrement, default and factory."""
    id_col = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    created = SnakeColumnInfo(
        name="created",
        python_type=datetime.datetime,
        nullable=True,
        default_factory=datetime.datetime.now,
    )
    price = SnakeColumnInfo(
        name="price", python_type=Decimal, default=Decimal("9.99"), has_default=True
    )
    active = SnakeColumnInfo(
        name="active", python_type=bool, default=True, has_default=True
    )
    table = SnakeTableInfo(
        name="products",
        columns=(id_col, created, price, active),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
        indexes=(SnakeIndexInfo(columns=("price",), unique=True),),
    )
    operations: list[SnakeOperation] = [CreateTable(table)]
    source = render_migration("0001_products", operations)
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_round_trip_preserves_sql_for_create_and_drop_index() -> None:
    """Round-trip of CreateIndex/DropIndex: the written migration rebuilds the SAME DDL.

    It closes point 2 of the metadata contract (the renderer): without this, `makemigrations`
    would generate the operations and then blow up while writing the file.
    """
    id_col = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="users",
        columns=(id_col, SnakeColumnInfo(name="email", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    operations: list[SnakeOperation] = [
        CreateIndex(table, SnakeIndexInfo(columns=("email",), unique=True)),
        DropIndex(table, SnakeIndexInfo(columns=("email",), name="viejo")),
    ]
    source = render_migration("0002_indexes", operations)

    assert "CreateIndex(" in source
    assert "DropIndex(" in source
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_round_trip_preserves_sql_for_server_default() -> None:
    """Round-trip of a CreateTable with server_default (enum) and server_default_sql (raw)."""
    id_col = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    created = SnakeColumnInfo(
        name="created_at",
        python_type=datetime.datetime,
        server_default=SnakeServerDefault.NOW,
    )
    public_id = SnakeColumnInfo(
        name="public_id",
        python_type=int,
        server_default_sql="gen_random_uuid()",
    )
    table = SnakeTableInfo(
        name="events",
        columns=(id_col, created, public_id),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    operations: list[SnakeOperation] = [CreateTable(table)]
    source = render_migration("0001_events", operations)
    # The enum is rendered by its NAME with its import from snakeorm.metadata.
    assert "SnakeServerDefault.NOW" in source
    assert "from snakeorm.metadata import (" in source
    assert "server_default_sql=" in source
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_round_trip_preserves_sql_for_foreign_key() -> None:
    """Round-trip of an AddForeignKey (relation + referential actions)."""
    parent_id = SnakeColumnInfo(name="id", python_type=int)
    parent = SnakeTableInfo(
        name="parents",
        columns=(parent_id,),
        primary_key=SnakePrimaryKeyInfo(columns=(parent_id,)),
    )
    child_id = SnakeColumnInfo(name="id", python_type=int)
    relationship = SnakeRelationshipInfo(
        name="parent",
        target="Parent",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(
            target="Parent",
            pairs=(("parent_id", "id"),),
            on_delete=SnakeFkAction.CASCADE,
        ),
    )
    child = SnakeTableInfo(
        name="children",
        columns=(child_id, SnakeColumnInfo(name="parent_id", python_type=int)),
        primary_key=SnakePrimaryKeyInfo(columns=(child_id,)),
        relationships=(relationship,),
    )
    operations: list[SnakeOperation] = [
        CreateTable(parent),
        CreateTable(child),
        AddForeignKey(child, relationship, parent),
    ]
    source = render_migration("0002_fk", operations)
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_render_serializes_target_table_for_self_contained_migration() -> None:
    """REGRESSION: `target_table` (the ALREADY resolved target) is serialised. Without it the
    migration is not self-contained and CANNOT be APPLIED on SQLite (which demands the FK inside the
    CREATE TABLE, and to inline it needs the resolved target table's name)."""
    child_id = SnakeColumnInfo(name="id", python_type=int)
    relationship = SnakeRelationshipInfo(
        name="parent",
        target="Parent",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(target="Parent", pairs=(("parent_id", "id"),)),
        target_table="public.parents",
    )
    child = SnakeTableInfo(
        name="children",
        columns=(child_id, SnakeColumnInfo(name="parent_id", python_type=int)),
        primary_key=SnakePrimaryKeyInfo(columns=(child_id,)),
        relationships=(relationship,),
    )
    source = render_migration("0001_child", [CreateTable(child)])
    assert "public.parents" in source  # the resolved target travels in the file
    rebuilt = _reconstruct(source)
    assert isinstance(rebuilt[0], CreateTable)
    assert rebuilt[0].table.relationships[0].target_table == "public.parents"


def _fk_migration_source() -> str:
    """Renders a migration with two tables and an FK between them (for the shape tests)."""
    author_id = SnakeColumnInfo(
        name="id", python_type=int, autoincrement=True, attr_name="id"
    )
    author = SnakeTableInfo(
        name="cli_authors",
        columns=(
            author_id,
            SnakeColumnInfo(name="name", python_type=str, attr_name="name"),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(author_id,)),
    )
    book_id = SnakeColumnInfo(
        name="id", python_type=int, autoincrement=True, attr_name="id"
    )
    relationship = SnakeRelationshipInfo(
        name="author",
        target="Author",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(
            target="Author",
            pairs=(("author_id", "id"),),
            on_delete=SnakeFkAction.CASCADE,
        ),
    )
    book = SnakeTableInfo(
        name="cli_books",
        columns=(
            book_id,
            SnakeColumnInfo(name="author_id", python_type=int, attr_name="author_id"),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(book_id,)),
        relationships=(relationship,),
    )
    operations: list[SnakeOperation] = [
        CreateTable(author),
        CreateTable(book),
        AddForeignKey(book, relationship, author),
    ]
    return render_migration("0001_books", operations)


def test_render_extracts_tables_to_named_variables() -> None:
    """Each table is declared ONCE as a named variable and the operations reference it."""
    source = _fk_migration_source()
    # The table is declared as a variable sanitised from its name.
    assert "cli_authors = SnakeTableInfo(" in source
    assert "cli_books = SnakeTableInfo(" in source
    # The operations reference the variable, they do not repeat the SnakeTableInfo inline.
    assert "CreateTable(cli_authors)" in source
    assert "AddForeignKey(\n        cli_books," in source
    # `cli_authors = SnakeTableInfo(` appears ONLY once (the whole table is not repeated).
    assert source.count("cli_authors = SnakeTableInfo(") == 1
    assert source.count("cli_books = SnakeTableInfo(") == 1


def test_render_omits_fields_equal_to_their_default() -> None:
    """Fields equal to their default value (nullable=False, unique=False...) are not emitted."""
    source = _fk_migration_source()
    assert "nullable=False" not in source
    assert "unique=False" not in source
    assert "has_default=False" not in source
    assert "index=False" not in source


def test_render_uses_double_quotes() -> None:
    """Strings are rendered with double quotes (consistent with ruff), not single ones."""
    source = _fk_migration_source()
    assert 'name="cli_authors"' in source
    assert "name='cli_authors'" not in source


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not on the PATH")
def test_rendered_migration_passes_ruff(tmp_path: Path) -> None:
    """The generated file passes `ruff check` and `ruff format --check` untouched (a real guarantee)."""
    path = tmp_path / "0001_books.py"
    path.write_text(_fk_migration_source())

    check = subprocess.run(
        ["ruff", "check", str(path)], capture_output=True, text=True, check=False
    )
    assert check.returncode == 0, check.stdout + check.stderr

    fmt = subprocess.run(
        ["ruff", "format", "--check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr


def test_lambda_factory_is_rejected() -> None:
    """A lambda as default_factory has no import path: SnakeModelDefinitionError."""
    col = SnakeColumnInfo(name="x", python_type=int, default_factory=lambda: 1)
    table = SnakeTableInfo(
        name="t", columns=(col,), primary_key=SnakePrimaryKeyInfo(columns=(col,))
    )
    with pytest.raises(SnakeModelDefinitionError, match="import"):
        render_migration("0001_x", [CreateTable(table)])


def test_closure_factory_is_rejected() -> None:
    """A closure (qualname with <locals>) is not importable either: SnakeModelDefinitionError."""

    def make_factory() -> object:
        def inner() -> int:
            return 1

        return inner

    col = SnakeColumnInfo(name="x", python_type=int, default_factory=make_factory())  # type: ignore[arg-type]
    table = SnakeTableInfo(
        name="t", columns=(col,), primary_key=SnakePrimaryKeyInfo(columns=(col,))
    )
    with pytest.raises(
        SnakeModelDefinitionError,
        match="is not importable: a lambda or a closure has no import path",
    ):
        _render("0001_x", [CreateTable(table)])


def test_unrenderable_default_is_rejected() -> None:
    """An arbitrary default (not a literal) cannot be written into the file: an explicit error."""

    class Weird:
        pass

    col = SnakeColumnInfo(name="x", python_type=int, default=Weird(), has_default=True)
    table = SnakeTableInfo(
        name="t", columns=(col,), primary_key=SnakePrimaryKeyInfo(columns=(col,))
    )
    with pytest.raises(SnakeModelDefinitionError, match="literal"):
        render_migration("0001_x", [CreateTable(table)])


def test_round_trip_preserves_sql_for_run_sql() -> None:
    """Round-trip of a RunSQL (raw up/down SQL): the statements survive the exec."""
    operations: list[SnakeMigrationOperation] = [
        RunSQL(("UPDATE t SET x = 1", "UPDATE t SET y = 2"), down="UPDATE t SET x = 0")
    ]
    source = render_migration("0001_data", operations)
    assert "RunSQL(" in source
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_render_run_python_references_importable_functions() -> None:
    """RunPython renders by REFERENCE: the file is imported and its functions exist (round-trip)."""
    source = render_migration("0002_py", [RunPython(data_forward, data_backward)])
    assert "RunPython(" in source
    operations = _reconstruct(source)
    assert len(operations) == 1
    operation = operations[0]
    assert isinstance(operation, RunPython)
    # The functions are rebuilt from their import path: they are EXACTLY the module's own.
    assert operation.forward is data_forward
    assert operation.backward is data_backward


def test_render_run_python_rejects_lambda() -> None:
    """A lambda as `forward` is not importable: SnakeModelDefinitionError (as with default_factory)."""
    with pytest.raises(SnakeModelDefinitionError, match="import"):
        render_migration("0003_bad", [RunPython(lambda session: None)])


class RenderLevel(enum.StrEnum):
    """A module-level enum: the renderer references it by its import path."""

    FREE = "free"
    PRO = "pro"


def test_round_trip_preserves_sql_for_an_enum_column() -> None:
    """Round-trip of an enum column: type, storage and its derived CHECK all survive.

    It closes point 2 of the contract for `snake_enum`. The enum is referenced by its import path
    (`render_type` already knew how), so no name<->type registry is needed at all.
    """
    id_col = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    level = SnakeColumnInfo(
        name="level",
        python_type=RenderLevel,
        enum_type=RenderLevel,
        enum_storage=SnakeEnumStorage.CHECK,
    )
    table = SnakeTableInfo(
        name="render_accounts",
        columns=(id_col, level),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
        checks=(
            SnakeCheckInfo(
                condition=SnakeExpr[str](path=("level",)).in_(("free", "pro"))
            ),
        ),
    )
    operations: list[SnakeOperation] = [CreateTable(table)]
    source = render_migration("0009_enum", operations)

    assert "SnakeEnumStorage.CHECK" in source
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_a_generic_alias_renders_with_its_arguments() -> None:
    """A generic alias is written WHOLE, with its argument and with that argument's import.

    `list[str]` is not a `type`: it is a `types.GenericAlias` that delegates attributes to its origin.
    Reading its `__qualname__` returned a bare `"list"` **with no error whatsoever**, so the migration
    stored a different type from the one it was given and the cycle silently stopped closing.

    The case with `uuid.UUID` inside is the one that proves the point: the argument has to go through
    the same `render_type`, because it is that call — and no other — that REGISTERS its import.
    """
    id_col = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    table = SnakeTableInfo(
        name="render_generics",
        columns=(
            id_col,
            SnakeColumnInfo(name="tags", python_type=list[str], nullable=True),
            SnakeColumnInfo(name="claves", python_type=list[uuid.UUID], nullable=True),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    operations: list[SnakeOperation] = [CreateTable(table)]
    source = render_migration("0010_generics", operations)

    assert "list[str]" in source
    assert "list[uuid.UUID]" in source
    assert "import uuid" in source, "the argument has to register its own import"
    assert _sql(_reconstruct(source)) == _sql(operations)


def test_an_unrenderable_type_is_rejected_out_loud() -> None:
    """What cannot be written is rejected AT GENERATION TIME, not degraded into something similar.

    It is the lesson of the bug itself: degrading in silence produces a migration that compiles, gets
    applied and says something else. An error here costs a minute; the silence cost the round-trip.
    """
    id_col = SnakeColumnInfo(name="id", python_type=int, autoincrement=True)
    table = SnakeTableInfo(
        name="render_raro",
        columns=(id_col, SnakeColumnInfo(name="raro", python_type="no soy un tipo")),  # type: ignore[arg-type]
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )

    with pytest.raises(
        SnakeModelDefinitionError, match="is not renderable in a migration"
    ):
        render_migration("0011_raro", [CreateTable(table)])
