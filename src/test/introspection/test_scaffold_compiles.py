"""Test that what `scaffold` generates can be AMOUNTD and compiles as a model.

The hole it closes, and it cost dearly: the scaffolder tests checked the generated TEXT —that
`max_length=20` came out, that `primary_key=True` showed up— and none of them ran it. So when
`snake_column()` stopped accepting the type knobs, the scaffolder kept emitting them and kept
passing the tests: it generated files that do not compile, and nobody noticed.

It is exactly the lesson the repo itself has written down in
`test/migration/test_render_completeness.py`: *"a test that measures the source code measures the
source code; to know whether something works you have to call it"*. Here it is called: the generated
module is written to disk, imported for real, and its models are compiled into the graph.

One column of EACH family carrying parameters is covered, which are precisely the ones a generic
`snake_column()` can no longer declare.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
import pytest

from snakeorm import SnakeUtc
from snakeorm.introspection.models import render_models
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDateTimeParams,
    SnakeDecimalParams,
    SnakeIntParams,
    SnakeIntSize,
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
)
from snakeorm.registry import registry


def _table_with_everything() -> SnakeTableInfo:
    """A table with one column of each family carrying parameters, plus one without them."""
    pk = SnakeColumnInfo(name="id", python_type=int, attr_name="id", autoincrement=True)
    columns = (
        pk,
        SnakeColumnInfo(
            name="codigo",
            python_type=str,
            attr_name="codigo",
            type_params=SnakeStrParams(max_length=20),
        ),
        SnakeColumnInfo(
            name="quantity",
            python_type=int,
            attr_name="quantity",
            type_params=SnakeIntParams(size=SnakeIntSize.SMALLINT),
        ),
        SnakeColumnInfo(
            name="amount",
            python_type=Decimal,
            attr_name="amount",
            type_params=SnakeDecimalParams(precision=12, scale=2),
        ),
        SnakeColumnInfo(
            name="meta",
            python_type=dict,
            attr_name="meta",
            type_params=SnakeJsonParams(storage=SnakeJsonStorage.JSON),
        ),
        SnakeColumnInfo(
            name="ocurrio",
            python_type=SnakeUtc,
            attr_name="ocurrio",
            type_params=SnakeDateTimeParams(tz=True),
        ),
        SnakeColumnInfo(
            name="apertura",
            python_type=datetime,
            attr_name="apertura",
            type_params=SnakeDateTimeParams(tz=False),
        ),
        SnakeColumnInfo(name="dia", python_type=date, attr_name="dia"),
    )
    return SnakeTableInfo(
        name="cosas", columns=columns, primary_key=SnakePrimaryKeyInfo(columns=(pk,))
    )


@pytest.fixture(scope="module")
def generated_model(tmp_path_factory: pytest.TempPathFactory) -> Iterator[type]:
    """Writes the module the scaffolder generates, IMPORTS it for real, and returns its model.

    MODULE scoped because importing it REGISTERS the table in the global registry: doing it once per
    test would clash with itself on the second go.
    """
    dest = tmp_path_factory.mktemp("scaffold")
    (dest / "mirror_scaffold.py").write_text(
        render_models([_table_with_everything()]), encoding="utf-8"
    )
    sys.path.insert(0, str(dest))
    try:
        module = importlib.import_module("mirror_scaffold")
        yield next(
            value
            for value in vars(module).values()
            if isinstance(value, type) and registry.table_of(value) is not None
        )
    finally:
        sys.path.remove(str(dest))
        # The module STAYS in sys.modules on purpose: importing it registered its model in the
        # global registry, and `snake_link()` resolves the annotations against the module globals.
        # Removing it would leave a registered model whose module no longer exists, and the next
        # link of ANY other test would blow up with a NameError that has nothing to do with it.


def test_the_generated_module_imports(generated_model: type) -> None:
    """Checks that the generated file imports without blowing up.

    Importing it is what fires `@snake_db_first`, which compiles the model and goes through ALL the
    compiler guards. If the scaffolder emits a declarator that no longer exists or a knob that is no
    longer accepted, it blows up here — which is what did not happen comparing strings.
    """
    assert registry.table_of(generated_model) is not None


@pytest.mark.parametrize(
    ("column", "check"),
    [
        ("codigo", lambda c: c.max_length == 20),
        ("quantity", lambda c: c.int_size is SnakeIntSize.SMALLINT),
        ("amount", lambda c: (c.precision, c.scale) == (12, 2)),
        ("meta", lambda c: c.json_storage is SnakeJsonStorage.JSON),
        ("ocurrio", lambda c: c.python_type is SnakeUtc),
        ("apertura", lambda c: c.python_type is datetime),
    ],
)
def test_each_parameter_survives_the_mirror(
    generated_model: type, column: str, check: object
) -> None:
    """Checks that each parameter read from the DB is still there after the trip through the file.

    Without this, the mirror could compile and WIDEN in silence: a `VARCHAR(20)` coming back as
    `TEXT` or a `SMALLINT` coming back as `BIGINT` breaks nothing visible, and corrupts the schema in
    the first migration anybody generates.
    """
    table = registry.table_of(generated_model)
    assert table is not None
    info = table.get_column(column)
    assert info is not None
    assert check(info)  # type: ignore[operator]
