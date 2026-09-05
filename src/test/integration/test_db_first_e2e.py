"""The database-first road on the THREE engines: introspect, scaffold, and answer about drift.

The three introspectors had a file each, and that is how the road ends up walked on one engine and
assumed on the other two. It is one road: read the live catalogue into the SAME metadata shapes the
decorator builds, so everything downstream — scaffold, drift, DDL — works on it without knowing
where it came from.

The drift half carries a lesson the docstring of `drift()` spells out and that is worth running
rather than reading: comparing PYTHON types across this boundary compares something only one side
has. A `date` on SQLite is written as `TEXT`, and reading `TEXT` back can only ever answer `str`.
Both sides are right and they never match — drift once reported three differences against a database
the ORM had just built out of the very model it was comparing. Noise, from the one tool whose
SILENCE is the whole product.

So the assertion that matters here is the empty one: a schema the ORM has just created must drift by
NOTHING, on every engine.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from snakeorm import SnakeDriver
from snakeorm.introspection import (
    MySQLIntrospector,
    PostgresIntrospector,
    SnakeIntrospector,
    SQLiteIntrospector,
    drift,
)
from snakeorm.introspection.models import render_models
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.metadata.type_params import SnakeStrParams
from snakeorm.migration import emit_create_table
from test.scenarios.engines import DIALECTS, three_drivers

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]

_ID = SnakeColumnInfo(name="id", python_type=int)
_TABLE = SnakeTableInfo(
    name="dbf_clients",
    columns=(
        _ID,
        SnakeColumnInfo(
            name="name", python_type=str, type_params=SnakeStrParams(max_length=60)
        ),
        SnakeColumnInfo(name="visits", python_type=int, nullable=True),
    ),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
)


def _introspector(engine: str, driver: SnakeDriver) -> SnakeIntrospector:
    """The reader of each engine's catalogue. Three sources, one Protocol, one set of shapes."""
    if engine == "postgres":
        return PostgresIntrospector(driver)
    if engine == "mysql":
        return MySQLIntrospector(driver)
    return SQLiteIntrospector(driver)


@pytest.fixture
def drivers(tmp_path: pathlib.Path) -> Iterator[dict[str, SnakeDriver]]:
    """A driver per engine with the table CREATED BY THE ORM, so what is read back is what it wrote."""
    with three_drivers([], sqlite_path=str(tmp_path / "dbfirst.db")) as opened:
        for name, driver in opened.items():
            driver.execute(f"DROP TABLE IF EXISTS {_TABLE.name}", ())
            driver.execute(emit_create_table(_TABLE, DIALECTS[name]), ())
            driver.commit()
        try:
            yield opened
        finally:
            for driver in opened.values():
                driver.execute(f"DROP TABLE IF EXISTS {_TABLE.name}", ())
                driver.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_catalogue_comes_back_as_the_metadata_shapes(
    engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """Three catalogues, one answer: the table, its columns and its primary key.

    Reading only "a table came back" would pass on an introspector that found the name and nothing
    else, which is the shape a scaffold turns into an empty class.
    """
    tables = {
        table.name: table for table in _introspector(engine, drivers[engine]).tables()
    }

    assert _TABLE.name in tables, f"{engine} did not find the table it had just created"
    found = tables[_TABLE.name]
    assert {column.name for column in found.columns} >= {"id", "name", "visits"}
    assert found.primary_key is not None
    assert [column.name for column in found.primary_key.columns] == ["id"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_scaffold_writes_python_that_compiles(
    engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """What comes out is SOURCE, so the only honest check is to run it.

    `compile()` and not a string match: a scaffold that emitted a stray comma or forgot an import
    would still contain every name this test could look for.
    """
    tables = _introspector(engine, drivers[engine]).tables()
    ours = [table for table in tables if table.name == _TABLE.name]

    source = render_models(ours)

    compile(source, f"<scaffold {engine}>", "exec")
    assert "class" in source and _TABLE.name in source


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_schema_the_orm_just_built_drifts_by_nothing(
    engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """THE assertion of this file, and it is the EMPTY one.

    Drift is the tool whose silence is its product: a report that cries about a database the ORM
    itself created is noise, and noise is how a drift check stops being read at all.
    """
    live = _introspector(engine, drivers[engine]).tables()
    ours = [table for table in live if table.name == _TABLE.name]

    differences = drift([_TABLE], ours, DIALECTS[engine])

    assert differences == [], (
        f"{engine} reports drift against a schema it wrote itself: {differences}"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_column_the_code_does_not_declare_is_reported(
    engine: str, drivers: dict[str, SnakeDriver]
) -> None:
    """The other half: silence has to be earned, so a real difference must be seen.

    Without this the test above would pass on a `drift()` that returned `[]` for everything, which
    is the failure mode of every check whose good news is an empty list.
    """
    narrower = SnakeTableInfo(
        name=_TABLE.name,
        columns=_TABLE.columns[:2],
        primary_key=_TABLE.primary_key,
    )
    live = _introspector(engine, drivers[engine]).tables()
    ours = [table for table in live if table.name == _TABLE.name]

    differences = drift([narrower], ours, DIALECTS[engine])

    assert differences, f"{engine} saw no drift where a whole column is undeclared"
