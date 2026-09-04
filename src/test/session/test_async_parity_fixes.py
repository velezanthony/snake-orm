"""Sync/async parity on two paths the review found DIVERGENT.

Decision D3 says both sessions must take the SAME decisions. The review found two places where they
did not: (1) `add_all` of a PK-only model fell back to `DEFAULT VALUES` in sync but blew up in async;
(2) `update` validated the `Decimal` scale in sync but not in async (silent truncation). Both were
fixed by sharing the path; these tests pin the parity down so that it cannot open up again.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeColumn,
    SnakeModel,
    SnakeSession,
    SnakeValueError,
    SnakeWarning,
    snake_auto,
    snake_decimal,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.session import AsyncSession
from snakeorm.session import shared as session_mod

_DIALECT = PostgresDialect()


@snake_model(table="apf_solo_pk")
class SoloPk(SnakeModel):
    """Autoincrement PK only: the `DEFAULT VALUES` case."""

    id: SnakeColumn[int] = snake_auto()


@snake_model(table="apf_dinero")
class Dinero(SnakeModel):
    """A Decimal column with a scale, to exercise the validation on update."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    amount: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)


class _DriverSync:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def fetch_all(self, sql: str, params: object = ()) -> list[tuple[object, ...]]:
        self.sql.append(sql)
        return [(1,)]

    def execute(self, sql: str, params: object = ()) -> int:
        self.sql.append(sql)
        return 1

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class _DriverAsync:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def fetch_all(
        self, sql: str, params: object = ()
    ) -> list[tuple[object, ...]]:
        self.sql.append(sql)
        return [(1,)]

    async def execute(self, sql: str, params: object = ()) -> int:
        self.sql.append(sql)
        return 1

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...


def test_add_all_of_a_pk_only_model_emits_default_values_in_both_sessions() -> None:
    """Verifies that `add_all` of a PK-only model emits `DEFAULT VALUES` in sync AND in async."""
    sync_driver = _DriverSync()
    SnakeSession(sync_driver, _DIALECT).add_all([SoloPk(), SoloPk()])  # type: ignore[arg-type]

    async_driver = _DriverAsync()

    async def action() -> None:
        await AsyncSession(async_driver, _DIALECT).add_all([SoloPk(), SoloPk()])  # type: ignore[arg-type]

    asyncio.run(action())

    assert all("DEFAULT VALUES" in s for s in sync_driver.sql)
    assert async_driver.sql == sync_driver.sql  # SAME SQL: parity is the contract


def test_update_validates_decimal_scale_in_both_sessions() -> None:
    """Verifies that a Decimal with more decimals than the scale is refused in sync AND in async."""
    row = Dinero(id=1, amount=Decimal("1.23"))
    row.amount = Decimal("9.9999")  # 4 decimals over a scale of 2

    with pytest.raises(SnakeValueError, match="decimal"):
        SnakeSession(_DriverSync(), _DIALECT).update(row)  # type: ignore[arg-type]

    async def action() -> None:
        await AsyncSession(_DriverAsync(), _DIALECT).update(row)  # type: ignore[arg-type]

    with pytest.raises(SnakeValueError, match="decimal"):
        asyncio.run(action())


@snake_model(table="apf_sin_returning")
class WithoutReturning(SnakeModel):
    """Autoincrement PK plus one column, for the path of an engine without RETURNING."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(max_length=20)


class _DriverWithId:
    """Phoney driver that DOES return a `last_insert_id`, the way MySQL would."""

    def __init__(self) -> None:
        self.sql: list[str] = []

    def fetch_all(self, sql: str, params: object = ()) -> list[tuple[object, ...]]:
        self.sql.append(sql)
        return []

    def execute(self, sql: str, params: object = ()) -> int:
        self.sql.append(sql)
        return 1

    @property
    def last_insert_id(self) -> int:
        return 42

    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class _DriverWithIdAsync(_DriverWithId):
    """The SAME double, awaiting. `last_insert_id` is NOT async: the cursor already stored it."""

    async def fetch_all(  # type: ignore[override]
        self, sql: str, params: object = ()
    ) -> list[tuple[object, ...]]:
        self.sql.append(sql)
        return []

    async def execute(self, sql: str, params: object = ()) -> int:  # type: ignore[override]
        self.sql.append(sql)
        return 1

    async def commit(self) -> None: ...  # type: ignore[override]
    async def rollback(self) -> None: ...  # type: ignore[override]
    async def close(self) -> None: ...


def test_add_fills_the_autoincrement_pk_from_last_insert_id_in_both_sessions() -> None:
    """Verifies that on an engine WITHOUT RETURNING BOTH sessions fill the PK from `last_insert_id`.

    It is the exact silent failure the Protocol member was added to avoid, sneaking in one layer
    further up: `AsyncDriver` already declared `last_insert_id`, but the async session never called
    it. So in MySQL async the `id` stayed at `MISSING` without a word, and that id which never came
    back ends up being the foreign key of the next row.
    """
    mysql = MySQLDialect()

    sync_row = WithoutReturning(name="ana")
    SnakeSession(_DriverWithId(), mysql).add(sync_row)  # type: ignore[arg-type]

    async_row = WithoutReturning(name="ana")

    async def action() -> None:
        await AsyncSession(_DriverWithIdAsync(), mysql).add(async_row)  # type: ignore[arg-type]

    asyncio.run(action())

    assert sync_row.id == 42
    assert async_row.id == sync_row.id  # SAME recovery: parity is the contract


def test_add_all_warns_about_unfilled_keys_in_both_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that the "add_all does not fill the ids" warning is emitted by BOTH sessions.

    The warning is the only thing separating "the rows were inserted" from "and you also have their
    ids". Having only the synchronous session say it turns the async user into precisely the one who
    never finds out.
    """
    mysql = MySQLDialect()

    monkeypatch.setattr(session_mod, "_warned_bulk_keys", set())
    with pytest.warns(SnakeWarning, match="add_all"):
        SnakeSession(_DriverWithId(), mysql).add_all(  # type: ignore[arg-type]
            [WithoutReturning(name="ana")]
        )

    monkeypatch.setattr(session_mod, "_warned_bulk_keys", set())

    async def action() -> None:
        await AsyncSession(_DriverWithIdAsync(), mysql).add_all(  # type: ignore[arg-type]
            [WithoutReturning(name="ana")]
        )

    with pytest.warns(SnakeWarning, match="add_all"):
        asyncio.run(action())
