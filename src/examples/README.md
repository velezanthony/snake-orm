# examples/ — SnakeORM in action

Living, executable documentation for SnakeORM. A publishing domain (`showcase.py`) that exercises
ALL of the syntax, and a tour (`tour.py`) that connects to a real Postgres, creates the schema,
seeds it and walks the API printing, for every operation, **the SQL emitted** and **the actual
result**.

## What is here

- **`showcase.py`** — the domain. Models (`Ex*`, tables `ex_*`) showing auto and explicit PKs,
  **composite** PKs and FKs, many-to-many with an **explicit** join table, `UUID`/`Decimal` columns,
  literal `default` vs `default_factory`, `name=` (SQL override), `db_comment`, `index=` and a
  composite unique index (`SnakeIndexes`), and **column inheritance** from an abstract base
  (`ExTimestamped`, without `@snake_model`, which `ExTag` and `ExNote` inherit from), plus a
  read-only **VIEW** (`ExCatalogEntry`, table `ex_catalog`) navigable in both directions. It includes
  `create_schema()` (DDL generated from the metadata with the emitters in `snakeorm.migration`, no
  hand-written SQL, `CREATE VIEW` included) and `seed()`. It also includes a **DATABASE FUNCTION**
  (`ex_book_stats`, opaque SQL) and its declared `@snake_row` form (`BookStats`) for `session.call`.
- **`tour.py`** — the tour, in 22 numbered sections. `main()` runs it from start to finish.

## How to run it

```bash
uv run python -m examples.tour
```

It needs a reachable **PostgreSQL**. The connection is resolved by `test/scenarios/db.py::dsn()`,
which reads a `.env` (or the environment) for `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`,
`DB_NAME` (devcontainer defaults). With no database, that command dies with `OperationalError` and
exit code 1.

The assertions over the output live apart, and **they skip themselves when there is no server**:

```bash
uv run pytest src/test/examples -q       # the tour's integration test: SKIPS without Postgres
```

That skip is convenient on a laptop and it is a green that lies in a gate, so the Makefile runs both
halves DEMANDING the engine — the command published above and the test with
`SNAKEORM_REQUIRE_POSTGRES=true`, which turns the skip into a failure:

```bash
make examples                            # part of `make audit`
```

> SnakeORM's registry is a **global singleton**: that is why the classes (`Ex*`) and the tables
> (`ex_*`) carry a unique prefix, so they do not collide with the test models.

## Which section demonstrates what

| Section | Feature |
| ------- | ------- |
| 1  | CRUD: `add` (wide RETURNING: auto PK + `default_factory`), `add_all`, `update`, `delete`, `first`, `all` |
| 2  | Filters: comparators, `in_`, `like`, `is_null`, `== None`, composition with `&` `\|` `~` |
| 3  | `order_by` (asc/desc), `limit`, `offset`, `distinct()` |
| 4  | **Typed deep navigation** (`ExPrinting.edition.book.publisher.country.name`) and its JOINs |
| 5  | `include()` to-one (LEFT JOIN), to-many (select-in) and the `SnakeRelationshipNotLoaded` guard |
| 6  | Collections: `.any()`, `~.any()`, **nested** `.any()`, `.count()`, `.avg()`, `.sum_()`, `.count() == 0` |
| 7  | Session `count()` and `exists()` |
| 8  | Projection: `select()` with columns, aggregates and navigation; `group_by` + `having` |
| 9  | `annotate()` with `@snake_result` + the escape hatch `obj.aggregate.<name>` (with a `cast`) |
| 10 | Bulk writing: `update_where` with arithmetic (`col = col + x`) and `delete_where` |
| 11 | `upsert` (DO UPDATE and DO NOTHING) |
| 12 | Subquery: `in_(query.as_scalar(col))` |
| 13 | Many-to-many navigating the explicit join table |
| 14 | **Composite** FK/PK: composite JOIN and composite `include` (select-in by tuple) |
| 15 | The **guards** as a feature: `SnakeRelationshipNotLoaded`, `delete_where` without a filter, `annotate` with names that do not match, and the typing guard (`# does not compile`) |
| 16 | Coercion: a projected `UUID` column comes back as `uuid.UUID`, not `str` |
| 17 | `server_default`: the value is set by the SERVER (`NOW`, `UUID_V4`), outside the `INSERT` |
| 18 | **Explicit JOIN** to a collection (`.join()`): the **child rows**, multiplied, vs `.any()`; `SnakeJoinedQuery` only projects tuples (it does not hydrate models) |
| 19 | **Nested `include()`** with `SnakePrefetch(...).then(...)`: to-many → to-many with **one query per level** (chained select-in, no N+1); and **`.filter()` in the prefetch** to narrow which children are loaded per level (a parent with no matching children comes back with an **empty** list) |
| 20 | **Column inheritance**: `ExTag` and `ExNote` inherit `id` + `created_at` from an abstract base (`ExTimestamped`, without `@snake_model`); the compiler walks the MRO and the inherited columns come out before the own ones |
| 21 | **Views** (`@snake_view`): a **read-only** model mapped over a `VIEW`; it is queried and **navigated** in both directions (`ExPublisher.catalog` ↔ `ExCatalogEntry.publisher`); `session.add/update/delete` reject it (type lock + runtime guard) |
| 22 | **Database functions** (`session.call`): calls a `FUNCTION ... RETURNS TABLE` and maps its rows to a `@snake_row` (a **DECLARED** contract, not a verified one); the ARGS travel parameterised; the types are coerced (NUMERIC→`float`). The CRUD of routines lives in the migrations (`CreateFunction`/`AlterFunction`/`DropFunction`) |
