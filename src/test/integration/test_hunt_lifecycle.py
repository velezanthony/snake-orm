"""HUNT 3 — the life of a schema over TIME: change the model and migrate again.

Everything tested so far is born from an empty state. A real project does the opposite: it
migrates, changes the model, migrates again. That is where the `replay` of the history has to
reconstruct EXACTLY what is there.

The contract being chased: after applying the diff, diffing again must produce NOTHING.
Converging is not a detail: if it does not converge, every `makemigrations` generates the SAME
migration forever and the history fills up with noise that on top of that gets applied.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from enum import StrEnum

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import PostgresDialect, PsycopgDriver
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeDecimalParams,
    SnakeEnumStorage,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import SchemaState, diff_schema, emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)


class State(StrEnum):
    """Enum that gets a value added to it halfway through its life."""

    NEW = "new"
    DONE = "done"


def _table(
    columns: tuple[SnakeColumnInfo, ...] = (),
    indexes: tuple[SnakeIndexInfo, ...] = (),
    checks: tuple[SnakeCheckInfo, ...] = (),
) -> SnakeTableInfo:
    """The `lifecycle` table with whatever is handed to it."""
    return SnakeTableInfo(
        name="lifecycle",
        columns=(_ID, *columns),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        indexes=indexes,
        checks=checks,
    )


def _pending(before: SnakeTableInfo, after: SnakeTableInfo) -> list[str]:
    """Operations left PENDING after applying the diff. Empty = it converged."""
    state = SchemaState()
    for operation in diff_schema([], [before]):
        operation.apply_to_state(state)
    for operation in diff_schema(state.tables(), [after]):
        operation.apply_to_state(state)
    return [type(op).__name__ for op in diff_schema(state.tables(), [after])]


def test_adding_a_column_converges() -> None:
    """Baseline: the simplest case has to converge."""
    assert (
        _pending(_table(), _table((SnakeColumnInfo(name="name", python_type=str),)))
        == []
    )


def test_adding_an_index_converges() -> None:
    """Checks that once the index is created, the diff does not propose it again."""
    column = SnakeColumnInfo(name="name", python_type=str)
    assert (
        _pending(
            _table((column,)),
            _table((column,), indexes=(SnakeIndexInfo(columns=("name",)),)),
        )
        == []
    )


def test_adding_a_partial_index_converges() -> None:
    """A PARTIAL index holds a CONDITION, and conditions do not compare by equality."""
    column = SnakeColumnInfo(name="borrado", python_type=int, nullable=True)
    index = SnakeIndexInfo(
        columns=("borrado",), where=SnakeExpr[int](path=("borrado",)).is_null()
    )
    assert _pending(_table((column,)), _table((column,), indexes=(index,))) == []


def test_adding_a_check_converges() -> None:
    """Same for the CHECKs, which also hold a condition."""
    column = SnakeColumnInfo(name="age", python_type=int)
    check = SnakeCheckInfo(condition=SnakeExpr[int](path=("age",)) >= 18)
    assert _pending(_table((column,)), _table((column,), checks=(check,))) == []


def test_adding_a_value_to_an_enum_converges() -> None:
    """THE DAY 2 CASE: adding a value to the enum changes its derived CHECK."""
    column = SnakeColumnInfo(
        name="state",
        python_type=State,
        enum_type=State,
        enum_storage=SnakeEnumStorage.CHECK,
    )
    old = SnakeCheckInfo(condition=SnakeExpr[str](path=("state",)).in_(("new", "done")))
    new = SnakeCheckInfo(
        condition=SnakeExpr[str](path=("state",)).in_(("new", "done", "cancelled"))
    )
    before = _table((column,), checks=(old,))
    after = _table((column,), checks=(new,))

    # ONE operation and not the old `DropCheck` + `AddCheck` pair: the CHECK is this table's only
    # change, and a constraint on a table that already exists is what SQLite can only alter by
    # remaking the table. The drop and the add are still there — they are the two statements the
    # rebuild emits where the engine has `ALTER TABLE ... ADD CONSTRAINT`.
    assert [type(op).__name__ for op in diff_schema([before], [after])] == [
        "RebuildTable"
    ]
    assert _pending(before, after) == []


def test_adding_a_comment_converges() -> None:
    """Documenting a column is a schema change; it has to converge as well."""
    assert (
        _pending(
            _table((SnakeColumnInfo(name="name", python_type=str),)),
            _table(
                (SnakeColumnInfo(name="name", python_type=str, db_comment="The name"),)
            ),
        )
        == []
    )


def test_changing_the_precision_converges() -> None:
    """The precision is detected in the diff; whether it also converges is another question."""
    assert (
        _pending(
            _table(
                (
                    SnakeColumnInfo(
                        name="total",
                        python_type=Decimal,
                        type_params=SnakeDecimalParams(precision=10, scale=2),
                    ),
                )
            ),
            _table(
                (
                    SnakeColumnInfo(
                        name="total",
                        python_type=Decimal,
                        type_params=SnakeDecimalParams(precision=12, scale=2),
                    ),
                )
            ),
        )
        == []
    )


@pytest.fixture
def driver() -> Iterator[PsycopgDriver]:
    """Real driver for the life cycle actually applied for real."""
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    connection.execute("DROP TABLE IF EXISTS lifecycle CASCADE", ())
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute("DROP TABLE IF EXISTS lifecycle CASCADE", ())
        connection.commit()
        connection.close()


def test_the_second_migration_applies_on_top_of_the_first(
    driver: PsycopgDriver,
) -> None:
    """The real cycle APPLIED: create, evolve the model and migrate on top breaking nothing."""
    column = SnakeColumnInfo(name="state", python_type=str)
    initial = _table((column,))
    driver.execute(emit_create_table(initial, _DIALECT), ())
    driver.commit()

    evolved = _table(
        (column, SnakeColumnInfo(name="priority", python_type=int, nullable=True)),
        indexes=(SnakeIndexInfo(columns=("state",)),),
        checks=(SnakeCheckInfo(condition=SnakeExpr[str](path=("state",)) != ""),),
    )
    for operation in diff_schema([initial], [evolved]):
        for sql in operation.up_sql(_DIALECT):
            driver.execute(sql, ())
    driver.commit()

    columns = {
        str(row[0])
        for row in driver.fetch_all(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'lifecycle'",
            (),
        )
    }
    assert "priority" in columns
