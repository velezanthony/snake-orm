"""Tests of session.call(): calls a DATABASE FUNCTION returning rows into a DECLARED shape.

It is tested with a FAKE driver (no Postgres): the shape of the emitted SQL
(`SELECT * FROM name(%s, ...)`), that the ARGS ALWAYS travel parametrised (never inside the string),
that each row maps onto the @snake_row by POSITION, and that each column is coerced to the declared
type of the field (Decimal→float, str→UUID). The contract is DECLARED, not verified: the ORM
hydrates into the shape the user asks for, it does not check that the function exists or returns
that.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from decimal import Decimal
from uuid import UUID

import pytest

from snakeorm.decorators import SnakeRow, snake_row
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeEmitError, SnakeModelDefinitionError
from snakeorm.session import SnakeSession


class _FakeDriver:
    """Fake driver: it returns canned rows and records the SQL it ran (no database)."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[str, Sequence[object]]] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        return self.rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append((sql, params))
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:  # pragma: no cover
        ...

    def rollback(self) -> None:  # pragma: no cover
        ...

    def savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def release_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def rollback_to_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover
        ...


@snake_row
class _Payroll(SnakeRow):
    """Declared row: the `net` field is a float even though the database returns NUMERIC (Decimal)."""

    employee_id: int
    gross: Decimal
    net: float


@snake_row
class _Badge(SnakeRow):
    """Declared row with a UUID: psycopg2 hands it over as str; the ORM coerces it to UUID."""

    label: str
    token: UUID


def test_call_emits_select_from_function_with_placeholders() -> None:
    """Emits `SELECT * FROM name(%s, %s)` with one placeholder per argument."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.call("calcular_nomina", [1234, 2025], into=_Payroll)
    sql, _ = driver.calls[0]
    assert sql == "SELECT * FROM calcular_nomina(%s, %s)"


def test_call_passes_args_parametrized_never_interpolated() -> None:
    """The ARGS are user data: they travel as params, NEVER interpolated into the string."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.call("f", ["'; DROP TABLE users; --", 7], into=_Payroll)
    sql, params = driver.calls[0]
    assert sql == "SELECT * FROM f(%s, %s)"
    assert list(params) == ["'; DROP TABLE users; --", 7]


def test_call_with_no_args_emits_empty_parentheses() -> None:
    """With no arguments it emits `SELECT * FROM name()` (empty parentheses, no placeholders)."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.call("dashboard", [], into=_Payroll)
    sql, params = driver.calls[0]
    assert sql == "SELECT * FROM dashboard()"
    assert list(params) == []


def test_call_maps_rows_to_the_declared_dataclass_by_position() -> None:
    """Each driver row maps onto the @snake_row by POSITION (field order == column order)."""
    driver = _FakeDriver(
        rows=[(1, Decimal("2000"), 1600.0), (2, Decimal("3000"), 2400.0)]
    )
    session = SnakeSession(driver, PostgresDialect())
    rows = session.call("calcular_nomina", [], into=_Payroll)
    assert [r.employee_id for r in rows] == [1, 2]
    assert isinstance(rows[0], _Payroll)


def test_call_coerces_numeric_to_float_when_declared_float() -> None:
    """A field declared float gets the NUMERIC (Decimal) coerced to float (source: the type)."""
    driver = _FakeDriver(rows=[(1, Decimal("2000"), Decimal("1600.50"))])
    session = SnakeSession(driver, PostgresDialect())
    [row] = session.call("calcular_nomina", [], into=_Payroll)
    assert row.net == 1600.50
    assert isinstance(row.net, float)


def test_call_coerces_str_to_uuid_when_declared_uuid() -> None:
    """A field declared UUID gets the str psycopg2 hands over coerced to uuid.UUID."""
    token = "12345678-1234-5678-1234-567812345678"
    driver = _FakeDriver(rows=[("alpha", token)])
    session = SnakeSession(driver, PostgresDialect())
    [row] = session.call("emitir_credencial", [], into=_Badge)
    assert row.token == UUID(token)
    assert isinstance(row.token, UUID)


def test_call_with_a_non_row_class_raises_clearly() -> None:
    """`into=` with a class that is not a @snake_row fails loudly (it is not a valid row holder)."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(SnakeModelDefinitionError, match="is not a @snake_row"):
        session.call("f", [], into=object)  # type: ignore[type-var]


def test_call_rejects_a_row_of_wrong_width() -> None:
    """A row with a different number of columns than declared fields fails loudly (positional map).

    It is checked against the SINGLE message both sessions share. Each one used to have its own
    —"devolvió N columna(s) pero" against "devuelve N columna(s) y"— and this test pinned the
    synchronous one down, which meant it protected the drift instead of catching it.
    """
    driver = _FakeDriver(
        rows=[(1, Decimal("2000"))]
    )  # columns missing for _Payroll (3 fields)
    session = SnakeSession(driver, PostgresDialect())
    with pytest.raises(SnakeEmitError, match="the mapping is positional"):
        session.call("calcular_nomina", [], into=_Payroll)


def test_execute_procedure_emits_call_and_returns_nothing() -> None:
    """execute_procedure emits `CALL name(%s)` (a PROCEDURE returning no rows) and returns nothing."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.execute_procedure(
        "recalcular_saldos", [42]
    )  # it returns nothing (a PROCEDURE CALL)
    sql, params = driver.calls[0]
    assert sql == "CALL recalcular_saldos(%s)"
    assert list(params) == [42]
