"""DDL and seed for the scenario domain (by hand: there is no migration/ yet).

`create_schema` resets the tables (idempotent) and `seed` populates them with a connected graph
plus the odd cases (NULL age, inactive owner, composite PK, assorted types). The database is
left populated after the tests: it is a playground to inspect and to develop against.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from snakeorm import SnakeUtc
from snakeorm.drivers import SnakeDriver

# Fixed values for the event (deterministic so they can be asserted).
EVENT_ID = UUID("11111111-1111-1111-1111-111111111111")
EVENT_AMOUNT = Decimal("1234.56")
# AWARE, and not a bare `datetime`: the model declares `snake_datetimetz()`, so the column
# is TIMESTAMPTZ and what comes back is an instant. A naive one here compared apples to oranges.
EVENT_CREATED = SnakeUtc(2024, 1, 15, 12, 30, 0)

_DDL = (
    "DROP TABLE IF EXISTS order_items, events, owners, cars, brands, countries CASCADE",
    "CREATE TABLE countries ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL, iso_code TEXT UNIQUE NOT NULL)",
    "CREATE TABLE brands ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " country_id INTEGER NOT NULL REFERENCES countries(id))",
    "CREATE TABLE cars ("
    " id INTEGER PRIMARY KEY, model TEXT NOT NULL,"
    " brand_id INTEGER NOT NULL REFERENCES brands(id))",
    "CREATE TABLE owners ("
    " id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, age INTEGER,"
    " active BOOLEAN NOT NULL DEFAULT TRUE, car_id INTEGER NOT NULL REFERENCES cars(id))",
    "CREATE TABLE order_items ("
    " order_id INTEGER, product_id INTEGER, quantity INTEGER NOT NULL,"
    " PRIMARY KEY (order_id, product_id))",
    "CREATE TABLE events ("
    " id UUID PRIMARY KEY, amount NUMERIC(10, 2) NOT NULL,"
    # TIMESTAMPTZ, just as the model emits. This DDL is written by hand and had drifted from
    # the model, which is exactly what a hand-written fixture cannot afford.
    " created_at TIMESTAMPTZ NOT NULL, note TEXT)",
)


def create_schema(driver: SnakeDriver) -> None:
    """Creates (resetting) the schema of the scenario domain."""
    for statement in _DDL:
        driver.execute(statement, ())


def seed(driver: SnakeDriver) -> None:
    """Populates the connected graph and the odd cases."""
    driver.execute(
        "INSERT INTO countries VALUES (1, 'España', 'ES'), (2, 'Alemania', 'DE')", ()
    )
    driver.execute("INSERT INTO brands VALUES (1, 'SEAT', 1), (2, 'BMW', 2)", ())
    driver.execute("INSERT INTO cars VALUES (1, 'Ibiza', 1), (2, 'M3', 2)", ())
    # Ana: age 30, active. Bob: age NULL, inactive (nullable + default edge cases).
    driver.execute(
        "INSERT INTO owners (id, full_name, age, active, car_id) VALUES"
        " (1, 'Ana', 30, TRUE, 1), (2, 'Bob', NULL, FALSE, 2)",
        (),
    )
    driver.execute("INSERT INTO order_items VALUES (10, 100, 5), (10, 101, 2)", ())
    driver.execute(
        "INSERT INTO events (id, amount, created_at, note) VALUES (%s, %s, %s, %s)",
        (str(EVENT_ID), EVENT_AMOUNT, EVENT_CREATED, None),
    )
