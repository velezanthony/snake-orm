"""Triggers EXECUTED against Postgres: that they really do FIRE.

That the DDL is valid proves nothing that matters. What matters is the GUARANTEE: that the rule
holds even when the row is written by someone who does not go through the ORM. That is only proven
by writing from the outside and checking that the trigger acted all the same.

It skips gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeTriggerEvent,
    SnakeTriggerTiming,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.metadata import SnakeRoutineInfo, SnakeTriggerInfo
from snakeorm.migration import (
    AlterTrigger,
    CreateFunction,
    CreateTrigger,
    DropTrigger,
    emit_create_table,
)
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="tg_orders")
class Order(SnakeModel):
    """Order with a mark that the TRIGGER fills in, not the application."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    amount: SnakeColumn[int] = snake_int()
    brand: SnakeColumn[str | None] = snake_str()


_FUNCTION = SnakeRoutineInfo(
    name="tg_marcar",
    body=(
        "CREATE OR REPLACE FUNCTION tg_marcar() RETURNS trigger AS $$ "
        "BEGIN NEW.brand := 'tocado'; RETURN NEW; END; $$ LANGUAGE plpgsql"
    ),
)


def _trigger(function: str = "tg_marcar") -> SnakeTriggerInfo:
    """A BEFORE trigger that fills in the mark before the row is stored."""
    return SnakeTriggerInfo(
        name="tg_orders_marcar",
        table="tg_orders",
        timing=SnakeTriggerTiming.BEFORE,
        events=(SnakeTriggerEvent.INSERT, SnakeTriggerEvent.UPDATE),
        body=f"EXECUTE FUNCTION {function}()",
    )


@pytest.fixture
def environment() -> Iterator[tuple[SnakeSession, PsycopgDriver]]:
    """Table, function and trigger created with the ORM's OWN DDL."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    dialect = PostgresDialect()
    driver.execute("DROP TABLE IF EXISTS tg_orders CASCADE", ())
    driver.execute("DROP FUNCTION IF EXISTS tg_marcar() CASCADE", ())
    driver.execute(emit_create_table(snake_table(Order), dialect), ())
    for sql in CreateFunction(_FUNCTION).up_sql(dialect):
        driver.execute(sql, ())
    for sql in CreateTrigger(_trigger()).up_sql(dialect):
        driver.execute(sql, ())
    driver.commit()
    try:
        yield SnakeSession(driver, dialect), driver
    finally:
        driver.execute("DROP TABLE IF EXISTS tg_orders CASCADE", ())
        driver.execute("DROP FUNCTION IF EXISTS tg_marcar() CASCADE", ())
        driver.commit()
        driver.close()


def test_it_fires_on_a_write_through_the_orm(
    environment: tuple[SnakeSession, PsycopgDriver],
) -> None:
    """The trigger acts on a row written through the ORM."""
    session, _ = environment
    session.add(Order(id=1, amount=100, brand=None))
    session.commit()

    order = session.first(SnakeQuery(Order).filter(Order.id == 1))
    assert order is not None and order.brand == "tocado"


def test_it_fires_on_a_write_that_never_touched_the_orm(
    environment: tuple[SnakeSession, PsycopgDriver],
) -> None:
    """THE proof that justifies triggers existing: it is written FROM OUTSIDE and still holds.

    This is the only thing that separates a trigger from a code signal. A signal only fires if the
    write goes through the session; here the row goes in with raw SQL —as a maintenance script,
    another application or somebody in a `psql` would put it in— and the rule holds regardless.
    """
    session, driver = environment
    driver.execute("INSERT INTO tg_orders (id, amount) VALUES (2, 50)", ())
    driver.commit()

    order = session.first(SnakeQuery(Order).filter(Order.id == 2))
    assert order is not None and order.brand == "tocado"


def test_dropping_it_stops_the_rule(
    environment: tuple[SnakeSession, PsycopgDriver],
) -> None:
    """The operation's `down` switches the rule off: create and drop really are inverses."""
    session, driver = environment
    for sql in DropTrigger(_trigger()).up_sql(PostgresDialect()):
        driver.execute(sql, ())
    driver.commit()

    session.add(Order(id=3, amount=10, brand=None))
    session.commit()

    order = session.first(SnakeQuery(Order).filter(Order.id == 3))
    assert order is not None and order.brand is None


def test_altering_it_swaps_the_behaviour(
    environment: tuple[SnakeSession, PsycopgDriver],
) -> None:
    """`AlterTrigger` replaces the whole rule: DROP + CREATE, and it shows in the data."""
    session, driver = environment
    dialect = PostgresDialect()
    driver.execute(
        "CREATE OR REPLACE FUNCTION tg_other() RETURNS trigger AS $$ "
        "BEGIN NEW.brand := 'other'; RETURN NEW; END; $$ LANGUAGE plpgsql",
        (),
    )
    for sql in AlterTrigger(_trigger(), _trigger("tg_other")).up_sql(dialect):
        driver.execute(sql, ())
    driver.commit()

    session.add(Order(id=4, amount=10, brand=None))
    session.commit()

    order = session.first(SnakeQuery(Order).filter(Order.id == 4))
    assert order is not None and order.brand == "other"
    driver.execute("DROP FUNCTION IF EXISTS tg_other() CASCADE", ())
    driver.commit()
