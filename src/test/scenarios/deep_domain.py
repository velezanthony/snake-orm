"""Domain with relationships (snake_to_one) to exercise deep JOINs: Truck→Maker→Nation.

Uncommon names (they do not clash with other tests in the global registry). Includes DDL + seed
for the integration test against a real Postgres. The seeded graph:
España→SEAT→Ibiza and Alemania→BMW→M3.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.drivers import SnakeDriver
from snakeorm.fields import (
    SnakeColumn,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.model import SnakeModel


@snake_model(table="nations")
class Nation(SnakeModel):
    """Root of the chain; inverse to-many towards its makers."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    makers: SnakeToMany[Maker] = snake_to_many("nation")


@snake_model(table="makers")
class Maker(SnakeModel):
    """Maker, with a relationship to Nation and an inverse to-many towards its trucks."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    nation_id: SnakeColumn[int] = snake_int()
    nation: SnakeToOne[Nation] = snake_to_one(nation_id)
    trucks: SnakeToMany[Truck] = snake_to_many("maker")


@snake_model(table="trucks")
class Truck(SnakeModel):
    """Vehicle, with a relationship to Maker: the Truck→Maker→Nation chain."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    model: SnakeColumn[str] = snake_str()
    maker_id: SnakeColumn[int] = snake_int()
    maker: SnakeToOne[Maker] = snake_to_one(maker_id)


_DDL = (
    "DROP TABLE IF EXISTS trucks, makers, nations CASCADE",
    "CREATE TABLE nations (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE makers ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " nation_id INTEGER NOT NULL REFERENCES nations(id))",
    "CREATE TABLE trucks ("
    " id INTEGER PRIMARY KEY, model TEXT NOT NULL,"
    " maker_id INTEGER NOT NULL REFERENCES makers(id))",
)


def create_schema(driver: SnakeDriver) -> None:
    """Creates (resetting) the tables of the deep domain."""
    for statement in _DDL:
        driver.execute(statement, ())


def seed(driver: SnakeDriver) -> None:
    """Populates the graph: España→SEAT→Ibiza, Alemania→BMW→M3."""
    driver.execute("INSERT INTO nations VALUES (1, 'España'), (2, 'Alemania')", ())
    driver.execute("INSERT INTO makers VALUES (1, 'SEAT', 1), (2, 'BMW', 2)", ())
    driver.execute("INSERT INTO trucks VALUES (1, 'Ibiza', 1), (2, 'M3', 2)", ())
