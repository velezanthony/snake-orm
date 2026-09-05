"""The two halves of concurrency control, plus `NULLS FIRST/LAST`.

`FOR UPDATE` and the ISOLATION level are one single tool split in two: the lock says which rows you
reserve, isolation says what you see meanwhile. Having one without the other is having half of it,
and that is why they come together.

`NULLS FIRST/LAST` looks cosmetic until you sort by an optional column: Postgres puts NULLs LAST on
ascending and FIRST on descending, so an `ORDER BY` that flips direction also flips where the gaps
show up. Being able to say it is being able to not depend on that.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Nation

_DIALECT = PostgresDialect()


def _sql(query: SnakeQuery[Nation]) -> str:
    """The SQL emitted by the query."""
    return query.to_sql(_DIALECT)[0]


def test_nulls_last_is_explicit_in_the_sql() -> None:
    """Checks that `nulls_last()` gets written out, instead of trusting the engine's default."""
    assert _sql(SnakeQuery(Nation).order_by(Nation.name.asc().nulls_last())).endswith(
        'ORDER BY "name" ASC NULLS LAST'
    )


def test_nulls_first_works_with_descending_too() -> None:
    """Checks that the position of the NULLs is independent of the sort direction."""
    assert _sql(SnakeQuery(Nation).order_by(Nation.name.desc().nulls_first())).endswith(
        'ORDER BY "name" DESC NULLS FIRST'
    )


def test_without_asking_nothing_is_emitted() -> None:
    """Checks that nothing is written unless you ask for it: the default behaviour is not changed."""
    assert "NULLS" not in _sql(SnakeQuery(Nation).order_by(Nation.name.asc()))


def test_for_update_locks_the_selected_rows() -> None:
    """Checks that `for_update()` appends the locking clause at the end of the SELECT."""
    assert _sql(SnakeQuery(Nation).for_update()).endswith("FOR UPDATE")


def test_skip_locked_and_nowait_are_available() -> None:
    """Checks the two ways of not sitting there waiting, which is what a queue uses."""
    assert _sql(SnakeQuery(Nation).for_update(skip_locked=True)).endswith(
        "FOR UPDATE SKIP LOCKED"
    )
    assert _sql(SnakeQuery(Nation).for_update(nowait=True)).endswith(
        "FOR UPDATE NOWAIT"
    )


def test_nowait_and_skip_locked_are_mutually_exclusive() -> None:
    """Checks that asking for both is rejected: they are OPPOSITE answers to the same question.

    `NOWAIT` says "if it is locked, fail"; `SKIP LOCKED` says "if it is locked, skip it".
    Accepting both would force picking one of them in silence.
    """
    with pytest.raises(
        SnakeUnsupportedFeature, match="nowait and skip_locked are mutually exclusive"
    ):
        SnakeQuery(Nation).for_update(nowait=True, skip_locked=True)


def test_for_update_is_refused_on_a_view() -> None:
    """Checks the read-only guard: you do not lock the rows of a view."""
    from test.session.test_view_readonly import RoUserClasses

    with pytest.raises(
        SnakeUnsupportedFeature, match="there is nothing of its own to lock"
    ):
        SnakeQuery(RoUserClasses).for_update()


def test_the_query_stays_immutable() -> None:
    """Checks that `for_update()` returns a NEW query, like the rest of the builder."""
    base = SnakeQuery(Nation)
    locked = base.for_update()

    assert "FOR UPDATE" not in _sql(base)
    assert "FOR UPDATE" in _sql(locked)
    assert base is not locked


def test_for_update_goes_after_limit() -> None:
    """Checks the ORDER of the grammar: the lock goes at the end, after LIMIT/OFFSET."""
    sql = _sql(SnakeQuery(Nation).limit(5).for_update())
    assert sql.index("LIMIT") < sql.index("FOR UPDATE")
