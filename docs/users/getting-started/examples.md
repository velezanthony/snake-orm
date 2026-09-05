# Runnable examples

Every page on this site is prose about SQL. `src/examples/` is the opposite: a program you run,
against a real PostgreSQL, which prints for each operation **the SQL emitted** and **the actual
result the database gives back**, one beside the other.

```bash
uv run python -m examples.tour
```

That is the tour. It connects, creates the schema of a publishing domain, seeds it and walks the API
in numbered sections — from CRUD to nested prefetch, passing through typed deep navigation,
composite keys, upsert, views and database functions.

## What lives there

| File | What it is |
|---|---|
| `src/examples/showcase.py` | The domain. Models `Ex*` over tables `ex_*`, plus `create_schema()` and `seed()` |
| `src/examples/tour.py` | The walk. `main()` runs it end to end |
| `src/examples/README.md` | The table of which section demonstrates what |

The domain is not a toy: it exercises auto and explicit primary keys, **composite** PKs and FKs, a
many-to-many with an explicit join table, `UUID` and `Decimal` columns, literal `default` against
`default_factory`, column renames, comments, indexes, columns **inherited** from an abstract base, a
read-only **VIEW** navigable in both directions, and a database **FUNCTION** called through
`session.call`.

`create_schema()` is worth a look on its own: the DDL comes out of the metadata through the emitters
in `snakeorm.migration`, including the `CREATE VIEW`. There is no hand-written SQL in it.

## What it needs

A reachable PostgreSQL. The connection is resolved by `test/scenarios/db.py::dsn()`, which reads the
same `.env` as the rest of the project (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`).
The [installation page](installation.md) covers those variables.

SnakeORM's registry is a **global singleton**, and that is why every class and table in there carries
a unique prefix (`Ex*`, `ex_*`): so they cannot collide with the models of the test suite.

There is an integration test that runs the whole tour:

```bash
uv run pytest src/test/examples/ -q
```

## Why read it instead of a page

Because a page can go stale and a program cannot. The SQL the tour prints is not an illustration of
the SQL that runs: it **is** the SQL that runs, obtained from the same emitter the session uses. If
an emitter changes, the output changes with it.

The section on guards is the clearest case. It provokes the errors on purpose —a relation that was
not loaded, a `delete_where` with no filter, an `annotate` whose names do not match— and prints the
messages. In an ORM whose doctrine is to shout rather than guess, those messages are the product,
and there they are, printed by the thing that emits them.

## Benchmarks

`src/benchmarks/` is the other executable corner: a self-contained harness that times compilation,
SQL emission, inserts, reads, deep navigation, select-in prefetch and aggregates against a real
PostgreSQL.

```bash
uv run python -m benchmarks.run
```

It creates its own schema (`bench_*`), measures, and drops it. Read `src/benchmarks/README.md`
before reading the numbers: it is a **baseline of its own**, on one machine and one engine, with no
comparison against other ORMs — useful for catching regressions, not for claiming a ranking.

---

Next: the [guide](../guide/columns.md), which goes type by type.
