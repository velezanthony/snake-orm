"""Tests that db-first tells apart the TWO Postgres date types, which really are different.

`timestamp with time zone` and `timestamp without time zone` are not the same type: the first stores
an INSTANT (the moment, normalised, without the offset it was written with) and the second a WALL
CLOCK TIME, which identifies no moment at all until somebody says which zone it belongs to.

The introspector mapped BOTH of them to `datetime`. While `datetime` meant `TIMESTAMPTZ` that only
lost the zoneless case; ever since the type decides (`SnakeUtc` -> with zone, `datetime` -> without
it), collapsing them breaks the mirror from the other side: scaffolding a `TIMESTAMPTZ` column
produced a model that says `TIMESTAMP`.

And that failure is one of the expensive ones, because it does not blow up: the `scaffold` comes out
fine, the model compiles, and only a `drift` uncovers it — or the day somebody regenerates
migrations and sees an ALTER nobody asked for.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from snakeorm import PostgresDialect, SnakeUtc
from snakeorm.introspection.postgres import _PYTHON_TYPES
from snakeorm.metadata import SnakeColumnInfo
from snakeorm.migration.ddl import sql_type_of


@pytest.mark.parametrize(
    ("sql_read", "expected_python", "sql_reemitted"),
    [
        ("timestamp with time zone", SnakeUtc, "TIMESTAMPTZ"),
        ("timestamp without time zone", datetime, "TIMESTAMP"),
    ],
)
def test_each_timestamp_type_survives_the_mirror(
    sql_read: str, expected_python: type, sql_reemitted: str
) -> None:
    """Checks the DB -> Python -> DB round trip of each date type, without getting lost on the way.

    It is the only thing that truly proves the mirror is faithful: comparing only the Python type
    would let the collapse through, because both landed on `datetime` and "both are datetime" looked
    correct.
    """
    assert _PYTHON_TYPES[sql_read] is expected_python
    column = SnakeColumnInfo(name="when", python_type=_PYTHON_TYPES[sql_read])
    assert sql_type_of(column, PostgresDialect()) == sql_reemitted


def test_the_two_timestamp_types_do_not_collapse() -> None:
    """Checks that the two do NOT land on the same Python type.

    It is the check that was missing, and the one that would have caught the failure: while both
    were `datetime`, any test about "the type read" passed and the mirror lied all the same.
    """
    with_zone = _PYTHON_TYPES["timestamp with time zone"]
    without_zone = _PYTHON_TYPES["timestamp without time zone"]
    assert with_zone is not without_zone
