"""The benchmark's OWN domain: a 3-hop to-one chain for deep navigation.

Table names carry the `bench_` prefix and classes the `Bench` prefix so they never collide with
the GLOBAL registry that the examples and the tests share. The graph is a parent-to-child chain:

    BenchContinent (PK str)  1──*  BenchNation (PK auto)  1──*  BenchMaker (PK auto)  1──*  BenchTruck (PK auto)

The "crown jewel" for typed deep navigation (3 JOINs, no `Any`):

    BenchTruck.maker.nation.continent.name

The DDL is generated from the compiled metadata with the emitters in `snakeorm.migration`: NO
hand-written SQL, just like the rest of the project. The structure lives here; the seeding and
the measurements live in `benchmarks/run.py` (they depend on the configurable sizes).
"""

from __future__ import annotations

from decimal import Decimal

from snakeorm.decorators import SnakeResult, snake_model, snake_result, snake_table
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers import SnakeDriver
from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.fields import (
    SnakeColumn,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_column,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.metadata import SnakeFkAction
from snakeorm.migration import emit_add_foreign_key, emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.registry import registry


@snake_model(table="bench_continents")
class BenchContinent(SnakeModel):
    """Continent. EXPLICIT PK (a short code, chosen by the user)."""

    code: SnakeColumn[str] = snake_str(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    nations: SnakeToMany[BenchNation] = snake_to_many("continent")


@snake_model(table="bench_nations")
class BenchNation(SnakeModel):
    """Nation. Auto-increment PK and a simple FK to the continent."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    continent_code: SnakeColumn[str] = snake_str()
    continent: SnakeToOne[BenchContinent] = snake_to_one(
        continent_code, on_delete=SnakeFkAction.CASCADE
    )
    makers: SnakeToMany[BenchMaker] = snake_to_many("nation")


@snake_model(table="bench_makers")
class BenchMaker(SnakeModel):
    """Maker. Auto-increment PK and a simple FK to the nation."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    nation_id: SnakeColumn[int] = snake_int()
    nation: SnakeToOne[BenchNation] = snake_to_one(
        nation_id, on_delete=SnakeFkAction.CASCADE
    )
    trucks: SnakeToMany[BenchTruck] = snake_to_many("maker")


@snake_model(table="bench_trucks")
class BenchTruck(SnakeModel):
    """Truck (the leaf of the chain). Auto-increment PK, a Decimal `price` and an FK to the maker."""

    id: SnakeColumn[int] = snake_auto()
    model_name: SnakeColumn[str] = snake_str()
    price: SnakeColumn[Decimal] = snake_column()
    maker_id: SnakeColumn[int] = snake_int()
    maker: SnakeToOne[BenchMaker] = snake_to_one(
        maker_id, on_delete=SnakeFkAction.CASCADE
    )


@snake_result
class BenchMakerStats(SnakeResult[BenchMaker]):
    """TYPED container for `session.annotate()`: base row (the maker) + scalar aggregates.

    `avg_price` is `float | None` because `AVG` over zero rows is NULL (only `COUNT` is 0). The
    declared type is the source of truth for the coercion: an `AVG` that Postgres hands back as a
    `Decimal` comes back as a `float` because `float` is what is declared here.
    """

    maker: BenchMaker
    truck_count: int
    avg_price: float | None


# Creation order: the tables first (with no inline FKs) and the FKs at the end, so the order of
# this list does not matter for the dependencies. The DROP uses CASCADE (see `drop_schema`).
MODELS: tuple[type[SnakeModel], ...] = (
    BenchContinent,
    BenchNation,
    BenchMaker,
    BenchTruck,
)


def create_schema(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Creates (resetting it) the benchmark schema, generating the DDL from the compiled metadata.

    Two phases, like a real migration: (1) CREATE TABLE for every table, (2) ALTER TABLE ADD
    FOREIGN KEY for every to-one relationship. NO hand-written SQL. Requires `snake_link()` first
    (the FKs are resolved in the linker).
    """
    drop_schema(driver, dialect)
    tables = [snake_table(model) for model in MODELS]
    for table in tables:
        driver.execute(emit_create_table(table, dialect), ())
    for table in tables:
        for relationship in table.relationships:
            if relationship.kind != "to_one":
                continue
            target = registry.table_by_name(relationship.target)
            if target is None:
                raise SnakeRegistryError(
                    f"The target '{relationship.target}' of '{table.name}."
                    f"{relationship.name}' is not registered."
                )
            driver.execute(
                emit_add_foreign_key(table, relationship, target, dialect), ()
            )


def drop_schema(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Drops the benchmark tables (the final cleanup). CASCADE takes the FKs down as well."""
    references = ", ".join(
        f"{dialect.quote_ident(table.schema)}.{dialect.quote_ident(table.name)}"
        for table in (snake_table(model) for model in MODELS)
    )
    driver.execute(f"DROP TABLE IF EXISTS {references} CASCADE", ())
