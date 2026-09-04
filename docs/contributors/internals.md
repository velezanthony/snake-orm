# Internals: where each feature lives

`architecture.md` holds the DECISIONS — the pipeline, the seams, why the shape is the shape. This
page is the other half: for each feature the roadmap tracks, **where its code is and what path a
value takes through it**. It is written for somebody about to change one of them.

It is deliberately not the user guide. There you find how to CALL a feature; here, what it does on
the inside and which file to open.


## Queries: one pipeline, two emitters

Every read walks the same road. `SnakeQuery` is FROZEN: each builder method returns a new one, so
a fragment can be stored and reused without anybody mutating it behind your back — which is what lets
`shared/selectors/` exist as plain functions.

`to_sql` is the only door out, and it hands back a tuple. Nothing below it touches a driver.

```text
query/query.py     SnakeQuery.filter/order_by/limit/offset/distinct/group_by/having
                   -> a NEW SnakeQuery (frozen), never a mutation
query/query.py     .to_sql(dialect) -> (sql, params)      the ONLY door out
sql/select.py      emit_select(...)                        assembles the statement
sql/condition.py   emit_condition_into(...)                the WHERE, by isinstance chain
sql/value.py       emit_value(...)                         the values, by singledispatch
session/session.py _run(plan) -> driver.fetch_all(sql, params)
```

## Conditions and values: two pipelines that do not behave alike

This is the single most useful thing to know before adding an operator. A VALUE node registers
itself and nothing existing changes; a CONDITION node has to be added to a closed chain in three
places, and one of them fails **silently**.

`expressions/paths.py` returning `[]` is what plans the JOINs. Forget the branch and the query emits
an unqualified column with no join behind it — and no exception anywhere.

```text
VALUE  (SnakeValue[T])            open, additive
  sql/value.py      @emit_value.register(TheNode)   nothing else changes

CONDITION (SnakeCondition)         closed, three places
  sql/condition.py      isinstance branch   -> missing = SnakeNodeError   LOUD
  expressions/paths.py  isinstance branch   -> missing = return []        SILENT
  migration/render.py   isinstance branch   -> only for CHECK / partial index
```

## Relationships: the graph is built once, at link time

The decorator compiles each class on its own and registers it loose; `snake_link()` is what ties
the ends together, and it HAS to be called. Until then a relation knows its own name and nothing
about its target.

Deep navigation (`A.b.c.d`) is the class-access overload of the descriptors, resolved against that
graph — no codegen and no type-checker plugin.

```text
decorators/model.py   @snake_model  -> compile ONE class, register it loose
linker/              snake_link()   -> resolve every target, both directions
metadata/            SnakeRelationshipInfo(source_table, target_table, ...)
                     target_table follows the DECLARATION, not the foreign key
fields/relationship.py  class access -> type[M] / SnakeCollection[M]
                        instance access -> the loaded value, or it RAISES
sql/joins.py         include() -> LEFT JOIN (to-one) or a second select-in (to-many)
```

## Writes: a colourless plan, run by either session

Every write is decided in `session/planning.py`, which returns a `Plan` and touches no driver.
That is what makes the two sessions thin, and it is why a bug gets fixed in one place instead of two.

`needs_rows` is carried rather than guessed from the string: whoever built the plan knows whether
there is a `RETURNING` to read back.

```text
session/planning.py  plan_insert / plan_update / plan_delete / plan_upsert
                     -> Plan(sql, params, apply, needs_rows)
sql/insert.py        emits RETURNING where the engine has it
                     without it, the PK comes back via driver.last_insert_id (MySQL)
session/session.py   _run_plan(plan)          sync
session/asyncsession.py  await _run(plan)     same Plan, an await in front
```

## Types: two registries answering two different questions

Going in and coming back are separate problems and have separate code. `adapt_params` prepares a
value for the DBAPI; `converter_for` rebuilds the declared type from whatever the driver returned.

Bug #39 lived exactly here: MySQL hands a `TIME` back as a `timedelta`, and until the converter knew
that, a column declared `time` came back as something else on one engine of three.

```text
WRITE   sql/adapt.py     adapt_param(value, native_arrays=...)
                         native_arrays is answered by the DRIVER, not the dialect
READ    session/coercion.py  converter_for(python_type, scale)
                         resolved ONCE per column, never per row
                         None means 'passes through', and costs nothing
        the converter NEVER handles NULL: the caller guards it beforehand
```

## Queries, one by one

### `filter()` and conditions

Each call returns a NEW query, so a fragment is safe to store. The WHERE is emitted by an isinstance chain that ends in `SnakeNodeError` — a node nobody taught it about fails loudly.

```text
query/query.py      filter(*conditions) -> new SnakeQuery
sql/condition.py    emit_condition_into(node, dialect, params, qualify, correlate)
expressions/paths.py  condition_paths(node)  -> which JOINs the WHERE needs
```

### `order_by` / `limit` / `offset`

The pagination clause is the dialect's, because the three do not spell it alike and two of them take the values as parameters.

```text
query/query.py      order_by(*orders) / limit(n) / offset(n)
dialects/base.py    limit_offset(limit, offset, params) -> str
                    it appends to params: whether a slot can be a placeholder is the engine's answer
```

### `distinct`

A flag on the query that the emitter reads; there is no separate node, because `DISTINCT` is part of the SELECT and not an expression.

```text
query/query.py      distinct() -> new SnakeQuery with the flag set
sql/select.py       emit_select writes SELECT DISTINCT
```

### `group_by` / `having`

`having` reuses the condition emitter of the WHERE: the grammar is the same and only the position changes. A `group_by` over a deep relationship plans its own JOIN.

```text
query/query.py      group_by(*values) / having(*conditions)
sql/select.py       GROUP BY ... HAVING ...
sql/condition.py    the SAME emitter as the WHERE
```

### aggregates (`count` `sum` `avg` `min` `max`)

Value nodes like any other, so they register a handler and change nothing. A `SUM` is typed nullable on purpose: over no rows it is NULL, and pretending otherwise would be the ORM lying about SQL.

```text
sql/aggregate.py    count() / sum_() / avg() / min_() / max_()
sql/value.py        @emit_value.register(...)  -> FUNC(expr)
```

### `string_agg`

One of the few with three different NAMES, so it is a dialect hook. The `order_by` travels inside the call, and SQLite only accepted it from 3.44 — measured, not assumed.

```text
expressions/functions.py  string_agg(value, separator, order_by=...)
dialects/base.py    string_agg_sql(value, separator, order_by, params)
  postgres  string_agg(x, ?)        mysql  GROUP_CONCAT(x SEPARATOR ?)
  sqlite    group_concat(x, ? ORDER BY ...)
```

### `annotate()`

The base row plus correlated scalars, grouped by the PK. The names are validated at build time against the declared `@snake_result`, so a typo fails before any SQL is emitted.

```text
session/session.py  annotate(query, ResultClass, **aggregates)
decorators/result.py  @snake_result declares the container
                    an extra or missing name -> SnakeEmitError, naming it
```

### explicit `join()`

For the projection a relationship does not cover. It goes into the same JOIN list `include()` fills, so the two cannot produce a duplicate.

```text
sql/joins.py        the JOIN list, shared with include()
query/query.py      join(target, on=...) -> new SnakeQuery
```

### `.any()` / correlated `exists`

It emits a correlated subquery, and `condition_paths` returns `[]` for it ON PURPOSE: its columns live inside the subquery and must not drag JOINs into the outer one.

```text
sql/condition.py    SnakeExists -> EXISTS (SELECT 1 FROM ... WHERE ...)
expressions/paths.py  returns [] for SnakeExists: no outer JOIN
```

### correlated scalar subquery

A value node whose body is a whole query. It is what `annotate` builds underneath, so the two share the emitter rather than each growing their own.

```text
expressions/scalar.py  the node
sql/value.py        emits (SELECT ... ) correlated to the outer row
```

### composite `IN` (`snake_keys`)

A typed setter chain that builds the `SnakeTupleIn` which already existed. It adds no `Cap` and no dialect hook — `Cap.ROW_CONSTRUCTOR` was already there and all three answer `Full()`.

```text
expressions/keys.py  snake_keys(M).in_([snake_key(M).set(col, val), ...])
sql/condition.py     SnakeTupleIn -> WHERE (a, b) IN ((?, ?), ...)
                     guarded against the engine's bind-parameter ceiling
```

### `only()` / `defer()`

The projection narrows the SELECT and the instance REMEMBERS what was left out: touching it raises instead of answering `None`, which would be indistinguishable from a real NULL.

```text
query/query.py      only(*columns) / defer(*columns)
fields/column.py    instance access to a deferred column -> SnakeColumnNotLoaded
```

### `iterate()` (server cursor)

The streaming seam, and it lives in the driver Protocol for a reason: with only `fetch_all` a ten-million-row query built the whole list before returning the first row.

```text
session/session.py  iterate(query, chunk=1000) -> Iterator[T]
drivers/base.py     fetch_iter(sql, params, chunk)
  postgres  a real server-side cursor    sqlite/mysql  fetchmany, bounding the peak
```

### `CASE` / `COALESCE` / `NULLIF`

Value nodes with no dialect hook: the three engines write them identically, which is worth knowing because it is rare.

```text
expressions/conditional.py  the nodes
sql/value.py        emitted as-is on the three engines
```

### window functions (`OVER`, frame)

The frame is part of the node, not a string appended later, so the parameter order stays textual — placeholders are numbered by `len(params)`.

```text
expressions/window.py  row_number() / rank() / dense_rank() / lag() ... .over(...)
sql/value.py        FUNC(...) OVER (PARTITION BY ... ORDER BY ... frame)
```

### `UNION` / `INTERSECT` / `EXCEPT`

A compound is its own type with its own `to_sql`, not a query with a flag. Branch parenthesising is a declared capability: SQLite cannot, and the plan stops rather than emitting something it will reject.

```text
query/compound.py   SnakeCompound.to_sql(dialect)
dialects/capabilities.py  Cap.PARENTHESISED_COMPOUND
```

### `WITH RECURSIVE`

The anchor plus the recursive step in one statement. `distinct=True` switches `UNION ALL` to `UNION`, which is what makes a cyclic walk terminate at all.

```text
query/recursive.py  .recursive(on=(child_col, parent_col), distinct=False)
                    reversing the pair walks the other way: ancestors, not descendants
dialects/capabilities.py  Cap.CTE_IN_COMPOUND_BRANCH
```

## Expressions and functions

### Text functions

One `SnakeFunc` member each, plus one entry per dialect. The catalogue guard fires at IMPORT if a dialect forgets one, which is why silence never means 'not supported'.

```text
expressions/scalar.py   SnakeFunc.LOWER / UPPER / TRIM / LENGTH / CONCAT / SUBSTRING / REPLACE
dialects/*.py           _<ENGINE>_FUNCTIONS maps each to its spelling
                        _<ENGINE>_CANNOT declares, with a reason, what it has not
                        set(SnakeFunc) - FUNCTIONS - CANNOT must be EMPTY at import
```

### Date functions

The clearest case in the catalogue of a claim a string test cannot make: the SQL is the same everywhere and what differs is who will run it. SQLite declares it cannot do either.

```text
expressions/scalar.py   SnakeFunc.DATE_TRUNC / EXTRACT
dialects/sqlite.py      _SQLITE_CANNOT: both, with the reason written out
dialects/base.py        date_shift_sql(...)  for the arithmetic, which IS shared
```

### ABS and ROUND

Every SQLite build ships them, so their absence from its table was a BUG (#34) and not a limit. That distinction is the whole reason `_CANNOT` exists beside `_FUNCTIONS`.

```text
expressions/scalar.py   snake_abs(value) / snake_round(value, digits=0)
dialects/*.py           present in all three _FUNCTIONS tables
note: ROUND(double, int) does not exist on Postgres; only the 1-arg form is asserted
```

### CEIL, FLOOR, SQRT and POWER

Translated by the three and, unlike `ABS`, a COMPILE-TIME option in SQLite. That cannot be a `Cap` — a capability is answered by the dialect class, which does not know which binary got linked — so the test asks the binary by running the query.

```text
expressions/scalar.py   snake_ceil / snake_floor / snake_sqrt / snake_power
dialects/sqlite.py      present, with the ENABLE_MATH_FUNCTIONS caveat in a comment
the probe is the query itself: 'no such function' -> skip, with the reason
```

### json_get()

Three engines, three MECHANISMS, and the declared `as_type` is the point: without the cast a comparison runs over TEXT, where '9' sorts above '100'. The key is interpolated and never parametrised, so it is validated against a strict identifier pattern first.

```text
expressions/expression.py  SnakeValue.json_get(*keys, as_type=...)  -> SnakeJsonGet
                        keys checked against ^[A-Za-z_][A-Za-z0-9_]*$ BEFORE emission
dialects/base.py        json_get_sql(source, key_path, as_type)
  postgres (x ->> 'k')::int   mysql CAST(JSON_UNQUOTE(JSON_EXTRACT(..)) AS SIGNED)
  sqlite   CAST(json_extract(x, '$.k') AS INTEGER)
```

### JSON containment and path operators

NOT implemented, and the shape it would take is written here so the next attempt does not rediscover it. They are BOOLEAN, so they land in the closed condition chain — the one where forgetting `paths.py` loses the JOIN silently.

```text
not implemented. If added:
  as a FUNCTION  -> a SnakeFunc member; test_function_catalogue covers it for free
  as an OPERATOR -> a node + dialect hook + FOUR isinstance branches
either way, the Degraded reason of Cap.JSON says 'cannot query INSIDE it' and would
have to be rewritten: the session shows it to the user at startup
```

### Array operators

NOT implemented. A `list[T]` column already round-trips on the three — native on Postgres, JSON text elsewhere — so what is missing is querying INSIDE it, which is exactly what `Cap.ARRAYS` declares degraded on two engines.

```text
sql/adapt.py        native_arrays is answered by the DRIVER, not the dialect
                    psycopg True   pymysql/sqlite3 False -> json.dumps
session/coercion.py  _to_list rebuilds the list from JSON text on the way back
dialects/capabilities.py  Cap.ARRAYS: Full on postgres, Degraded on the other two
```

### Full-text search

NOT implemented, and the reason is structural rather than effort: SQLite needs an FTS5 VIRTUAL TABLE, so it is not a column but another schema object. A model written once would stop running on the three.

```text
not implemented. The three do not converge:
  postgres  tsvector + to_tsquery + a GIN index
  mysql     MATCH ... AGAINST + a FULLTEXT index
  sqlite    a separate FTS5 virtual table
the honest shape would be Full / Degraded / Nope in Cap, not a common denominator
```

### ILIKE

TWO questions, and reading one for the other is what made `Nope` mean two things. `syntax.has_ilike` says which SHAPE to write; `Cap.ILIKE` says how good the result is. All three engines match without regard to case — one with the operator, two through `LOWER(a) LIKE LOWER(b)` — so nothing is refused and no plan stops. What differs is how much the folding covers, which is a `Degraded`.

```text
sql/condition.py    reads supports_ilike before emitting
dialects/capabilities.py  syntax.has_ilike   -> WHICH SHAPE to write
                          Cap.ILIKE          -> HOW GOOD the result is
  postgres has_ilike=True  Full
  mysql    has_ilike=False Degraded (folds what the collation folds)
  sqlite   has_ilike=False Degraded (folds ASCII only)
```

### for_update() (row locking)

A clause the emitter only writes where the engine has it, read from the catalogue rather than from a version check.

```text
sql/select.py       reads supports_row_locking before appending the clause
dialects/capabilities.py  Cap.ROW_LOCKING
```

### raw()

The escape hatch, and what it still guarantees is the HYDRATION: the declared `@snake_row` shape comes back typed. The width is checked ROW BY ROW, so a query returning nothing passes even with a wrong shape.

```text
session/session.py  raw(sql, params, into=Row) -> list[Row]
session/planning.py plan_raw(into): positional hydration + per-row width check
                    a mismatch raises SnakeEmitError
the placeholder is the dialect's: ask dialect.placeholder(n), never hard-code $1/%s/?
```

## Writes

### insert / update / delete

All three are decided in `planning.py`, which returns a `Plan` and touches no driver. That is why the two sessions are thin and why a bug here is fixed once.

```text
session/planning.py  plan_insert / plan_update / plan_delete -> Plan(...)
sql/insert.py        the statement, parametrised; RETURNING where the engine has it
session/session.py   _run_plan(plan)      asyncsession.py  await _run(plan)
```

### bulk writes

One multi-row INSERT per chunk, and the chunk is bounded by the engine's bind-parameter ceiling rather than by a number somebody liked.

```text
session/session.py   add_all(instances)
dialects/capabilities.py  SnakeLimits.bind_params
  postgres/mysql 65535   sqlite 32766   -> the chunk size is derived, not chosen
```

### RETURNING

Where the engine has it the PK comes back inside the INSERT; where it does not, the session asks the driver for `last_insert_id`. Two paths, one declared capability.

```text
dialects/capabilities.py  Cap.RETURNING   postgres/sqlite Full   mysql Nope
sql/insert.py        appends RETURNING only where supported
drivers/base.py      last_insert_id  is the OTHER path, and only MySQL walks it
```

### savepoint() / set_isolation()

The savepoint is a context manager that names its level (`sp1`, `sp2`) so nesting reuses names deterministically. `set_isolation` RAISES where the catalogue says `Nope` instead of emitting SQL the engine will reject.

```text
session/session.py  savepoint()  -> SAVEPOINT spN / RELEASE / ROLLBACK TO on error
                    the name is INTERNAL, never user data
                    set_isolation(level) -> SnakeUnsupportedFeature where Cap says Nope
dialects/capabilities.py  Cap.SET_ISOLATION
```

### with_retry

It retries only what is worth retrying: a SERIALIZATION conflict, recognised by the engine's own code. Retrying a constraint violation would just repeat it.

```text
session/retry.py    with_retry(work, attempts=..., ...)
                    the retryable set is per engine, not a catch-all except
```

### Constraint failures

One violated constraint, one exception, on the three. Classified from the code the engine sends — never from the message, which is how a detector fails open, and never from the driver's CLASS: on MySQL a CHECK arrives as `OperationalError` and the other three as `IntegrityError`. The driver's exception is chained, so `__cause__` and `driver_error` both keep it.

Not on `fetch_iter`: it is a generator, so the wrapper would hand it back without running a statement — and it walks a SELECT, which breaks nothing.

```text
drivers/failures.py   translate(error)  ->  the ORM exception, or None
                      @translating      ->  execute, fetch_all, commit
  postgres SQLSTATE   23505 23503 23502 23514
  mysql    errno      1062  1452  1048  4025/3819   (its SQLSTATE is 23000 for all four)
  sqlite   errorname  SQLITE_CONSTRAINT_UNIQUE / _FOREIGNKEY / _NOTNULL / _CHECK
never the message, and never the driver's exception class
```

### refresh()

Reads the row back ONTO the object already held, which is the only way to see what a trigger or a default wrote. A refresh of a row nobody else touched proves nothing.

```text
session/session.py  refresh(instance) -> re-reads by PK and writes the fields back
the demo exercises it where a TRIGGER keeps Post.visit_count
```

## Models and types

### Polymorphic inheritance

Single table with a discriminator column. The compiler records which subclass each value names, so a query on the base hydrates the right class without a second read.

```text
decorators/model.py   the subclass declares its discriminator value
compiler/             one SnakeTableInfo, the subclass map inside it
session/planning.py   hydration picks the class from the discriminator column
```

### Views (@snake_view)

A view is a model whose body is a query, so `view_body()` renders it in the TARGET dialect — a compound view is written afresh per engine. `CREATE OR REPLACE` is a declared capability.

```text
decorators/view.py    @snake_view(query=...)
migration/ddl.py      emit_create_view -> view_body(dialect)
dialects/capabilities.py  Cap.REPLACE_VIEW -> where Nope, DROP + CREATE
```

### Signals and triggers

Two different things on purpose. A SIGNAL is Python and fires around the session; a TRIGGER is DDL and holds even for a write that never goes through the ORM. Bulk writes SKIP signals and say so.

```text
core/signals.py       before_insert / after_update ... around the session
migration/operations.py  CreateTrigger / CreateFunction  -> real DDL
session/session.py    warn_bulk_skips_signals(...) on add_all / delete_where
dialects/capabilities.py  Cap.STORED_FUNCTIONS  Nope on mysql and sqlite
```

### Indexes and constraints

Declared on the model, compiled into the graph, emitted as DDL and diffed by the autodetector. A CHECK that compiles and validates nothing is the failure this path exists to prevent.

```text
fields/index.py       snake_index(...) / snake_unique(...)
decorators/check.py   snake_checks(Model, snake_check(cond, name=...))
                      declared OUTSIDE the class body: inside, the column has no name yet
migration/autodetect.py  indexes and constraints are diffed, not assumed
```

### Partial indexes

A WHERE inside CREATE INDEX. MySQL has none, and the degradation is not uniform: a partial SEARCH index widens to the whole table (same rows, more space) while a partial UNIQUE is REFUSED, because widening it would forbid duplicates the domain allows.

```text
fields/index.py       snake_index(..., where=...)
dialects/capabilities.py  Cap.PARTIAL_INDEXES
migration/ddl.py      widen a SEARCH index, refuse a UNIQUE one
```

### Index methods (GIN / GIST / BRIN)

`USING <method>`, and the set of methods is the engine's. MySQL has BTREE and HASH and not the Postgres ones; SQLite has one kind and therefore takes no method at all.

```text
fields/index.py       snake_index(..., method=...)
dialects/capabilities.py  Cap.INDEX_METHODS
  postgres Full   mysql Degraded (BTREE/HASH only)   sqlite Nope
```

### Comments (db_comment)

Table and column comments that travel to the database. MySQL has no `COMMENT ON`: a comment is a CLAUSE, and changing a column comment means respelling the whole column with MODIFY COLUMN — so anything the database holds that the model does not describe is lost.

```text
fields/column.py      snake_column(db_comment=...)
dialects/capabilities.py  CommentStyle: COMMENT_ON / INLINE / UNSUPPORTED
  postgres COMMENT ON   mysql INLINE clause   sqlite UNSUPPORTED
```

### Type converters (register_converter)

The user's way back for a domain type. It is consulted BEFORE the internal registry, so a subclass of a handled type can declare its own conversion instead of arriving as its base.

```text
core/converters.py    register_converter(type, to_db=..., from_db=...)
session/coercion.py   converter_for: user registry FIRST, then the internal one
                      mark_builtin(_CONVERTERS.keys()) stops a user rewriting a builtin
```

### UTC helpers (SnakeUtc, utc_now, to_utc)

`SnakeUtc` is a `datetime` subclass that cannot be naive. Only Postgres has a zone-carrying type, so on the other two the guarantee belongs entirely to the ORM — which is why the round trip is asserted on the three.

```text
times.py             utc_now() / to_utc(v) / utc_from_zone(v, zone) / parse_utc(s)
                     SnakeUtc.of / .from_zone / .parse / .to_zone(zone)
session/coercion.py  _to_snake_utc closes the trip on the engines without a zone type
```

## Engines and drivers

### Startup caveat warning

The session warns ONCE per engine per caveat, and only about type caveats a model actually declares — so a project with no JSON column never hears about JSON.

```text
session/session.py  _warn_reduced_fidelity(dialect) from __init__, both sessions
                    _warned_caveats: module-level, so it is once per PROCESS
                    _relevant_caveats: all structural + type ones the models use
dialects/capabilities.py  caveats() -> (cap, reason) for everything not Full
```

### Synchronous drivers

Three implementations of one Protocol. The heavy dependency is imported INSIDE `connect`, so importing the driver does not drag psycopg2 or PyMySQL into a project that does not use them.

```text
drivers/base.py     SnakeDriver: fetch_all / fetch_iter / execute / last_insert_id
                    commit / rollback / savepoint / release / rollback_to / close
drivers/psycopg.py  drivers/pymysql.py  drivers/sqlite.py
the connection object is never exposed: that is what lets one dialect serve every driver
```

### Asynchronous drivers

Postgres speaks psycopg 3 natively; the other two run their SYNCHRONOUS driver on a thread of their own, which is what `aiosqlite` does inside and gives real concurrency on MySQL because the GIL is released while the socket waits.

```text
drivers/asyncbase.py     AsyncDriver: the SAME members, checked mechanically
drivers/asyncpsycopg.py  native
drivers/threaded.py      ThreadedAsyncDriver, max_workers=1 as a CORRECTNESS rule
drivers/asyncsqlite.py + asyncpymysql.py  subclass it, adding only connect()
```

### Connection pool

The pool is engine-agnostic: it takes three callables and only the RULE lives in it. The pooled driver is INNERMOST, so `close()` walks down the decorator chain and reaches a close that GIVES THE CONNECTION BACK.

```text
drivers/pool.py     SnakePool(borrow, give_back, close_all, pre_ping=, recycle_seconds=, timeout_seconds=)
                    _PooledDriver.close() rolls back FIRST, then gives back
                    psycopg_pool(dsn, ...) is the only shipped factory, Postgres only
for the other two, write borrow/give_back/close_all: that is the intended surface
```

### Statement timeout

A production knob, not a nicety: one hung query drains a pool. It is a dialect string because it is Postgres-only syntax, and SQLite answers `None` — so `TimeoutDriver` REFUSES to wrap it rather than hand back a connection that looks capped and is not.

```text
dialects/base.py    statement_timeout_sql(ms) -> str | None
  postgres SET statement_timeout = ms   mysql SET SESSION max_statement_time = s
  sqlite   None  (busy_timeout waits for a LOCK; it does nothing about a slow query)
drivers/timeout.py  None -> SnakeDialectError at construction, never a silent no-op
```

### Logging driver

A decorator that records what flows through, to an INJECTED writer — so a test collects into a list and production sends it wherever it likes. It logs the boundaries too, which is how a missing COMMIT becomes visible.

```text
drivers/logging.py  LoggingDriver(inner, write=...)
                    COMMIT / ROLLBACK / CLOSE are logged, not only the SELECTs
order matters: put it INNERMOST of the decorators and it records what they do too
```

## Migrations

### Diff and autodetection

It compares the compiled graph against the previous state, never against the live database — a migration has to be reproducible without a server. Drift against the real schema is a DIFFERENT tool, on purpose.

```text
migration/autodetect.py  graph(previous) vs graph(now) -> [SnakeOperation]
                    columns, indexes, constraints and comments are all diffed
a NARROWING change (a shorter NUMERIC) is EMITTED and WARNED, not blocked:
the tool points, the human decides, and the engine is still the last net
```

### Runner (atomic per migration)

One transaction per migration, not per operation: half a migration applied is worse than none. Where the engine has transactional DDL that is real; where it has not, the runner says so rather than pretending.

```text
migration/runner.py      + asyncrunner.py, sharing the operation list
dialects/capabilities.py Cap.TRANSACTIONAL_DDL
migration/operations.py  SnakeOperation is runtime_checkable: the runner dispatches
                         by STRUCTURE (up_sql vs run/unrun), not by a registry
```

### RebuildTable (SQLite's way out)

SQLite cannot drop a column a foreign key names and has no DROP CONSTRAINT to clear the way, so the table is rebuilt: create the new one, copy, drop, rename. It is the USER's call and goes in an explicit operation rather than happening behind their back.

```text
migration/operations.py  RebuildTable(...)
                    the PRAGMA is a NO-OP inside a transaction: measured, not assumed
dialects/capabilities.py  Cap.DROP_COLUMN_CASCADES_FK
```

### RunPython (data, with reverse)

A data migration is code, so it declares its own way back. The runner recognises it by STRUCTURE — it has `run`/`unrun` instead of `up_sql` — which is why no registry has to be kept in step.

```text
migration/operations.py  SnakeDataOperation: run(session) / unrun(session)
                    runtime_checkable, dispatched by shape
a RunPython without a reverse is a migration that cannot be rolled back, and says so
```

### Collapsing (squash)

Many migrations into one, keeping the resulting STATE identical. What it cannot collapse is a `RunPython`: arbitrary code has no algebra, so it is carried through rather than merged.

```text
migration/squash.py  folds the operation list, preserving the final graph
a data operation survives the fold untouched
```

### Cross-app dependencies

Migrations from several packages ordered into one line. The loader builds a graph and refuses a cycle out loud instead of picking an order and hoping.

```text
migration/loader.py  reads each package, resolves `depends_on` into one order
                    a cycle raises, naming the migrations that close it
```

### DDL emitters by engine (the matrix)

Every emitter, times every dialect. The surface is enumerated FROM THE CODE with `vars(ddl)`, so a new emitter without an entry fails the matrix — a green matrix over an incomplete list is the failure this guards against.

```text
migration/ddl.py    emit_create_table / emit_add_column / emit_create_index / ...
the matrix skips per DECLARED capability, quoting it:
  'SQLite cannot: supports_schemas (`realize` stops it)'
and a CONTROL test asserts that what it says cannot run really cannot
```

## Database-first

### PostgreSQL introspection

It reads the live catalogue and builds the same metadata graph the decorator builds, so everything downstream — scaffold, drift, DDL — works on it without knowing where it came from.

```text
introspection/postgres.py  reads information_schema + pg_catalog
                    -> SnakeTableInfo / SnakeColumnInfo / ...  the SAME shapes
introspection/base.py  SnakeIntrospector Protocol
```

### MySQL introspection

The same Protocol over another catalogue, and the differences are not cosmetic: MySQL folds an empty comment and no comment into one value, so what comes back is what the model can describe and no more.

```text
introspection/mysql.py   information_schema, MySQL's own columns
an empty comment and no comment are the same value here: it cannot be round-tripped
```

### SQLite introspection

PRAGMAs rather than a catalogue, and the type is what the column DECLARED — SQLite stores affinity, so a scaffold reads the declaration, not the values.

```text
introspection/sqlite.py  PRAGMA table_info / index_list / foreign_key_list
the declared type is the source: affinity means the values do not tell you the type
```

### Model scaffold

Turns an introspected graph into Python source. It renders generic aliases RECURSIVELY and registers the imports that recursion needs; what it cannot render it REFUSES out loud rather than degrading.

```text
introspection/scaffold.py  graph -> source text
                    render_type recurses, and the recursion is what registers imports
                    what cannot be rendered raises; it does not fall back to a guess
```

### Drift detection

Compares the code against the LIVE database, which is the opposite question to the autodetector's. It only looks at what the code DECLARES: another application's tables in the same database generate no noise.

```text
introspection/drift.py   declared graph vs current_schema()
                    include_unmanaged=True brings in the @snake_db_first mirrors
                    it compares storage_type, not python_type
```

## Debug

### Collector and DebugReport

The capture driver writes into a scope held in a `ContextVar`, so nothing is threaded through the call chain — and with no scope open it delegates straight through at zero cost. The origin is resolved INSIDE `add`, while the caller's stack is still alive.

```text
debug/capture.py     CaptureDriver(inner, system=...)  installed via config.open(wrap=...)
debug/collector.py   capture_queries() opens the scope; current_collector() reads it
                     no scope -> delegate, no cost
debug/record.py      QueryRecord(n, sql, params, duration_ms, rows, kind, origin, ...)
```

### ssr channel (HTML panel)

Self-contained HTML with no dependencies, which is a requirement rather than a style: the panel has to work when what is broken is the configuration it would otherwise read.

```text
debug/html.py        render_report_html / render_report_page
the panel is BILINGUAL by design: debug/assets/js/language.js holds LANG = { ES, EN }
that exemption covers the text TABLE, not the file: its comments are English
```

### envelope channel

The report added to the JSON response. It is in `RISKY_CHANNELS`: it returns SQL to the client, so `allowed_channels()` throws it out in production.

```text
contrib/deliver.py   folds report().to_dict() into the JSON body
debug/channel.py     SnakeDebugChannel.ENVELOPE, inside RISKY_CHANNELS
```

### timing channel (Server-Timing)

A standard header, so any browser's devtools reads it with no panel at all. It carries the three durations separately, because `app` is `wall - db - mapping` and merging them hides where the time went.

```text
debug/timing.py      Server-Timing: db;dur=..., map;dur=..., app;dur=...
isolating MAPPING is what showed the cost was hydration and not the query
```

### sidecar channel

The full report served at its own URL behind a token, so the response itself stays clean. Also in `RISKY_CHANNELS`.

```text
contrib/sidecar.py   GET /__snake__/{token} -> render_report_page(...)
debug/channel.py     SnakeDebugChannel.SIDECAR, inside RISKY_CHANNELS
```

### otel channel (OTLP spans)

Spans to a real tracer over OTLP/HTTP, using OpenTelemetry's OWN variable names — anyone who has configured another exporter already has them set. A transport failure never reaches the caller: the spans are lost and it says so once.

```text
debug/otel/exporter.py   POSTs to OTEL_EXPORTER_OTLP_ENDPOINT
debug/otel/spans.py      one span per statement, db.system.name from the backend enum
a failed export warns ONCE and stays quiet after: telemetry must not break the request
```

### Index advisor

It reads the EMITTED SQL against the metadata and says which filter or FK column looks unindexed. It does not run `EXPLAIN`: it guesses from the statement, while `explain()` asks the engine — two different questions that pair well.

```text
advisor.py           index_hints_from_sql / index_hints_from_records(min_ms=...)
                     regex over the emitted SQL + the declared metadata
contrib/deliver.py   wires the hints into the debug panel
```

### ORM error page

NOT implemented, and the prerequisite is the expensive half: almost every class in `core/exceptions.py` has no `__init__` and not one attribute — `SnakeIntegrityError` is the single exception — so the `Cap` that refused an operation is melted into an f-string and thrown away.

```text
not implemented. The order it would go in:
  1. structured data on the exceptions       the expensive part, 19 classes
  2. exc.add_note(...)  (PEP 678)            appears in Django's page, the admin
                                             email and the console, subclassing nothing
  3. a channel of its own reusing render_report_page
it enters RISKY_CHANNELS the same day it is declared: an error page carries SQL
```

## Integration

### WSGI / ASGI / Django contrib

The core is framework-agnostic and the adapters are thin: open the capture scope, run the request, deliver by the configured channel. The ASGI headers must stay ASCII — a non-ASCII one broke Starlette's test client, and that is why the panel's own labels never travel in a header.

```text
contrib/wsgi.py + contrib/asgi.py   middleware: open scope, deliver, close
contrib/django.py                   translates DATABASES into SnakeConnectionConfig
contrib/config.py                   open_session(config) wraps with CaptureDriver
headers stay ASCII: latin-1 is the ASGI spec's encoding for them
```

### CLI (schema and migrations)

The commands resolve the connection BEFORE looking at the migrations directory, so 'there are no migrations' can name which database it is talking about — a message that used to be true and useless at the same time.

```text
cli/                 makemigrations / migrate / rollback / status / fresh / squash
                     scaffold / check / advise / tables / table / dto
                     the DSN is resolved first: the message names the connection
core/config.py       DB_* is the public contract, read here and by the demos
```
