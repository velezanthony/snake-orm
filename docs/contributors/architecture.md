# Architecture (v2)

```python
from __future__ import annotations

from snakeorm import (
    SnakeColumn, SnakeModel, SnakeQuery, SnakeToOne,
    snake_auto, snake_int, snake_link, snake_model, snake_str, snake_to_one,
)

@snake_model(table="countries")
class Country(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()

@snake_model(table="cities")
class City(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    country_id: SnakeColumn[int] = snake_int()
    country: SnakeToOne[Country] = snake_to_one(country_id)
    name: SnakeColumn[str] = snake_str()

snake_link()  # the classes are already compiled; this resolves the relationships

# The query is an immutable AST: it does not execute. The JOIN comes from the relationship path.
q = SnakeQuery(City).filter(City.country.name == "España")
```

That is the whole pipeline: **Python class → immutable metadata → AST → `(sql, params)` → driver**.
The class is inspected once; the runtime reads from the graph, never from the class.

## Principles (non-negotiable)

- **Type-first**: the type comes from Python. Metadata only adds SQL info, never the type.
- **Compile-once**: the class is inspected ONCE → immutable graph. The runtime does not reflect.
- **Zero `Any`** in the API, **zero raw SQL** outside `sql/`, **zero magic strings**.
- One responsibility per module. No giant metaclasses.
- **The ORM provides primitives, not roles.** `Repository`/`Service`/`Selector` belong to your app;
  the ORM delivers the brick (`SnakeQuery`).
- **What an engine cannot do is DECLARED, never guessed.** Either it is translated to an exact
  equivalent, or the ORM stops and says why. Storing worse and keeping quiet is never an option.

## Decisions

| Decision | Choice | Status |
|----------|--------|--------|
| Deep relationship typing | Recursive descriptors: class access → `SnakeExpr[T]` / `type[M]` / `SnakeCollection[M]` | ✅ mypy and pyright |
| Compilation | Compile-once → immutable graph | decided |
| Execution | **Synchronous AND asynchronous**, over the same colorless seam | ✅ implemented |
| Multi-engine | Three axes: **Dialect** / **Driver** / **Introspector** | ✅ Postgres, MySQL/MariaDB, SQLite |
| Engine differences | Declared in a capability catalogue (`Cap` → `Full`/`Degraded`/`Nope`) | ✅ implemented |
| SQL | Always `(sql, params)`; never interpolate values | decided |
| Query entrypoint | `SnakeQuery(Model)` (the entrypoint IS the type `SnakeQuery[T]`) | decided |
| Linking | The decorator compiles and registers loose → `snake_link()` links at the end | ✅ proven |

## Pipeline

```text
   Python classes (@snake_model)              Model modules, imported
             │                                          │
             ▼                                          ▼
   Phase 1: compile_model()  ──────►  SnakeTableInfo registered LOOSE
   (compiler/, run by the decorator)   (registry/) — nothing is linked yet
             │
             ▼
   Phase 2: snake_link()  (linker/) — every model exists now:
            resolves types, pairs FKs, validates, links to-one then to-many
             │
             ▼
   Registry (IMMUTABLE, frozen graph)
             │                    everything below reads the GRAPH, NEVER the class
             ▼
   SnakeTableInfo / SnakeColumnInfo /   ┌────────────┬───────────────┬─────────────┐
   SnakePrimaryKeyInfo /             SnakeQuery      sql/            migration/
   SnakeForeignKeyInfo /             (AST)           (AST + Dialect → sql, params)
   SnakeRelationshipInfo                                  │
                                                          ▼
                                         session/planning.py → Plan (COLORLESS)
                                         sql + params + what to do with the rows
                                                          │
                                            ┌─────────────┴─────────────┐
                                            ▼                           ▼
                                      SnakeSession                 AsyncSession
                                      (SnakeDriver)                (AsyncDriver)
```

**Golden rule**: everything hangs off the graph. The graph does not know what Postgres is, nor does
it know the runtime.

## Components

| Module | Single responsibility |
|--------|------------------------|
| `decorators/` | `@snake_model`, `@snake_view`, `@snake_abstract`, `@snake_db_first`, `@snake_trigger`, `@snake_function`, `@snake_result`, `@snake_row`: compile the class and register it **loose**. No SQL logic. |
| `compiler/` | `compile_model()`: the "class → metadata" step. Walks the descriptors ONCE and returns a frozen `SnakeTableInfo`. |
| `core/` | What everything else stands on and that depends on nothing: `exceptions.py` (the `SnakeError` hierarchy), `converters.py` (the value-travel registry), `signals.py`, `placement.py` (which database, which schema), `config.py`, `sentinels.py`. |
| `fields/` | The descriptor system — the project's thesis. `SnakeColumn`, `SnakeToOne`, `SnakeToMany` and the field specifiers (`snake_int`, `snake_str`, `snake_decimal`, `snake_json`, `snake_enum`, `snake_to_one`, …). |
| `metadata/` | **Frozen** structures: `SnakeTableInfo`, `SnakeColumnInfo`, `SnakePrimaryKeyInfo`, `SnakeForeignKeyInfo`, `SnakeRelationshipInfo`, plus the agnostic enums (`SnakeFkAction`, `SnakeIntSize`, `SnakeServerDefault`, …). |
| `registry/` | `SnakeRegistry`: the store of compiled models (class → `SnakeTableInfo`). Entry point for migrations, SQL and relationships. |
| `linker/` | `snake_link()`: phase 2. Resolves types and relationships, validates, and links to-one before to-many. |
| `expressions/` | `SnakeExpr[T]`, `SnakeCondition`, aggregates, scalar functions, `CASE`/`COALESCE`/`NULLIF`, window functions, and the path collector. |
| `query/` | Typed DSL: `SnakeQuery[T]`, `SnakeJoinedQuery`, compound queries (`UNION`/`EXCEPT`/`INTERSECT`) and `WITH RECURSIVE`. Builds AST, **does not execute**. |
| `sql/` | AST + `SnakeDialect` → `(sql, params)`. The **only** place that emits SQL. |
| `dialects/` | `SnakeDialect` Protocol + `PostgresDialect`, `MySQLDialect`, `SQLiteDialect`, and the capability catalogue (`Cap`, `SnakeCapabilities`, `SnakeSyntax`, `SnakeLimits`). |
| `drivers/` | `SnakeDriver` / `AsyncDriver` Protocols, the concrete drivers, and the **decorator** drivers: pool, logging, timeout, and the sync→async thread bridge. |
| `session/` | Execution: `SnakeSession`, `AsyncSession`, the colorless `Plan` (`planning.py`), row hydration (`mapper.py`), coercion, pre-flight guards, retry, isolation levels, session factory. |
| `migration/` | The migration pipeline: `autodetect` → `diff` → `operations` → `planner` → `render`/`loader` → `runner`/`asyncrunner`, plus `ddl`, `state`, `squash`, `renames`, `realize`. |
| `introspection/` | The db-first path: `SnakeIntrospector` Protocol + Postgres, MySQL/MariaDB and SQLite implementations, drift detection, and model **scaffolding** (code generation). |
| `dto/` | Declared response shapes -> TypedDicts. `snake_dto(...)` is READ out of the user's own file with `ast` and never executed; the generated types go back into a marked region of that same file, and nothing outside it is touched. Imported from `snakeorm.dto`: the facade does not re-export it. |
| `debug/` | The debug panel: driver that records every statement, per-scope collector, `DebugReport` (dict, text, `Server-Timing`, HTML) and the `assert_queries` test helper. |
| `contrib/` | Framework binders: ASGI, WSGI, Django middleware, shared config translation, and the sidecar buffer. |
| `cli/` | The `snakeorm` command: `makemigrations`, `migrate`, `rollback`, `status`, `fresh`, `scaffold`, `check`, `squash`, `tables`, `table`, `advise`, `dto`. |
| `helpers/` | Small utilities shared by consumers that must not know about each other: annotations, MRO collection, safe Python literals. |

Four modules sit at the root because they belong to no layer: `model.py` (the `SnakeModel` base),
`connection.py` (the centralised connection config), `times.py` (UTC handling with no guessed
timezones) and `advisor.py` (the index advisor).

## Metadata: PK/FK with ONE structure

Simple and composite share structure. No special cases.

```text
SnakePrimaryKeyInfo.columns : tuple[...]      # 1 = simple, N = composite
SnakeForeignKeyInfo.pairs   : tuple[(local, remote), ...]   # 1 pair = simple, N = composite
```

`pairs` matches the local columns of `snake_to_one(...)` with the target's PK **by position**. The
join AND-s all the pairs. **Same code for simple and composite.**

## Compiling and linking (cycle-resistant)

With `City ↔ Country`, when `City` is defined the class `Country` does not yet exist. Solution
(`pg_dump` / EF Core pattern): **register everything first, link at the end.**

- **Phase 1 — the decorator.** `@snake_model` calls `compile_model()`, which walks the descriptors
  and produces the frozen `SnakeTableInfo`: columns, PK, indexes, checks. It registers it **loose**;
  it links nothing (the cycles never notice). Relationship annotations that do not resolve yet are
  skipped on purpose — only columns matter here.
- **Phase 2 — `snake_link()`.** It runs once everything exists: `get_type_hints()` resolves the
  targets, FKs are paired against the target's PK **by position**, and the pairing is validated
  (same number of columns, matching Python types) → errors HERE, at startup (fail-fast). Two passes:
  to-one (FK) first, then to-many (the inverses, which read the child's already resolved FK). It is
  idempotent.
- **Requirement**: model files start with `from __future__ import annotations` (annotations are lazy
  strings → no `NameError` at definition time).
- **MANUAL, and deliberately so**: nothing triggers phase 2 for you. You call `snake_link()` once,
  after the model modules are imported. The ORM does not hook `__init_subclass__` or an import hook
  to guess when "everything exists", because it cannot know — the whole point of phase 1 is that a
  model may still be waiting for a module nobody has imported yet, and a link fired too early would
  resolve half a graph and call it done. So forgetting the call is a normal mistake, and it has its
  own exception rather than an `AttributeError`: `SnakeUnlinkedRelationship`, raised by the
  descriptor with the sentence "call `snake_link()` first". The CLI is the one exception — it
  imports the models and calls it itself before diffing or emitting DDL.

## Relationships — where the graph is built

`linker/` resolves them: it matches every declared target against the registry and raises at startup
for one it cannot find (`SnakeRegistryError`: "which is not registered (did you import it?)."), so an
unlinked relationship is never a runtime `AttributeError`.

How to DECLARE one — simple FK, composite FK by position, and the `through`/`via`/`to` bridge of a
many-to-many — is user documentation and lives in
[the relationships guide](../users/guide/relationships.md). It used to be copied here, which meant
one of the two aged first and a reader had no way to tell which.

## Typing and runtime proxy — the heart

The same attribute behaves differently seen from the class or the instance — what this buys the
reader is in [How typing works](../users/reference/typing.md):

| Access | `SnakeColumn[T]` | `SnakeToOne[M]` | `SnakeToMany[M]` |
|--------|------------------|-----------------|------------------|
| Class (`User.x`) | `SnakeExpr[T]` | `type[M]` | `SnakeCollection[M]` |
| Instance (`u.x`) | `T` | `M` | `list[M]` |

**Three descriptors, three different class accesses**, and the third column is the one that carries
the thesis. A to-one keeps the cardinality, so class access hands back `type[M]` and navigation just
keeps going. A to-many CHANGES the cardinality, so class access hands back `SnakeCollection[M]`,
which deliberately does NOT expose the child's columns — only `.any(...)` and the scalar aggregates.
That is what makes `Nation.makers.name` a **type error** (`"SnakeCollection[Maker]" has no attribute
"name"`) instead of the silently row-duplicating query Django compiles and runs. Writing `type[M]`
in this column would describe an ORM this one exists in order not to be.

`User.car.brand.name` → `SnakeExpr[str]` (deep, typed, no plugin). The target's fields are
descriptors → navigation auto-wraps. At runtime the object **accumulates the path**, so the
`SnakeCondition` knows its joins and **the compiler generates them itself** from
`SnakeForeignKeyInfo`. You get the two things that seemed incompatible: deep typing AND automatic
joins.

## Query DSL

`SnakeQuery(Model)` **is** the type `SnakeQuery[T]`. It builds an immutable AST; it **does not
execute**. Execution lives in `SnakeSession` / `AsyncSession` (`session.all(q)`, `session.first(q)`,
…). The filter is `.filter(...)`, not `.where()`.

```python
from snakeorm import SnakeQuery

q = SnakeQuery(City).filter(City.country.name == "España").order_by(City.name).limit(10)
```

It is typed **without a plugin** (unlike Django's `objects`, which forced `django-stubs`). The ORM
delivers the primitive; the domain patterns (Repository, Service) are yours.

## Multi-engine: three axes

Three engines, **all three first-class**: PostgreSQL, MySQL/MariaDB and SQLite ([why the seam
holds](index.md)). Three axes, **never mixed**:

| Axis | What it decides | Protocol | Lives in |
|---|---|---|---|
| **Dialect** | How the SQL is WRITTEN: placeholders, quoting, `LIMIT/OFFSET`, `RETURNING`, upsert, Python→SQL type mapping | `SnakeDialect` | `dialects/` |
| **Driver** | How it is EXECUTED: the DBAPI library, connection, cursor, transaction | `SnakeDriver`, `AsyncDriver` | `drivers/` |
| **Introspector** | How the schema is READ: which tables, columns and FKs a live database already has | `SnakeIntrospector` | `introspection/` |

And inside the dialect there is a fourth cut, because the dialect is not one monolithic piece:
**vocabulary vs grammar**.

- **Vocabulary** — what the engine knows how to do. That is the capability catalogue below.
- **Grammar** — the SHAPE of a statement all three engines can run. `SnakeSyntax` lives in
  `dialects/capabilities.py` and is read by the emitters: `migration/ddl.py` branches on
  `dialect.syntax.alter_column_style is AlterColumnStyle.MYSQL_MODIFY`, and the same object decides
  `DROP INDEX x` vs `DROP INDEX x ON t`, `DROP TRIGGER` scoping, and how an all-defaults `INSERT` is
  written. Grammar is **translated** in the emitter and **never** stops a plan.

Mixing the two hard-wires an emitter to one engine's shape.

**Graph and models are 100% engine-agnostic.** Emission is always `(sql, params)`; values are never
interpolated into the string. That kills SQL injection AND is what makes multi-engine possible —
placeholders are precisely what changes between engines.

## The capability catalogue

What a user does with it is in
[the capability catalog](../users/engines/dialects.md#the-capability-catalog); this is how it is
built.

`dialects/capabilities.py` is the central abstraction for anything multi-engine. It replaced twenty
loose `supports_*` booleans on the dialect Protocol, which could be asked ONE at a time but could
neither be **iterated** (you cannot warn about everything an engine lacks without walking the list)
nor say **"sort of"** (SQLite stores a `Decimal` and returns it exact, but orders it as TEXT).

Three pieces:

```python
from snakeorm.dialects.capabilities import Cap, Degraded, Full, Nope, SnakeCapabilities

caps = SnakeCapabilities(
    declared={
        Cap.RETURNING: Full(),
        Cap.DECIMAL_ORDERING: Degraded("SQLite stores NUMERIC as TEXT: it orders lexicographically"),
        Cap.ALTER_COLUMN: Nope("SQLite would need the whole table rebuilt"),
        # ... and the rest of the catalogue: leaving one out fails on import
    }
)
```

- **`Cap`** — the catalogue of everything any engine can do. Two families: **structural** (if
  missing, the operation cannot run) and **type fidelity** (never stops anything; the value goes in
  and comes back exact, what degrades is the SQL semantics — ordering, comparing, operating).
- **`Support = Full | Degraded | Nope`** — the tri-state. `Degraded` and `Nope` demand a **reason**,
  and it is enforced in `__post_init__`: that string is what the user reads, not a comment. The
  union (rather than a bool plus some text) is what lets both the plan's decision and the warning be
  derived from one source, with no way for them to contradict each other.
- **`SnakeCapabilities`** — what ONE engine answers to the WHOLE catalogue. Its `__post_init__`
  **blows up on import** if a dialect leaves any entry undeclared, and then freezes the mapping. A
  `frozenset` of supported capabilities would be shorter to write and wrong: the one you forgot is
  simply absent, and "absent" reads as "unsupported" — a silent default, in the ORM that shouts.

Its readers: `.can(cap)` answers whether the engine can, **treating `Degraded` as a yes** (calling
it a no would forbid a `Decimal` on SQLite, which stores and returns it exactly), and `.caveats()`
returns every `(cap, reason)` that is not `Full`, in catalogue order, which is what the session
reports **once** per caveat when it opens.

The catalogue is split in two frozensets, and the split is what makes it checkable:

| Set | Meaning | Consequence |
|---|---|---|
| `PLAN_CAPS` | Somebody reads it to DECIDE: it stops an operation or changes the shape of the SQL | A capability in here that nobody reads is dead metadata — `test_every_plan_capability_has_a_consumer` fails |
| `ADVISORY_CAPS` | Everything else: declared in order to WARN | The type-fidelity family, plus `INDEX_METHODS` (enforced by the dialect's own `index_method()`) |

Alongside the capabilities live `SnakeSyntax` (grammar, above) and `SnakeLimits` — numeric ceilings
where `None` does not mean "no ceiling" but "this engine ignores the declared parameter", which is
SQLite's honest answer. `limits.bind_params` is what makes a bulk `INSERT` split into batches, and
what sizes the select-in of `include()` — measured in PLACEHOLDERS, so a composite key costs one per
column and the prefetch filter spends from the same budget (`session/planning.py:parents_per_batch`).

## Type vocabulary: two registries, two questions

Extending the set of types the ORM understands takes two independent axes, and confusing them is the
usual mistake:

| Question | Where | Scope |
|---|---|---|
| How is the COLUMN written? | `dialect.register_type(python_type, sql)` | Per dialect — the same type is `INET` on Postgres and `TEXT` on SQLite. Touches the DDL. |
| How does the VALUE travel? | `register_converter(python_type, to_db=…, from_db=…)` in `core/converters.py` | Global. Touches the round trip, not the schema. |

The value axis can afford to be global only because `from_db` is **idempotent**, and that is
enforced at registration time by `_demand_idempotent`, not on the first read in production. The
reason is the multi-engine one: the same converter serves all three engines and each returns the
column in a different shape — Postgres may hand back the object, SQLite the text. `from_db` has to
swallow both, so applying it twice must equal applying it once.

The registry also refuses to overwrite the types the ORM already handles (`mark_builtin` declares
them from `session/coercion.py`): a global registry is shared by the whole process, and letting a
third-party library change how a `Decimal` travels just by being imported is not an extension point,
it is an accident waiting to happen.

It lives in `core/` because both ends of the trip read it — `sql/adapt.py` when writing and
`session/coercion.py` when reading. Anywhere else would create a cycle between `sql/` and `session/`.

## Sync and async over the same colorless seam

Both execution modes are implemented and exported: `SnakeSession` and `AsyncSession`, `SnakeDriver`
and `AsyncDriver`, six concrete drivers, `migration/runner.py` and `migration/asyncrunner.py`.

What made that possible is that **SQL generation has no color**: it does not execute, so it is
reused as-is. The seam is `session/planning.py`, which holds the only copy of the decisions —which
SQL to emit, and how to interpret the rows that come back:

```text
Plan(sql, params, apply, needs_rows)
      │       │      │        └─ EXECUTE vs QUERY: known by whoever built the plan,
      │       │      │           never guessed from the string
      │       │      └─ rows → domain object (hydration, RETURNING write-back, casting)
      │       └─ never interpolated
      └─ built by sql/, engine-specific only through the dialect
```

The functions in `planning.py` return `(sql, params, apply)` and **none of them touches a driver**.
`SnakeSession` and `AsyncSession` are then thin: get the plan, run it, apply it. Copying a 1000-line
session and putting `await` in front would create two places to fix every bug.

The parity is not a matter of good intentions: both sessions consume the SAME `Plan` and the same
message catalogue, and a test compares the **message** as well as the SQL. In an ORM whose doctrine
is to shout, the message IS the product.

All three engines have an async driver. The Postgres one speaks psycopg 3 natively; the other two
are served by `ThreadedAsyncDriver`, which runs a **synchronous** driver on a thread of its own. That
is not faking async: it is what `aiosqlite` does internally, and for MySQL it gives real concurrency,
because Python releases the GIL while the socket waits. What it does not give is native-protocol
throughput under heavy load — and a native driver would enter as another implementation of the same
Protocol, without touching anything above.

**Drivers compose.** Beyond the six concrete ones, `drivers/` ships decorators that wrap another
driver and that the session cannot tell apart:

| Decorator | Adds |
|---|---|
| `SnakePool` / `AsyncSnakePool` | Lends a CONNECTION per session, with `pre_ping`, `recycle_seconds` and a borrow timeout |
| `LoggingDriver` / `AsyncLoggingDriver` | Records the SQL that flows through, to an injected writer |
| `TimeoutDriver` / `AsyncTimeoutDriver` | Sets a `statement_timeout` on the connection: a hung query drains the pool |
| `ThreadedAsyncDriver` | Serves a synchronous driver as an `AsyncDriver`, one thread per connection |
| `CaptureDriver` / `AsyncCaptureDriver` (`debug/`) | Records every statement into the scope's collector for the debug panel |

## Where a feature goes: above the seam or below it

`EXPLAIN` and server `notices` sit in the same roadmap row and are opposite problems, which is the
clearest way to read the seam.

`EXPLAIN` lives **above** it. The compiler already hands back `(sql, params)` and the dialect owns
the grammar, so the whole feature is:

```python
sql, params = query.to_sql(dialect)        # already compiled, already parametrised
rows = driver.fetch_all(dialect.explain_sql(sql), params)
```

Nothing in `SnakeDriver` moves. `notices` lives **below**: it is an out-of-band channel on the
connection, not a statement, so it cannot be reached without widening the Protocol.

**And widening is the expensive move.** Every wrapper in `drivers/` forwards method by method —
there is no `__getattr__` anywhere and several use `__slots__` — so one new member costs 13
production classes plus the test doubles, and `test_the_two_driver_protocols_declare_the_same_members`
charges it in both colours automatically. The rule that follows: **widen once, with everything that
is going in**, never method by method.

The dialect method returning a per-engine string is the shape to copy (`statement_timeout_sql`,
`explain_sql`, `json_get_sql`): the grammar differs, the execution does not.

## What the plan does NOT normalise

Two known gaps, written here because both look like oversights and are not:

- **The engines' errors arrive raw.** A rejected `CHECK` is a `CheckViolation`, an
  `OperationalError` and an `IntegrityError` depending on the driver. The ORM does not translate
  them, so the user writes the same three-way table the tests do.
- **The shape of an `EXPLAIN` answer is the engine's.** Postgres returns one column, SQLite four,
  MySQL about a dozen, and `plan_raw` checks width strictly, so one declared row cannot serve the
  three. `explain()` therefore hands back the engine's own lines rather than inventing a shape over
  three things that share no fields.

## Guards: the pre-flight layer

`session/guards.py` enforces a **declared limit** in Python, before touching the database:
`_guard_declared_limits` walks the columns and delegates to `_guard_scale`, `_guard_length`,
`_guard_int_range` and `_guard_timezone`; `_guard_required_values` covers the missing-value case.

**Two more guards live in that file and are not about a column's value at all.** They are the file's
only PUBLIC names — the ones above are reached through `_guard_declared_limits`, these are called
straight from both sessions, sync and async, which is the whole point of them living here in one
piece: `guard_can_set_isolation` refuses `SET TRANSACTION ISOLATION LEVEL` on an engine whose
catalogue answers `Nope`, and it moved here because the synchronous session asked the catalogue while
the asynchronous one handed the statement to the driver, so SQLite answered `near "SET": syntax
error`. `guard_uniform_bulk_columns` refuses an `add_all` whose instances do not present the SAME
columns.

That second one is a refusal a user meets head-on, so here it is whole:

```text
SnakeEmitError: Every row of a bulk INSERT must have the same columns, and these Note instances do not: tag, title / title. One model does not mean one shape — a column with a server default stays out of the constructor, so assigning it on some instances and not others splits the batch. Either assign it on all of them or on none, or call add() per instance.
```

One model does not mean one shape: a column with a server default stays out of `__init__`, so two
instances of the same class legitimately end up with different sets of assigned values, and rows with
different columns cannot share one multi-row INSERT. Without the guard, `add_all` branched on the
FIRST row and emitted `DEFAULT VALUES` for every instance whenever that one happened to be empty —
the values of the rest were computed and dropped, while reversing the same list made the emitter
refuse it. The POSITION of an element decided between a loud error and a silent loss of data.

Refusing instead of splitting the batch into groups is the doctrine, and it keeps a second promise
too: grouping would hand the rows back in an order the caller did not choose, which `add_all`
guarantees it does not do.

`snake_str(max_length=5)`, `snake_int(size=SMALLINT)` and `snake_decimal(precision=…, scale=…)` are
**domain rules**, not DDL decoration. If the ORM only wrote them into the DDL, the ENGINE would
enforce them — and then they would mean different things depending on where you run: Postgres
rejects (`value too long`, `smallint out of range`) and SQLite accepts, because it ignores VARCHAR
length and collapses every integer. The SQLite dialect exists so you can work without a server, so
without this the suite goes green in development and the deploy to Postgres blows up.

They live **outside** the session because they are not execution: they do not talk to the driver,
they know nothing about transactions, and they do not care whether anybody awaited.

None of them truncates or rounds. A `max_length` that clips the string turns a rule into silent data
loss; the ORM shouts and the caller decides.

## Risks — status after spikes

| Risk | Status |
|------|--------|
| `slots=True` + per-field descriptors | ✅ models WITHOUT slots; `metadata/` does use slots |
| Storing the value in the descriptor | ✅ `__set_name__` + `object.__setattr__`, leak-free |
| `SnakeToMany[M]` → `list[M]`, and class access that REFUSES the child's columns | ✅ `SnakeCollection[M]`, proven in mypy and pyright |
| Composite FK (AND-ed join, positional mapping) | ✅ design closed |
| Heterogeneous `select()` → `tuple[...]` | ✅ proven with positional overloads |
| Forward-refs + cycles (compiler/linker) | ✅ proven `City↔Country` with `from __future__ import annotations` |
| Async without duplicating the session | ✅ the colorless `Plan`; both sessions consume the same one |
| A second and a third engine | ✅ MySQL/MariaDB and SQLite: a new file each, not a refactor |
