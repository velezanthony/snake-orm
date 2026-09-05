"""A VIEW whose body is a set operation, CREATED and QUERIED on the three engines.

`view_body()` renders `query=` in the target dialect, so a compound's body is written afresh per
engine — which is what made this worth measuring rather than reading. Two questions:

- Does the view CREATE and answer the same rows on the three? It does, and the annotation of
  `query=` said `SnakeQuery` all the same, so the only thing stopping a UNION view was the type.
- What happens on SQLite, where a branch cannot be parenthesised? A regrouping frozen INSIDE a
  `CREATE VIEW` would be the worst version of the bug: it survives the process that wrote it and
  every later reader inherits it. It does not happen — the refusal travels through `view_body`,
  because the body is compiled by the very same `to_sql` that guards it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_view,
)
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.migration.ddl import emit_create_view
from snakeorm.registry import registry
from test.scenarios.engines import DIALECTS, three_drivers

pytestmark = pytest.mark.integration


@snake_model(table="cview_tickets")
class ViewTicket(SnakeModel):
    """The table the views read. The middle band belongs to neither slice."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    kind: SnakeColumn[str] = snake_str(max_length=10)
    amount: SnakeColumn[int] = snake_int()


_CHEAP = SnakeQuery(ViewTicket).filter(ViewTicket.amount < 500)
_DEAR = SnakeQuery(ViewTicket).filter(ViewTicket.amount > 700)
_ODD = SnakeQuery(ViewTicket).filter(ViewTicket.kind == "odd")


@snake_view(query=_CHEAP.union(_DEAR), name="cview_edges")
class ViewEdges(SnakeModel):
    """The two ends of the range, as ONE view. No `# type: ignore`: that is half the point."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    kind: SnakeColumn[str] = snake_str(max_length=10)
    amount: SnakeColumn[int] = snake_int()


@snake_view(query=_CHEAP.union(_DEAR.except_(_ODD)), name="cview_nested")
class ViewNestedEdges(SnakeModel):
    """The same, with a set INSIDE the right branch: inexpressible where branches take no parens."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    kind: SnakeColumn[str] = snake_str(max_length=10)
    amount: SnakeColumn[int] = snake_int()


snake_link()

_ROWS = ((1, "even", 100), (2, "odd", 600), (3, "odd", 900), (4, "even", 800))
_DROP_VIEW = "DROP VIEW IF EXISTS %s"


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The THREE engines with the table seeded and both views created where they can be.

    The views are created HERE and not by a migration: what is under test is the body the emitter
    writes, and going through the planner would put another suspect between the two.
    """
    with three_drivers([ViewTicket]) as drivers:
        sessions = {
            name: SnakeSession(driver, DIALECTS[name])
            for name, driver in drivers.items()
        }
        for session in sessions.values():
            session.add_all([ViewTicket(id=i, kind=k, amount=a) for i, k, a in _ROWS])
            session.commit()
        for name, driver in drivers.items():
            for model in (ViewEdges, ViewNestedEdges):
                view = registry.table_of(model)
                assert view is not None
                try:
                    driver.execute(emit_create_view(view, DIALECTS[name]), ())
                except SnakeEmitError:
                    continue  # the engine cannot write this body; the test below says which
            driver.commit()
        try:
            yield sessions
        finally:
            for name, driver in drivers.items():
                for view_name in ("cview_nested", "cview_edges"):
                    driver.execute(_DROP_VIEW % view_name, ())
                driver.commit()


def test_a_view_whose_body_is_a_union_answers_the_same_rows_on_the_three_engines(
    engines: dict[str, SnakeSession],
) -> None:
    """The view is created and queried on the three, and gives back the union's rows.

    The middle band (id 2, at 600) is in neither branch, so a view that quietly widened to the whole
    table would be caught here rather than passing on a row count.
    """
    answers = {
        name: sorted(row.id for row in session.all(SnakeQuery(ViewEdges)))
        for name, session in engines.items()
    }

    assert answers == {"sqlite": [1, 3, 4], "postgres": [1, 3, 4], "mysql": [1, 3, 4]}


def test_a_view_body_the_engine_cannot_group_is_refused_instead_of_being_frozen_wrong(
    engines: dict[str, SnakeSession],
) -> None:
    """SQLite REFUSES to write a nested set as a view body; the other two write it and agree.

    This is the one that had to be measured. Were the compound emitted unparenthesised into the
    `CREATE VIEW`, SQLite's left-to-right regrouping would be baked into the schema and every later
    read would inherit it, with nothing left to compare against.
    """
    view = registry.table_of(ViewNestedEdges)
    assert view is not None

    with pytest.raises(SnakeEmitError, match="reads the operators left to right"):
        emit_create_view(view, DIALECTS["sqlite"])

    answers = {
        name: sorted(row.id for row in engines[name].all(SnakeQuery(ViewNestedEdges)))
        for name in ("postgres", "mysql")
    }
    assert answers == {"postgres": [1, 4], "mysql": [1, 4]}
