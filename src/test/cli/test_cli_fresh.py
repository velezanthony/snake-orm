"""`fresh` against a REAL SQLite: the wipe order has to come from the KEYS, not from the source file.

`_cmd_fresh` handed `drop_all_sql` the tables of `current_schema()` reversed, and
`current_schema()` returns them in the order the `@snake_model` decorators ran — which is the order
somebody typed the classes in. Reversed declaration order is topological order only by coincidence:
it happens to be right whenever a model is declared after everything it points at, and a forward
reference (`SnakeToOne["Parent"]`, which the ORM supports precisely so the classes can be written in
any order) is enough to break it.

Nothing said so. On Postgres the `CASCADE` hides it and on MySQL the session switch hides it, so the
accident only surfaces on SQLite — with `FOREIGN KEY constraint failed` out of the one command whose
whole job is to leave nothing behind, halfway through, after it has already dropped some of the
tables.

SQLite is the engine under test here on purpose, and it needs no server: it is the one that tells
the truth about the order.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from snakeorm.cli import main
from snakeorm.cli.app import _prepare_models, _wipe_order
from snakeorm.migration import current_schema
from snakeorm.registry import registry

_PARENT = "fresh_parent"
_CHILD = "fresh_child"
_DB_ENV = "SNAKEORM_FRESH_DB"

_MODELS_SOURCE = f'''\
"""The child is declared FIRST, so declaration order is NOT the order they can be dropped in."""

from __future__ import annotations

import os

from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.contrib.config import SnakeOrmConfig
from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_to_one
from snakeorm.model import SnakeModel


@snake_model(table="{_CHILD}")
class Child(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    parent_id: SnakeColumn[int] = snake_int()
    parent: SnakeToOne["Parent"] = snake_to_one(parent_id)


@snake_model(table="{_PARENT}")
class Parent(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)


CONFIG = SnakeOrmConfig(
    databases={{
        "default": SnakeConnectionConfig(
            backend=SnakeBackend.SQLITE, name=os.environ["{_DB_ENV}"]
        )
    }}
)
'''

_CYCLE_SOURCE = '''\
"""Two tables pointing at each other: a graph with no drop order at all."""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_to_one
from snakeorm.model import SnakeModel


@snake_model(table="cycle_alpha")
class Alpha(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    beta_id: SnakeColumn[int | None] = snake_int()
    beta: SnakeToOne[Beta | None] = snake_to_one(beta_id)


@snake_model(table="cycle_beta")
class Beta(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    alpha_id: SnakeColumn[int | None] = snake_int()
    alpha: SnakeToOne[Alpha | None] = snake_to_one(alpha_id)
'''


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the global registry: empty at the start, restored at the end (monkeypatch)."""
    monkeypatch.setattr(registry, "_tables", {})
    monkeypatch.setattr(registry, "_by_name", {})
    monkeypatch.setattr(registry, "_model_by_name", {})
    monkeypatch.setattr(registry, "_table_owner", {})


def _install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    source: str = _MODELS_SOURCE,
) -> None:
    """Writes a models module into tmp_path, makes it importable and registers its models."""
    (tmp_path / f"{module_name}.py").write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv(_DB_ENV, str(tmp_path / "fresh.db"))
    monkeypatch.setenv("SNAKEORM_CONFIG", module_name)


def _rows(database: Path, table: str) -> int:
    """How many rows a table holds, read with a bare `sqlite3` outside the CLI's connection."""
    connection = sqlite3.connect(database)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def test_declaration_order_is_not_the_drop_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """The premise, measured: the child is registered BEFORE the parent it points at.

    Without this the rest of the file would be testing a scenario that cannot happen. Reversed, this
    declaration order puts the referenced table first — which is the order that fails.
    """
    _install(tmp_path, monkeypatch, "fresh_order_premise")
    _prepare_models("fresh_order_premise")

    declared = [table.name for table in current_schema()]

    assert declared == [_CHILD, _PARENT]
    assert list(reversed(declared)) == [_PARENT, _CHILD]


def test_the_wipe_order_puts_the_key_holder_before_the_table_it_points_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """`_wipe_order` derives the order from the FKs, so it is the same whoever typed what first."""
    _install(tmp_path, monkeypatch, "fresh_order_derived")
    _prepare_models("fresh_order_derived")

    order = _wipe_order(current_schema())

    assert order.index(_CHILD) < order.index(_PARENT)


def test_a_cycle_of_keys_still_yields_an_order_to_hand_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_registry: None
) -> None:
    """Two tables pointing at each other cannot be ordered, and `fresh` must not abort over it.

    There is no order to find, so refusing would break a wipe that Postgres (CASCADE) and MySQL (the
    session switch) both perform today — and that SQLite performs too now that its dialect defers
    the check to the COMMIT. What comes back is the tables, unordered rather than un-emitted.
    """
    _install(tmp_path, monkeypatch, "fresh_order_cycle", source=_CYCLE_SOURCE)
    _prepare_models("fresh_order_cycle")

    order = _wipe_order(current_schema())

    assert sorted(order) == ["cycle_alpha", "cycle_beta"]


def test_fresh_wipes_a_schema_whose_declaration_order_is_not_topological(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_registry: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end on a real SQLite: `fresh` empties and rebuilds, rows and all.

    The rows are what arm the trap. `DROP TABLE` on a referenced table runs an implicit delete of
    its rows, and that is what the key objects to — so an empty database comes through any order and
    proves nothing.
    """
    _install(tmp_path, monkeypatch, "fresh_models_wipe")
    migrations = tmp_path / "migrations"
    database = Path(os.environ[_DB_ENV])
    assert (
        main(
            [
                "makemigrations",
                "--models",
                "fresh_models_wipe",
                "--dir",
                str(migrations),
                "--name",
                "initial",
            ]
        )
        == 0
    )
    assert (
        main(["migrate", "--models", "fresh_models_wipe", "--dir", str(migrations)])
        == 0
    )
    connection = sqlite3.connect(database)
    connection.execute(f"INSERT INTO {_PARENT} (id) VALUES (1)")
    connection.execute(f"INSERT INTO {_CHILD} (id, parent_id) VALUES (1, 1)")
    connection.commit()
    connection.close()
    capsys.readouterr()

    code = main(["fresh", "--models", "fresh_models_wipe", "--dir", str(migrations)])

    assert code == 0
    assert "Database recreated from scratch: 1 migration(s) applied." in (
        capsys.readouterr().out
    )
    assert _rows(database, _PARENT) == 0  # the tables are back...
    assert _rows(database, _CHILD) == 0  # ...and empty
