"""Demonstration tests: they query the seeded playground with the current ORM.

They check that the stack works against real data with edge cases, and act as a safety net to
develop in parallel. They are read-only (they do not mutate the shared seed).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest

from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.domain import Country, Event, OrderItem, Owner
from test.scenarios.schema import EVENT_AMOUNT, EVENT_CREATED, EVENT_ID

pytestmark = pytest.mark.integration


def test_simple_table_with_unique(seeded_session: SnakeSession) -> None:
    """Checks a simple table: the seeded countries with their unique ISO code."""
    countries = seeded_session.all(SnakeQuery(Country))
    assert {(c.name, c.iso_code) for c in countries} == {
        ("España", "ES"),
        ("Alemania", "DE"),
    }


def test_name_override_round_trips(seeded_session: SnakeSession) -> None:
    """Checks the override: the SQL column `full_name` maps to the `name` attribute."""
    ana = seeded_session.first(SnakeQuery(Owner).filter(Owner.name == "Ana"))
    assert ana is not None
    assert ana.name == "Ana"


def test_nullable_and_default_columns(seeded_session: SnakeSession) -> None:
    """Checks a nullable column (age None) and a boolean seeded to FALSE."""
    bob = seeded_session.first(SnakeQuery(Owner).filter(Owner.id == 2))
    assert bob is not None
    assert bob.age is None
    assert bob.active is False


def test_is_null_filter_against_real_pg(seeded_session: SnakeSession) -> None:
    """Checks that `.is_null()` really filters the NULLs in Postgres (Bob, NULL age)."""
    sin_age = seeded_session.all(SnakeQuery(Owner).filter(Owner.age.is_null()))
    assert [o.name for o in sin_age] == ["Bob"]


def test_projection_returns_tuples_against_real_pg(
    seeded_session: SnakeSession,
) -> None:
    """Checks .select(): it projects specific columns and returns tuples (not models)."""
    rows = seeded_session.select(SnakeQuery(Country), Country.name, Country.iso_code)
    assert set(rows) == {("España", "ES"), ("Alemania", "DE")}


def test_count_and_exists_against_real_pg(seeded_session: SnakeSession) -> None:
    """Checks count() and exists() against a real Postgres over the seeded data."""
    assert seeded_session.count(SnakeQuery(Country)) == 2
    assert seeded_session.count(SnakeQuery(Owner).filter(Owner.age.is_null())) == 1
    assert seeded_session.exists(SnakeQuery(Owner).filter(Owner.name == "Ana")) is True
    assert (
        seeded_session.exists(SnakeQuery(Owner).filter(Owner.name == "Nadie")) is False
    )


def test_composite_pk_table(seeded_session: SnakeSession) -> None:
    """Checks that a table with a composite PK is read with no special cases."""
    items = seeded_session.all(SnakeQuery(OrderItem))
    assert {(i.order_id, i.product_id, i.quantity) for i in items} == {
        (10, 100, 5),
        (10, 101, 2),
    }


def test_varied_types_round_trip(seeded_session: SnakeSession) -> None:
    """Checks the type round-trip: Decimal, datetime and UUID coerced to the declared type."""
    event = seeded_session.first(SnakeQuery(Event))
    assert event is not None
    assert isinstance(event.amount, Decimal) and event.amount == EVENT_AMOUNT
    assert isinstance(event.created_at, datetime) and event.created_at == EVENT_CREATED
    assert event.note is None
    # The coercion turns the str that psycopg2 returns into the UUID declared in the model.
    assert isinstance(event.id, UUID) and event.id == EVENT_ID


def test_select_coerces_projected_uuid_against_real_pg(
    seeded_session: SnakeSession,
) -> None:
    """Checks that select() coerces a projected UUID column to uuid.UUID (not psycopg2's str)."""
    rows = seeded_session.select(SnakeQuery(Event), Event.id)
    assert rows == [(EVENT_ID,)]
    assert isinstance(rows[0][0], UUID)
