"""Projecting an `as_scalar()` is refused, and the refusal has to be worth reading.

What came out was the emitter's catch-all for a node nobody registered a handler for:

    SnakeNodeError: Value expression cannot be emitted: SnakeSubquery

That names an INTERNAL class and stops. `SnakeSubquery` is not something a caller ever types — they
typed `.as_scalar(...)` — so the one word the message carries is the one word they cannot act on,
and it says neither what is wrong nor what to do instead.

One file away, the SAME subject already answers properly. `SnakeQuery.as_scalar` refuses a WHERE
that navigates with "the JOIN inside the subquery is not built yet; filter by direct columns": what
happened, why, and the way out. In an ORM whose doctrine is that the message is the product, two
refusals about one node cannot be written to two standards.

The reason is not a missing handler either, and the message has to say so or it will be read as an
oversight and "fixed" by wiring the node into the emitter. `SnakeSubquery` carries table, column and
WHERE — and no `LIMIT`. `IN (...)` asks about a SET, so many rows are the point; a column of a
SELECT is ONE value per row, and the same node projected answers `more than one row returned by a
subquery used as an expression` from the engine, at runtime, on production data.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeError, SnakeUnsupportedFeature
from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeSubquery
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Maker, Nation

snake_link()

_POSTGRES = PostgresDialect()


def _subquery() -> SnakeSubquery[str]:
    """The scalar subquery of the guide: one column, flat WHERE, used in `.in_()`."""
    return SnakeQuery(Maker).filter(Maker.nation_id == 1).as_scalar(Maker.name)


def test_projecting_it_names_the_operation_and_not_the_node() -> None:
    """The caller wrote `as_scalar` and `select`; the message has to be about those two."""
    query = SnakeQuery(Nation)

    with pytest.raises(SnakeError, match="as_scalar") as raised:
        query.to_project_sql(_POSTGRES, (Nation.name, _subquery()))

    message = str(raised.value)
    assert "SnakeSubquery" not in message, message
    assert "in_" in message, message


def test_it_says_why_and_not_only_that_it_cannot() -> None:
    """The reason is the missing LIMIT, and naming it is what stops the wrong fix.

    Without it the refusal reads as a handler somebody forgot, and the obvious repair — register the
    node in `emit_value` — ships a projection that the engine rejects the moment a parent has two
    children.
    """
    with pytest.raises(SnakeError, match="LIMIT"):
        SnakeQuery(Nation).to_project_sql(_POSTGRES, (_subquery(),))


def test_it_is_the_same_refusal_class_as_its_sibling_one_file_away() -> None:
    """`as_scalar` already answers `SnakeUnsupportedFeature` about this very node.

    Two spellings of "this shape is not supported yet" would be two things to catch for one
    situation, and the caller cannot see that they are one situation.
    """
    with pytest.raises(SnakeUnsupportedFeature, match="as_scalar"):
        SnakeQuery(Nation).to_project_sql(_POSTGRES, (_subquery(),))

    with pytest.raises(SnakeUnsupportedFeature, match="scalar subquery"):
        SnakeQuery(Maker).filter(Maker.nation.name == "x").as_scalar(Maker.name)


def test_ordering_by_one_is_refused_the_same_way() -> None:
    """The ORDER BY goes through the same emitter, so it must not fall back to the catch-all."""
    query = SnakeQuery(Nation).order_by(_subquery().desc())

    with pytest.raises(SnakeUnsupportedFeature, match="as_scalar"):
        query.to_project_sql(_POSTGRES, (Nation.name,))


def test_a_node_with_no_handler_at_all_still_gets_the_catch_all() -> None:
    """The generic message stays for what it is for: a node the emitter has never heard of.

    Replacing it would hide the next unregistered type behind a sentence about subqueries.
    """
    from snakeorm.core.exceptions import SnakeNodeError
    from snakeorm.sql.value import emit_value

    class _Unknown:
        """A value node nobody registered."""

    with pytest.raises(SnakeNodeError, match="_Unknown"):
        emit_value(_Unknown(), _POSTGRES, [])


def test_using_it_in_an_in_still_works() -> None:
    """The supported route is untouched: the refusal is about the column list, not the node."""
    query = SnakeQuery(Nation).filter(Nation.name.in_(_subquery()))

    sql, params = query.to_sql(_POSTGRES)

    assert 'IN (SELECT "name" FROM "public"."makers" WHERE "nation_id" = %s)' in sql, (
        sql
    )
    assert params == (1,)
