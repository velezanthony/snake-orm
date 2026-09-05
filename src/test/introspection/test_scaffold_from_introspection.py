"""Test that the scaffolder compiles what the INTROSPECTOR produces, not what we hand it ourselves.

`test_scaffold_compiles.py` already wrote the generated module and imported it for real, which was
the right lesson. And even so two files that do not compile slipped past it, for a reason that
deserves writing down: it built its table by hand, giving EACH column its `type_params`. The real
introspector does not do that —for several types it returns `None`— so the test checked a scenario
the tool never produces.

The two that slipped through, both against a real Postgres:

    TIMESTAMPTZ  ->  ts: SnakeColumn[SnakeUtc] = snake_datetime()    <- does not even import
    NUMERIC      ->  n:  SnakeColumn[Decimal]  = snake_decimal()     <- `precision` is missing

The first because `_type_params` did not return date parameters, so the generator —which DOES look
at `with_timezone`— read the default and chose the zoneless declarator, contradicting the
annotation. The second because the declarator map sent every `Decimal` to `snake_decimal()`, which
demands `precision`, and an unconstrained `NUMERIC` does not have one.

That is why the input here comes out of `_PYTHON_TYPES` and `_type_params`, the SAME functions the
introspector uses: the test walks everything the tool can end up emitting. A new type goes into that
table and it goes into this test on its own, with nobody having to remember to add it.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest

from snakeorm.introspection.models import render_models
from snakeorm.introspection.postgres import _PYTHON_TYPES, _type_params
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)

# Values `information_schema` would return for each type. They only matter where the type carries
# them; the rest go to `None`, which is exactly what the database answers.
_LENGTH = {"character varying": 20, "character": 4}
_NUMERIC = {"numeric": (12, 2)}


def _columns() -> tuple[SnakeColumnInfo, ...]:
    """One column per EACH type the introspector can read, plus the unconstrained `numeric`.

    The `numeric` goes in twice on purpose: with precision and without it. They are different paths
    inside `_type_params` —one returns parameters and the other `None`— and only the second was broken.
    """
    columns = []
    for index, (data_type, python_type) in enumerate(sorted(_PYTHON_TYPES.items())):
        precision, scale = _NUMERIC.get(data_type, (None, None))
        columns.append(
            SnakeColumnInfo(
                name=f"c{index}",
                python_type=python_type,
                attr_name=f"c{index}",
                type_params=_type_params(
                    data_type, _LENGTH.get(data_type), precision, scale
                ),
            )
        )
    columns.append(
        SnakeColumnInfo(
            name="numeric_sin_restringir",
            python_type=_PYTHON_TYPES["numeric"],
            attr_name="numeric_sin_restringir",
            type_params=_type_params("numeric", None, None, None),
        )
    )
    return tuple(columns)


@pytest.fixture(scope="module")
def generated_module(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    """Writes the module the scaffolder produces for that table and IMPORTS it for real.

    MODULE scoped because importing it registers the model in the global registry; doing it once per
    test would clash with itself on the second go.
    """
    pk = SnakeColumnInfo(name="id", python_type=int, attr_name="id", autoincrement=True)
    table = SnakeTableInfo(
        name="mirror_introspectado",
        columns=(pk, *_columns()),
        primary_key=SnakePrimaryKeyInfo(columns=(pk,)),
    )
    dest = tmp_path_factory.mktemp("scaffold_introspeccion")
    (dest / "mirror_introspectado.py").write_text(
        render_models([table]), encoding="utf-8"
    )
    sys.path.insert(0, str(dest))
    try:
        yield importlib.import_module("mirror_introspectado")
    finally:
        sys.path.remove(str(dest))
        # The module STAYS in sys.modules on purpose: removing it would leave a registered model
        # whose module no longer exists, and the next `snake_link()` of ANY other test would blow up
        # with a NameError that has nothing to do with it.


def test_every_introspectable_type_scaffolds_into_a_module_that_imports(
    generated_module: ModuleType,
) -> None:
    """Checks that the generated file imports: it compiles through ALL the compiler guards.

    Importing it is what fires `@snake_db_first`. If the generator emits a declarator that
    contradicts the annotation, or one missing a mandatory argument, it blows up here — which is
    what did not happen while the input table was written by hand.
    """
    assert generated_module is not None


def test_a_timestamptz_scaffolds_the_zoned_declarator(
    generated_module: ModuleType,
) -> None:
    """Checks that a column WITH a zone comes out with `snake_datetimetz()`.

    It is the half the import alone does not prove: a mirror emitting both declarators the wrong way
    round would still compile —each one matches ITS annotation— and would describe the DB backwards.
    """
    source = render_models(
        [
            SnakeTableInfo(
                name="solo_fechas",
                columns=(
                    SnakeColumnInfo(
                        name="instante",
                        python_type=_PYTHON_TYPES["timestamp with time zone"],
                        attr_name="instante",
                        type_params=_type_params(
                            "timestamp with time zone", None, None, None
                        ),
                    ),
                    SnakeColumnInfo(
                        name="pared",
                        python_type=_PYTHON_TYPES["timestamp without time zone"],
                        attr_name="pared",
                        type_params=_type_params(
                            "timestamp without time zone", None, None, None
                        ),
                    ),
                ),
                primary_key=SnakePrimaryKeyInfo(columns=()),
            )
        ]
    )

    assert "instante: SnakeColumn[SnakeUtc] = snake_datetimetz()" in source
    assert "pared: SnakeColumn[datetime.datetime] = snake_datetime()" in source
