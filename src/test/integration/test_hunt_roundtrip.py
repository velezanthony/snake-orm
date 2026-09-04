"""HUNT 1 — round-trip through the FILE of a table with EVERY feature at the same time.

Each phase tested its own piece of the renderer separately. Nobody had put them all in the same
table and made it travel to disk and back. The renderer is where most bugs have hidden away in this
branch, and the combination is exactly what none of those tests covered.

The contract being chased: metadata → file → `exec` → EQUIVALENT metadata, and the same DDL.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import IntEnum, StrEnum

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeDecimalParams,
    SnakeEnumStorage,
    SnakeFkAction,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakeIndexMethod,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeServerDefault,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AddCheck,
    AddForeignKey,
    CreateIndex,
    CreateSchema,
    CreateTable,
    Migration,
    RenameColumn,
    SnakeMigrationOperation,
    SnakeOperation,
    render_migration,
)

_DIALECT = PostgresDialect()


class Level(StrEnum):
    """Text enum for the hunt."""

    BAJO = "low"
    ALTO = "alto"


class Rango(IntEnum):
    """Numeric enum for the hunt."""

    UNO = 1
    DOS = 2


def _rebuild(source: str) -> list[SnakeMigrationOperation]:
    """Runs the generated file and returns its operations."""
    namespace: dict[str, object] = {}
    exec(compile(source, "<caceria>", "exec"), namespace)  # noqa: S102
    migration = namespace["migration"]
    assert isinstance(migration, Migration)
    return list(migration.operations)


def _ddl(
    operations: Sequence[SnakeMigrationOperation],
) -> list[tuple[list[str], list[str]]]:
    """DDL fingerprint (up/down) of every operation."""
    signatures: list[tuple[list[str], list[str]]] = []
    for op in operations:
        assert isinstance(op, SnakeOperation)
        signatures.append((op.up_sql(_DIALECT), op.down_sql(_DIALECT)))
    return signatures


_ID = SnakeColumnInfo(name="id", python_type=int, autoincrement=True, attr_name="id")

_EVERYTHING = SnakeTableInfo(
    name="caza",
    schema="publico_caza",
    database="analytics",
    db_comment="A table with everything at once",
    columns=(
        _ID,
        SnakeColumnInfo(
            name="email", python_type=str, unique=True, db_comment="Correo"
        ),
        SnakeColumnInfo(name="borrado", python_type=datetime, nullable=True),
        SnakeColumnInfo(
            name="amount",
            python_type=Decimal,
            type_params=SnakeDecimalParams(precision=12, scale=2),
        ),
        SnakeColumnInfo(
            name="nivel",
            python_type=Level,
            enum_type=Level,
            enum_storage=SnakeEnumStorage.CHECK,
            default=Level.BAJO,
            has_default=True,
        ),
        SnakeColumnInfo(
            name="rango",
            python_type=Rango,
            enum_type=Rango,
            enum_storage=SnakeEnumStorage.CHECK,
            default=Rango.UNO,
            has_default=True,
        ),
        SnakeColumnInfo(
            name="created", python_type=datetime, server_default=SnakeServerDefault.NOW
        ),
        SnakeColumnInfo(name="extra", python_type=dict, nullable=True),
        # The GENERIC alias, which is what caught the bug: `list[str]` is not a `type`, and
        # reading its `__qualname__` returned a bare `"list"` without raising any error at all.
        # The cycle silently stopped closing.
        SnakeColumnInfo(name="tags", python_type=list[str], nullable=True),
    ),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    indexes=(
        SnakeIndexInfo(columns=("email",), method=SnakeIndexMethod.GIN),
        SnakeIndexInfo(
            columns=("amount",),
            unique=True,
            where=SnakeExpr[datetime](path=("borrado",)).is_null(),
        ),
    ),
    checks=(
        SnakeCheckInfo(condition=SnakeExpr[Decimal](path=("amount",)) > Decimal("0")),
        SnakeCheckInfo(
            condition=SnakeExpr[str](path=("email",)).like("%@%"), name="ck_caza_email"
        ),
    ),
)


def test_a_table_with_everything_round_trips_through_the_file() -> None:
    """THE HUNT: a table with enums, checks, partial index, method, arrays, JSONB and precision."""
    operations: list[SnakeOperation] = [CreateTable(_EVERYTHING)]
    source = render_migration("0001_caza", operations)

    assert _ddl(_rebuild(source)) == _ddl(operations)


def test_every_operation_type_round_trips_together() -> None:
    """Every operation in the SAME file: each one drags along its own imports."""
    target = SnakeTableInfo(
        name="destino",
        columns=(_ID,),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )
    relation = SnakeRelationshipInfo(
        name="destino",
        target="Destino",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(
            target="Destino", pairs=(("id", "id"),), on_delete=SnakeFkAction.CASCADE
        ),
    )
    operations: list[SnakeOperation] = [
        CreateSchema("publico_caza"),
        CreateTable(_EVERYTHING),
        CreateTable(target),
        AddForeignKey(_EVERYTHING, relation, target),
        AddCheck(
            _EVERYTHING, SnakeCheckInfo(condition=SnakeExpr[int](path=("id",)) > 0)
        ),
        CreateIndex(_EVERYTHING, SnakeIndexInfo(columns=("created",))),
        RenameColumn(_EVERYTHING, old_name="extra", new_name="metadatos"),
    ]
    source = render_migration("0002_todo", operations)

    assert _ddl(_rebuild(source)) == _ddl(operations)


def test_the_generated_file_survives_ruff() -> None:
    """The generated file has to pass the project's own linter, or it dirties the repo.

    The renderer promises to imitate `ruff format` (88 columns, double quotes, magic comma). With
    a table this loaded, that promise is a great deal easier to break.
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    if shutil.which("ruff") is None:  # pragma: no cover - depends on the environment
        pytest.skip("ruff is not on the PATH")

    source = render_migration("0003_caza", [CreateTable(_EVERYTHING)])
    with tempfile.TemporaryDirectory() as folder:
        file_path = Path(folder) / "0003_caza.py"
        file_path.write_text(source)
        result = subprocess.run(  # noqa: S603
            ["ruff", "check", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, (
        f"ruff complains about the generated file:\n{result.stdout}"
    )
