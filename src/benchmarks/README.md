# SnakeORM benchmarks

A **basic, self-contained** harness that measures SnakeORM's own operations against a real
PostgreSQL and prints a table of timings. It is a **baseline of our own**, not a ranking.

## What it measures

Seven benchmarks, each over the benchmark's own schema (tables `bench_*`, classes `Bench*`):

1. **Compilation (once)** — compiling the models + `snake_link()`, repeated. It measures the
   project's thesis: "compile once" is cheap because the metadata is computed ONE single time.
2. **SQL emission (no DB)** — `query.to_sql(dialect)` of a DEEP query (3 JOINs) repeated N times. It
   measures the cost of generating SQL from the already-compiled AST (it must be fast, without
   touching the DB).
3. **INSERT** — `add_all` of large batches (1,000 and 10,000 rows by default); total time and
   rows/sec.
4. **Simple SELECT** — fetching N rows with `session.all(...)`, including the mapping to instances.
5. **SELECT with deep navigation** — filtering by a 3-hop chain (`BenchTruck.maker.nation.
   continent.name`); execution time + mapping.
6. **to-many include (select-in)** — loading N parents with their children. It wraps the driver in a
   counter and proves that **2 queries** are emitted (1 root + 1 select-in), NOT N+1.
7. **annotate / aggregate** — `COUNT` + `AVG` of the children per parent, grouping by the PK.

All timing uses `time.perf_counter()`. Before each measurement there is a **warm-up** (the first
pass is discarded) so as not to measure the start-up (lazy imports, first plan, caches).

## How to run it

```bash
uv run python -m benchmarks.run          # the full measurement; `make benchmarks` does the same
```

**It does NOT go into `make audit`, and the reason is one of category, not of clock**: a benchmark is
a MEASUREMENT, and its result is a number that changes with the machine. What IS verifiable —that
the harness STILL RUNS— lives in `make benchmarks-smoke`, which runs the smoke test with
`SNAKEORM_REQUIRE_POSTGRES=true` so that a missing server is a FAILURE and not a skip in green.

It needs a reachable PostgreSQL (the devcontainer's will do as it is). The connection is resolved
from `.env` / the environment with the same defaults as the rest of the project (`DB_HOST`,
`DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`). With no Postgres, it prints a clear message and
exits with a code `!= 0`.

The harness is self-contained: it **creates its schema, seeds what it needs, measures and CLEANS UP**
(dropping its tables) on the way out. It leaves no trace in the database.

## Configurable sizes

All the sizes live in `benchmarks/harness.py`, in `DEFAULT_CONFIG` (easy to turn up or down):
compilation and emission iterations, INSERT batch sizes, rows for the reads, number of parents for
the include, and so on. The smoke test (`test/benchmarks/test_smoke.py`) uses a `SMALL_CONFIG` so it
runs fast without asserting timings.

## An honest NOTE

These numbers come from **one specific development machine**, against **a single engine**
(PostgreSQL), and **WITHOUT comparison to other ORMs** (SQLAlchemy, Django ORM, Peewee...). They
serve as a **baseline of our own** for spotting regressions and for backing the thesis that
"compiling once comes cheap", NOT as a ranking nor as a claim that SnakeORM is faster or slower than
anybody. A comparison between ORMs would be another design decision (an equivalent domain, the same
guarantees, controlled variables) that this harness does not take.
