"""Benchmark entry point: `uv run python -m benchmarks.run`.

Connects to a real Postgres, creates its own schema (`bench_*`), seeds what it needs, MEASURES the
seven operations that belong to the ORM and prints a table of timings. On the way out it CLEANS its
tables. If there is no Postgres, it prints a clear message and exits with a code != 0 (no ugly blow-up).

The seven benchmarks:
    1. Compilation (once): compiling the models + `snake_link()` — the "compiling is cheap" thesis.
    2. SQL emission (no DB): `query.to_sql(dialect)` of a DEEP query (3 JOINs), repeated.
    3. INSERT: `add_all` of large batches; total time and rows/sec.
    4. Simple SELECT: fetch N rows and map them to instances.
    5. SELECT with deep navigation: filter through a chain of 3 hops (2-3 JOINs).
    6. to-many include (select-in): N parents with their children, counting the queries (proves no N+1).
    7. annotate / aggregate: COUNT + AVG aggregates per maker.

The sizes are parameterized in `benchmarks/harness.py` (`DEFAULT_CONFIG`). `main()` accepts a
`BenchConfig` so that the smoke test can use small sizes.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg2

from benchmarks.harness import (
    DEFAULT_CONFIG,
    BenchConfig,
    CountingDriver,
    Measurement,
    Section,
    format_table,
    measure_repeated,
    time_call,
)
from benchmarks.models import (
    MODELS,
    BenchContinent,
    BenchMaker,
    BenchMakerStats,
    BenchNation,
    BenchTruck,
    create_schema,
    drop_schema,
)
from snakeorm.compiler import compile_model
from snakeorm.decorators import snake_table
from snakeorm.dialects import PostgresDialect, SnakeDialect
from snakeorm.drivers import PsycopgDriver, SnakeDriver
from snakeorm.linker.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

_WIDTH = 78


def _banner(text: str) -> None:
    """Prints a framed section header (a marker the smoke test looks for as well)."""
    print()
    print("=" * _WIDTH)
    print(f" {text}")
    print("=" * _WIDTH)


def _price(index: int) -> Decimal:
    """Deterministic price for truck `index` (NUMERIC, varied but reproducible)."""
    return Decimal(50_00 + (index % 5_000)) / Decimal(100)


def _trucks(count: int, maker_ids: list[int]) -> list[BenchTruck]:
    """Builds `count` BenchTruck instances spread across the given makers."""
    return [
        BenchTruck(
            model_name=f"Truck-{index}",
            price=_price(index),
            maker_id=maker_ids[index % len(maker_ids)],
        )
        for index in range(count)
    ]


def _truncate_all(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Empties the four benchmark tables, restarting the sequences (leaves the schema intact)."""
    references = ", ".join(
        f"{dialect.quote_ident(table.schema)}.{dialect.quote_ident(table.name)}"
        for table in (snake_table(model) for model in MODELS)
    )
    driver.execute(f"TRUNCATE {references} RESTART IDENTITY CASCADE", ())


def _truncate_trucks(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Empties only `bench_trucks`, restarting its sequence (between batches of the INSERT benchmark)."""
    table = snake_table(BenchTruck)
    reference = f"{dialect.quote_ident(table.schema)}.{dialect.quote_ident(table.name)}"
    driver.execute(f"TRUNCATE {reference} RESTART IDENTITY", ())


# ─────────────────────────────────────────────────────────────────────────────
# Seeding
# ─────────────────────────────────────────────────────────────────────────────
def _seed_one_maker(session: SnakeSession) -> int:
    """Seeds the minimum the INSERTs' FK needs (1 continent, 1 nation, 1 maker). Returns its id."""
    session.add_all([BenchContinent(code="C0", name="Continent-0")])
    nation = BenchNation(name="Nation-0", continent_code="C0")
    session.add(nation)
    maker = BenchMaker(name="Maker-0", nation_id=nation.id)
    session.add(maker)
    session.commit()
    return maker.id


def _seed_reads(session: SnakeSession, config: BenchConfig) -> str:
    """Empties and seeds the READ graph: continents -> nations -> makers -> trucks.

    Returns the name of the first continent, which the deep-navigation test uses as its filter. The
    trucks are spread evenly across the makers, so every maker has children (for the to-many include)
    and every continent has descendant trucks (for the deep filter).
    """
    _truncate_all(session._driver, session._dialect)  # noqa: SLF001 - controlled cleanup by the harness
    continents = [
        BenchContinent(code=f"C{index}", name=f"Continent-{index}")
        for index in range(config.continents)
    ]
    session.add_all(continents)
    nations = [
        BenchNation(
            name=f"Nation-{index}",
            continent_code=continents[index % config.continents].code,
        )
        for index in range(config.nations)
    ]
    session.add_all(nations)
    makers = [
        BenchMaker(name=f"Maker-{index}", nation_id=nations[index % config.nations].id)
        for index in range(config.include_parents)
    ]
    session.add_all(makers)
    session.add_all(_trucks(config.read_rows, [maker.id for maker in makers]))
    session.commit()
    return continents[0].name


# ─────────────────────────────────────────────────────────────────────────────
# The seven benchmarks
# ─────────────────────────────────────────────────────────────────────────────
def _bench_compile(config: BenchConfig) -> Section:
    """1. Compilation: compile the 4 models + `snake_link()`, repeated (the 'compiling is cheap' thesis)."""
    _banner("1. Compilation (compile models + link) - the thesis")

    def compile_cycle() -> None:
        for model in MODELS:
            compile_model(model)
        snake_link()

    measurement = measure_repeated(
        "Compile 4 models + link",
        config.compile_iterations,
        compile_cycle,
        warmup=config.warmup,
        unit="cycle",
    )
    return Section("1. Compilation", [measurement])


def _bench_emit(
    config: BenchConfig, dialect: SnakeDialect, continent_name: str
) -> Section:
    """2. SQL emission (no DB): `to_sql` of a 3-JOIN query, repeated N times."""
    _banner("2. SQL emission - deep query (3 JOINs), without touching the DB")
    deep_query = SnakeQuery(BenchTruck).filter(
        BenchTruck.maker.nation.continent.name == continent_name
    )
    measurement = measure_repeated(
        "to_sql() query 3 JOINs",
        config.emit_iterations,
        lambda: deep_query.to_sql(dialect),
        warmup=config.warmup,
    )
    return Section("2. SQL emission", [measurement])


def _bench_insert(
    session: SnakeSession, dialect: SnakeDialect, config: BenchConfig, maker_id: int
) -> Section:
    """3. INSERT: `add_all` for each configured size; total time and rows/sec.

    The instances are built OUTSIDE the stopwatch (what is measured is `add_all`: emission, execution
    and the mapping of the RETURNING, not the cost of creating objects). The table is emptied between
    batches.
    """
    _banner("3. INSERT - add_all in batches (rows/sec)")
    driver = session._driver  # noqa: SLF001 - the harness needs the driver for the TRUNCATE
    measurements: list[Measurement] = []
    for size in config.insert_sizes:
        for _ in range(config.warmup):
            session.add_all(_trucks(size, [maker_id]))
            _truncate_trucks(driver, dialect)
        rows = _trucks(size, [maker_id])
        seconds = time_call(lambda: session.add_all(rows))
        session.commit()
        measurements.append(
            Measurement(f"INSERT add_all ({size:,} rows)", size, seconds, "row")
        )
        _truncate_trucks(driver, dialect)
        session.commit()
    return Section("3. INSERT", measurements)


def _bench_select_simple(session: SnakeSession, config: BenchConfig) -> Section:
    """4. Plain SELECT: fetch every row and map it to instances (hydration included)."""
    _banner("4. Plain SELECT - fetch N rows and map them to instances")
    query = SnakeQuery(BenchTruck)
    session.all(query)  # warm-up (discards the first plan / cache)
    result: list[BenchTruck] = []

    def run() -> None:
        nonlocal result
        result = session.all(query)

    seconds = time_call(run)
    measurement = Measurement("SELECT all() + mapping", len(result), seconds, "row")
    return Section("4. Plain SELECT", [measurement])


def _bench_select_deep(
    session: SnakeSession, config: BenchConfig, continent_name: str
) -> Section:
    """5. SELECT with deep navigation: filter through a 3-hop chain (2-3 JOINs) + mapping."""
    _banner("5. SELECT deep navigation - filter through 3 hops (JOINs) + mapping")
    query = SnakeQuery(BenchTruck).filter(
        BenchTruck.maker.nation.continent.name == continent_name
    )
    session.all(query)  # warm-up
    result: list[BenchTruck] = []

    def run() -> None:
        nonlocal result
        result = session.all(query)

    seconds = time_call(run)
    measurement = Measurement("SELECT 3 JOINs + mapping", len(result), seconds, "row")
    return Section("5. SELECT deep navigation", [measurement])


def _bench_include(
    dialect: SnakeDialect, config: BenchConfig
) -> tuple[Section, int, int]:
    """6. to-many include (select-in): N parents with their children, COUNTING the queries emitted.

    It wraps a connection of its own in `CountingDriver` so as to exhibit the real number of queries:
    it must be 2 (1 root + 1 select-in), NOT N+1. Returns the section, the number of parents and the
    queries.
    """
    _banner("6. to-many include (select-in) - no N+1 (it counts the queries)")
    counting = CountingDriver(PsycopgDriver.connect(dsn()))
    try:
        session = SnakeSession(counting, dialect)
        query = SnakeQuery(BenchMaker).include(BenchMaker.trucks)
        session.all(query)  # warm-up
        counting.fetch_count = 0
        counting.execute_count = 0
        parents: list[BenchMaker] = []

        def run() -> None:
            nonlocal parents
            parents = session.all(query)

        seconds = time_call(run)
        query_count = counting.query_count
    finally:
        counting.close()
    measurement = Measurement(
        "include(trucks) select-in", len(parents), seconds, "parent"
    )
    return Section("6. to-many include", [measurement]), len(parents), query_count


def _bench_annotate(session: SnakeSession, config: BenchConfig) -> Section:
    """7. annotate / aggregate: COUNT + AVG of the trucks per maker, grouping by PK."""
    _banner("7. annotate / aggregate - COUNT + AVG per maker")
    truck_count = BenchMaker.trucks.count()
    avg_price = BenchMaker.trucks.avg(BenchTruck.price)
    query = SnakeQuery(BenchMaker)
    session.annotate(
        query, BenchMakerStats, truck_count=truck_count, avg_price=avg_price
    )  # warm-up
    result: list[BenchMakerStats] = []

    def run() -> None:
        nonlocal result
        result = session.annotate(
            query, BenchMakerStats, truck_count=truck_count, avg_price=avg_price
        )

    seconds = time_call(run)
    measurement = Measurement("annotate COUNT+AVG", len(result), seconds, "group")
    return Section("7. annotate / aggregate", [measurement])


def main(config: BenchConfig = DEFAULT_CONFIG) -> int:
    """Runs the seven benchmarks against Postgres and prints the timing table. Returns the exit code.

    0 if everything ran; 1 if there is no Postgres available (a clear message, with no ugly
    traceback). The schema is created and cleaned up inside this function: the harness is
    self-contained and leaves no trace.
    """
    snake_link()  # resolves the relationships (needed before using FKs, includes and the DDL)
    dialect = PostgresDialect()

    try:
        driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:
        print("There is no Postgres available: the benchmark cannot be run.")
        print(f"  Detail: {error}")
        print(
            "  Check the .env / the devcontainer (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME)."
        )
        return 1

    print("SnakeORM - basic BENCHMARK (its own baseline, a single engine: PostgreSQL)")
    sections: list[Section] = []
    include_parents = 0
    include_queries = 0
    try:
        create_schema(driver, dialect)
        session = SnakeSession(driver, dialect)

        # Benchmarks with no DB (compilation and emission): the emission needs a continent name for
        # the deep filter; with the schema just created there is no data yet, so a literal will do.
        sections.append(_bench_compile(config))
        sections.append(_bench_emit(config, dialect, "Continent-0"))

        maker_id = _seed_one_maker(session)
        sections.append(_bench_insert(session, dialect, config, maker_id))

        continent_name = _seed_reads(session, config)
        sections.append(_bench_select_simple(session, config))
        sections.append(_bench_select_deep(session, config, continent_name))

        include_section, include_parents, include_queries = _bench_include(
            dialect, config
        )
        sections.append(include_section)

        sections.append(_bench_annotate(session, config))
    finally:
        drop_schema(driver, dialect)
        driver.commit()
        driver.close()

    _banner("Results (time.perf_counter)")
    print(format_table(sections))
    print()
    print(
        f"to-many include: {include_queries} queries emitted for {include_parents:,} parents "
        f"(2 expected = 1 root + 1 select-in -> NOT an N+1)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
