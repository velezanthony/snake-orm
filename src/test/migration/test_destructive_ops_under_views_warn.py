"""The warning that moves the discovery from the DEPLOY to the moment somebody is writing.

WHY IT EXISTS. `RebuildTable` no longer carries a `views=` payload, and it should not: a
`SnakeTriggerInfo` has a `.table`, so "the triggers of this table" is a fact the state answers,
while nothing anywhere says which TABLES a view reads. Without the payload the failure only shows up
when the migration is APPLIED — that is, during a deploy, with the author already on something else.
This is the same knowledge said earlier, at `makemigrations`, when there is a person in front of it.

THE CONDITION IS DOUBLE, AND THAT IS THE WHOLE DESIGN. It takes a destructive operation over a table
— `RebuildTable` or `DropTable` — AND at least one standing view. A migration that only adds columns
says nothing however many views the schema has, and a migration that drops ten tables says nothing
in a schema with no views. A warning that fires on every run is a warning people learn to skip past,
and the two silent cases below are what stop that from happening.

THE TWO DESTRUCTIONS FAIL DIFFERENTLY, which is why both are in. A rebuild ends in a `RENAME` that
reparses the whole schema, so a view reading the table makes the migration fail — loud. A
`DropTable` is worse: SQLite resolves views lazily, so the drop succeeds and leaves the view
DANGLING, and nothing says so until somebody queries it.

WHAT THE MESSAGE MAY NOT DO IS CLAIM TO KNOW WHICH VIEW READS WHICH TABLE. It states two sets — the
tables being destroyed and the views standing — says out loud that pairing them is the reader's job
and why the ORM cannot do it, and names what to write if the pairing is real. Nothing is searched
inside the view's SQL text: that would be a heuristic that fails open while the message claimed
otherwise, which is the shape of net this repository deletes.
"""

from __future__ import annotations

import dataclasses

from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTableKind,
)
from snakeorm.migration import (
    AddColumn,
    CreateTable,
    DropTable,
    RebuildTable,
    SnakeOperation,
    standing_view_warning,
)

_ID = SnakeColumnInfo(name="id", python_type=int, attr_name="id")
_QTY = SnakeColumnInfo(name="qty", python_type=int, attr_name="qty")
_NOTE = SnakeColumnInfo(name="note", python_type=str, attr_name="note", nullable=True)

_STOCK = SnakeTableInfo(
    name="dvw_stock",
    columns=(_ID, _QTY),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    checks=(
        SnakeCheckInfo(
            name="ck_dvw_stock_qty", condition=SnakeExpr[int](path=("qty",)) >= 0
        ),
    ),
)
_TIGHTER = dataclasses.replace(
    _STOCK,
    checks=(
        SnakeCheckInfo(
            name="ck_dvw_stock_qty", condition=SnakeExpr[int](path=("qty",)) >= 1
        ),
    ),
)
_LOW_STOCK = SnakeTableInfo(
    name="dvw_low_stock",
    columns=(_ID, _QTY),
    primary_key=SnakePrimaryKeyInfo(columns=()),
    kind=SnakeTableKind.VIEW,
    view_definition="SELECT id, qty FROM dvw_stock WHERE qty < 10",
)


def test_a_rebuild_with_views_standing_warns_and_names_both_sides() -> None:
    """Verifies the rebuild case says which table is remade and which views are up.

    Two names in one sentence is what makes the warning actionable: without the table the reader
    does not know what to look at, and without the views they do not know what to read.
    """
    message = standing_view_warning(
        [RebuildTable(_STOCK, _TIGHTER)], [_STOCK, _LOW_STOCK]
    )

    assert "dvw_stock" in message
    assert "dvw_low_stock" in message
    assert "DropView" in message
    assert "CreateView" in message


def test_a_drop_table_with_views_standing_warns_the_same_way() -> None:
    """Verifies the silent half is covered: a dropped table leaves a view dangling, not failing.

    SQLite resolves a view lazily, so the `DROP TABLE` goes through and the damage surfaces the next
    time somebody queries the view. That is worse than the rebuild, not milder.
    """
    message = standing_view_warning([DropTable(_STOCK)], [_STOCK, _LOW_STOCK])

    assert "dvw_stock" in message
    assert "dvw_low_stock" in message


def test_a_destructive_plan_with_no_views_standing_says_nothing() -> None:
    """Verifies a rebuild in a schema without views is silent: there is nothing to look at."""
    assert standing_view_warning([RebuildTable(_STOCK, _TIGHTER)], [_STOCK]) == ""


def test_a_plan_that_destroys_nothing_says_nothing_even_under_views() -> None:
    """Verifies adding a column stays quiet however many views stand over the schema.

    This is the half that keeps the warning worth reading. A message that appeared on every
    `makemigrations` would be scrolled past, and the day it mattered nobody would see it.
    """
    plan: list[SnakeOperation] = [CreateTable(_STOCK), AddColumn(_STOCK, _NOTE)]

    assert standing_view_warning(plan, [_STOCK, _LOW_STOCK]) == ""


def test_the_message_never_claims_to_know_which_view_reads_the_table() -> None:
    """Verifies it says the pairing is the reader's, and says WHY the ORM cannot make it.

    The value of this warning is that it promises nothing it cannot keep. If it ever started naming
    "the view that reads dvw_stock", it would be guessing from SQL text and would go silent on every
    view it could not parse — a net that fails open under a name that says otherwise.
    """
    message = standing_view_warning(
        [RebuildTable(_STOCK, _TIGHTER)], [_STOCK, _LOW_STOCK]
    )

    assert "cannot tell you which of those views read those tables" in message
    assert "sql=" in message
    assert "yours to make" in message
