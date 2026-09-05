"""Changing a view's COLUMN NAMES is not something `CREATE OR REPLACE VIEW` can do, on any engine.

`AlterView` emitted a replacement and nothing else, on the reasoning that PostgreSQL and MySQL both
declare `Cap.REPLACE_VIEW`. They do — and the replacement still cannot rename an output column.
Measured against the real server:

    CREATE OR REPLACE VIEW v AS SELECT a, b FROM t WHERE a > 0   -> accepted
    CREATE OR REPLACE VIEW v AS SELECT a AS x, b FROM t          -> cannot change name of view
                                                                    column "a" to "x"

So it is NOT a capability question. The engine has the feature; the feature cannot express this
change. `Cap` answers "can this engine do X"; nothing was answering "can X express what is being
asked", and those are different questions that happened to agree until a view's projection changed.

WHERE IT SHOWED UP. Running the demos, after the `LowStock` view moved from `quantity` to `on_hand`.
The migration planned, the SQL emitted, and psycopg was what explained it — which is the same defect
this repository has now met at five different layers.

THE FIX IS TO DROP AND CREATE, and it is not a fallback for engines that lack something: it is what
the change REQUIRES, on every engine. So it is decided by comparing the two column lists, not by
asking the dialect what it supports.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTableKind,
)
from snakeorm.migration import AlterView


def _view(columns: tuple[str, ...], where: str) -> SnakeTableInfo:
    """A view over `t`, with the given projection and filter."""
    return SnakeTableInfo(
        name="v",
        columns=tuple(
            SnakeColumnInfo(name=name, python_type=int, attr_name=name)
            for name in columns
        ),
        primary_key=SnakePrimaryKeyInfo(columns=()),
        kind=SnakeTableKind.VIEW,
        view_definition=f"SELECT {', '.join(columns)} FROM t WHERE {where}",
    )


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect()],
    ids=["postgres", "mysql"],
)
def test_the_same_columns_are_replaced_in_one_statement(dialect: object) -> None:
    """A changed FILTER is what `CREATE OR REPLACE VIEW` is for: one statement, no drop."""
    before = _view(("a", "b"), "a > 0")
    after = _view(("a", "b"), "a > 10")

    statements = AlterView(before, after).up_sql(dialect)  # type: ignore[arg-type]

    assert len(statements) == 1, statements
    assert statements[0].upper().startswith("CREATE OR REPLACE VIEW")


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect(), SQLiteDialect()],
    ids=["postgres", "mysql", "sqlite"],
)
def test_renaming_a_column_drops_and_creates(dialect: object) -> None:
    """A changed PROJECTION cannot be replaced, so it is dropped and made again — on every engine.

    Including the two that declare `Cap.REPLACE_VIEW`: having the feature does not help, because the
    feature refuses this. That is the distinction this file exists for.
    """
    before = _view(("a", "b"), "a > 0")
    after = _view(("x", "b"), "a > 0")

    statements = AlterView(before, after).up_sql(dialect)  # type: ignore[arg-type]

    assert len(statements) == 2, statements
    assert statements[0].upper().startswith("DROP VIEW")
    assert statements[1].upper().startswith("CREATE VIEW")


def test_the_rollback_of_a_rename_also_drops_and_creates() -> None:
    """The reverse is the same shape: going back renames the column the other way.

    A `down_sql` that emitted a replacement would fail on rollback — the run nobody watches, and the
    one where a failure costs most.
    """
    before = _view(("a", "b"), "a > 0")
    after = _view(("x", "b"), "a > 0")

    statements = AlterView(before, after).down_sql(PostgresDialect())

    assert len(statements) == 2, statements
    assert statements[0].upper().startswith("DROP VIEW")
    assert statements[1].upper().startswith("CREATE VIEW")


def test_a_reordered_projection_also_drops_and_creates() -> None:
    """Order counts too: a view's columns are positional, so swapping two is a rename of both."""
    before = _view(("a", "b"), "a > 0")
    after = _view(("b", "a"), "a > 0")

    statements = AlterView(before, after).up_sql(PostgresDialect())

    assert len(statements) == 2, statements
