"""The scaffold cannot widen in silence: it mirrors the real width, length, precision and default.

Introspection reads `int_size`/`max_length`/`json_storage`/`precision`/`scale`/DEFAULT, but the
renderer THREW THEM AWAY: a `VARCHAR(20)` came back as `TEXT`, an `INTEGER` as `BIGINT`, a
`NUMERIC(10,2)` as a bare `NUMERIC`. On adopting the model (`@snake_db_first` → `@snake_model`) the
schema drifted from the real one, silently and against the fidelity promise. These tests pin that
ALL the knobs travel.
"""

from __future__ import annotations

from decimal import Decimal

from snakeorm.introspection.models import render_models
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDecimalParams,
    SnakeIntParams,
    SnakeIntSize,
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
)


def _table() -> SnakeTableInfo:
    """Table with one column per knob, as the Postgres introspection would return it."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    columns = (
        id_col,
        SnakeColumnInfo(
            name="code", python_type=str, type_params=SnakeStrParams(max_length=20)
        ),
        SnakeColumnInfo(
            name="amount",
            python_type=int,
            type_params=SnakeIntParams(size=SnakeIntSize.INTEGER),
        ),
        SnakeColumnInfo(
            name="doc",
            python_type=dict,
            type_params=SnakeJsonParams(storage=SnakeJsonStorage.JSON),
        ),
        SnakeColumnInfo(
            name="price",
            python_type=Decimal,
            type_params=SnakeDecimalParams(precision=10, scale=2),
        ),
        SnakeColumnInfo(name="qty", python_type=int, server_default_sql="0"),
    )
    return SnakeTableInfo(
        name="things",
        columns=columns,
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def test_every_knob_is_emitted_in_the_scaffold() -> None:
    """Checks that every knob shows up in the generated `snake_column(...)`."""
    source = render_models([_table()])
    assert "max_length=20" in source
    assert "size=SnakeIntSize.INTEGER" in source
    assert "storage=SnakeJsonStorage.JSON" in source
    assert "precision=10" in source
    assert "scale=2" in source
    assert 'server_default_sql="0"' in source


def test_the_needed_enums_are_imported() -> None:
    """Checks that SnakeIntSize/SnakeJsonStorage are imported when used (or the file does not compile)."""
    source = render_models([_table()])
    line = next(
        ln for ln in source.splitlines() if ln.startswith("from snakeorm import")
    )
    assert "SnakeIntSize" in line
    assert "SnakeJsonStorage" in line
    compile(source, "generado.py", "exec")  # importable, does not blow up


def test_no_knobs_means_no_enum_imports() -> None:
    """Checks that with no knobs no dead imports are left (ruff would complain in the generated file)."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    simple = SnakeTableInfo(
        name="plain",
        columns=(id_col, SnakeColumnInfo(name="name", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )
    source = render_models([simple])
    assert "SnakeIntSize" not in source
    assert "SnakeJsonStorage" not in source
