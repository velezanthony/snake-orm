"""Tests of `RunSQL`: the DATA operation that emits raw SQL (up/down) without touching the schema.

`RunSQL` is the NON portable escape hatch: it runs statements bare. It verifies that `up_sql`
returns the statements of `up` (a str as a single one, a tuple as several), that `down_sql`
is `[]` when there is no reverse and the statements of `down` when there is, and that
`apply_to_state` is a NO-OP: a data migration mutates rows, not the tables of the abstract state.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import CreateTable, RunSQL
from snakeorm.migration.state import SchemaState


def test_run_sql_up_from_single_string() -> None:
    """An `up` made of a single string is emitted as ONE statement."""
    operation = RunSQL("UPDATE t SET x = 1")
    assert operation.up_sql(PostgresDialect()) == ["UPDATE t SET x = 1"]


def test_run_sql_up_from_tuple_keeps_order() -> None:
    """An `up` of several statements (a tuple) is emitted in order."""
    operation = RunSQL(("UPDATE t SET x = 1", "UPDATE t SET y = 2"))
    assert operation.up_sql(PostgresDialect()) == [
        "UPDATE t SET x = 1",
        "UPDATE t SET y = 2",
    ]


def test_run_sql_down_defaults_to_empty() -> None:
    """Without `down`, the SQL reverse is an empty list (nothing to undo at the SQL level)."""
    operation = RunSQL("UPDATE t SET x = 1")
    assert operation.down_sql(PostgresDialect()) == []


def test_run_sql_down_when_provided() -> None:
    """With `down`, the reverse emits its statements (str or tuple)."""
    operation = RunSQL("UPDATE t SET x = 1", down=("UPDATE t SET x = 0",))
    assert operation.down_sql(PostgresDialect()) == ["UPDATE t SET x = 0"]


def test_run_sql_does_not_touch_schema_state() -> None:
    """`apply_to_state` is a no-op: a data migration does NOT change the tables of the state."""
    state = SchemaState()
    id_col = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="t", columns=(id_col,), primary_key=SnakePrimaryKeyInfo(columns=(id_col,))
    )
    CreateTable(table).apply_to_state(state)
    before = list(state.tables())

    RunSQL("UPDATE t SET x = 1").apply_to_state(state)

    assert list(state.tables()) == before
