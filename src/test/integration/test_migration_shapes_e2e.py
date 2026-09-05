"""Autodetection, squash and `RebuildTable`, applied against the THREE engines.

The three had unit tests over the operation LIST, which is the right place to check what they
DECIDE. What none of them said is whether the decided operations actually run, and that is a
separate question with a separate answer per engine — a squash that folds correctly into DDL one
engine rejects has folded nothing useful.

`RebuildTable` is here on all three deliberately, and it is not padding. It exists because SQLite
cannot drop a column a foreign key names and has no `DROP CONSTRAINT` to clear the way; running it
on the other two proves the operation is not SQLite-shaped SQL wearing a portable name.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from dataclasses import replace

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.metadata import SnakeCheckInfo, SnakeColumnInfo
from snakeorm.metadata.type_params import SnakeStrParams
from snakeorm.migration import (
    AddColumn,
    CreateTable,
    Migration,
    MigrationRunner,
    RebuildTable,
    autodetect,
    squash,
)
from test.scenarios.engines import DIALECTS, three_drivers

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="msh_items")
class Item(SnakeModel):
    """Declared as a MODEL and not as raw metadata, because a CHECK needs a real condition.

    `SnakeCheckInfo` stores the `SnakeCondition` as an AST rather than emitted SQL — that is what
    keeps the metadata engine-agnostic and what lets the checker see `Item.id` — so there has to be
    a class for the condition to be written against.
    """

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=40)


_FIRST = snake_table(Item)
_NOTE = SnakeColumnInfo(
    name="note",
    python_type=str,
    type_params=SnakeStrParams(max_length=40),
    nullable=True,
)
_WIDER = replace(_FIRST, columns=(*_FIRST.columns, _NOTE))

_CREATE = Migration(version="0001_create", operations=(CreateTable(_FIRST),))
_WIDEN = Migration(version="0002_widen", operations=(AddColumn(_WIDER, _NOTE),))


@pytest.fixture
def runners(tmp_path: pathlib.Path) -> Iterator[dict[str, MigrationRunner]]:
    """A runner per engine over an empty database."""
    with three_drivers([], sqlite_path=str(tmp_path / "shapes.db")) as drivers:
        made = {
            name: MigrationRunner(driver, DIALECTS[name])
            for name, driver in drivers.items()
        }
        try:
            yield made
        finally:
            for driver in drivers.values():
                driver.execute(f"DROP TABLE IF EXISTS {_FIRST.name}", ())
                driver.execute("DROP TABLE IF EXISTS snake_migrations", ())
                driver.commit()


def test_autodetect_sees_the_new_column_and_nothing_else() -> None:
    """The diff is engine-independent by design: it compares the GRAPH, never the live database.

    That is the whole reason a migration is reproducible without a server, so this half has no
    `engine` parameter — asking it three times would be asking the same question three times.
    """
    operations = autodetect([_CREATE], [_WIDER])

    assert len(operations) == 1, f"expected one operation, got {operations}"
    assert type(operations[0]).__name__ == "AddColumn"


@pytest.mark.parametrize("engine", _ENGINES)
def test_what_autodetect_decided_actually_runs(
    engine: str, runners: dict[str, MigrationRunner]
) -> None:
    """The other half, and the one the unit test cannot make: the decision REACHES the engine.

    An `AddColumn` that every engine rejects is a correct decision and a useless one.
    """
    runner = runners[engine]
    runner.apply([_CREATE])

    detected = autodetect([_CREATE], [_WIDER])
    applied = runner.apply(
        [_CREATE, Migration(version="0002_detected", operations=tuple(detected))]
    )

    assert applied == ["0002_detected"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_squashed_history_lands_the_same_schema(
    engine: str, runners: dict[str, MigrationRunner]
) -> None:
    """Folding many migrations into one must leave the SAME state, which only the engine can say.

    The two histories are applied to the same engine one after the other — the second must find
    nothing left to do, which is the strongest statement of "the same state" available without
    reading the catalogue in three dialects.
    """
    runner = runners[engine]
    folded = squash([_CREATE, _WIDEN], version="0001_squashed")

    assert runner.apply([folded]) == ["0001_squashed"]

    detected = autodetect([folded], [_WIDER])

    assert detected == [], (
        f"{engine}: the squashed history did not land the same schema: {detected}"
    )


# -- `RebuildTable`: one operation, two spellings ---------------------------------------------------

_CHECKED = replace(
    _FIRST,
    checks=(SnakeCheckInfo(condition=Item.id > 0, name="ck_msh_items_positive"),),
)


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_constraint_change_applies_on_every_engine(
    engine: str, runners: dict[str, MigrationRunner]
) -> None:
    """`RebuildTable` says WHAT changes; each dialect decides how much work that costs.

    SQLite remakes the whole table because it has no `ALTER TABLE ADD CONSTRAINT` and never will;
    PostgreSQL and MySQL emit the minimal `ALTER`. Running it on the three is what proves the
    operation is portable rather than SQLite-shaped SQL wearing a portable name — and the file the
    user writes stays the same on all of them, which is the decision the operation exists for.
    """
    runner = runners[engine]
    runner.apply([_CREATE])

    applied = runner.apply(
        [
            _CREATE,
            Migration(
                version="0002_checked",
                operations=(RebuildTable(_FIRST, _CHECKED),),
            ),
        ]
    )

    assert applied == ["0002_checked"]
