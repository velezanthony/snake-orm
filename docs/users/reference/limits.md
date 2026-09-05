# Known limits

**Part of the contract**, not a list of apologies.

## Of the type mechanism

- **`type[Brand]` is callable.** The checker accepts `Car.brand()`. It does nothing useful and
  there's no way to forbid it with recursive descriptors.
- **`==` over a class expression returns `SnakeCondition`, not `bool`.** Consequence: `assert
  Car.price == 100` **always passes** (it's *truthy*).
- **The `field_specifiers` tuple is duplicated five times.** PEP 681 imposes it. A test keeps it in
  sync; removing it isn't possible.

## Of queries

- **Streaming doesn't coexist with a to-many `include()`.** `session.iterate()` does exist (sync and
  async) and walks the result without materializing it — a server-side cursor on Postgres and MySQL,
  `fetchmany` on SQLite. What it **raises** on is a to-many `include()` or a prefetch: the select-in
  needs ALL the roots to fire its second query, and in streaming they don't exist. A to-one
  `include()` does work (it travels in the same JOIN). Everything else — `all()`, `first()` — does
  materialize the whole result into memory.
- **`only()`/`defer()` do not combine with `include()`.** The emitter with includes builds its
  column list per segment; mixing a subset into it is another piece. It is REFUSED, not
  silently widened, and the message says so.
- **`session.select()` projects FOUR columns at most.** The overloads stop at `c4`, so a fifth is not
  a looser tuple — it is `No overload variant of "select" matches`, at build time. Split the
  projection into two selects, which is also the shape that stays readable. Widening it is a line
  per arity in a file that already carries four.
- **`annotate` validates at runtime** that the query is of the same model as the `@snake_result`, not
  in the checker.
- **CHECKs don't allow subqueries** (`EXISTS`, `IN (SELECT ...)`). Rejected when declaring them —
  PostgreSQL doesn't allow them there either.
- **`in_()` does not chunk by the bind-parameter ceiling.** `add_all()` and `include()`'s select-in
  do; `in_()` emits one placeholder per value, against 65,535 on Postgres and MySQL and 32,766 on
  SQLite. It fails in the driver on execution, not when building. Split a large `in_()` by hand.
- **A composite `IN` has TWO ceilings, and the ORM only guards the one it can know exactly.** The
  placeholders are `width × number of keys`, and going over the engine's declared limit is refused
  before emitting, naming both numbers. PostgreSQL stops EARLIER and for another reason: measured on
  17, it refuses at around eight thousand KEYS with `stack depth limit exceeded` at any width, which
  is the parser's recursion and not the protocol's 65,535. That number moves with the server's
  `max_stack_depth`, so the ORM does not pre-empt it — refusing at a figure copied from one server's
  configuration would forbid on a tuned one what the database there allows. Slice the list of keys
  by hand and combine the results.
- **Bulk writes don't fire signals.** `update_where`/`delete_where` are a single SQL statement; no
  instances to notify. The ORM warns if the model has registered signals.
- **`DISTINCT ON` is out of scope.** `distinct()` emits the standard `DISTINCT` over the whole
  SELECT, never Postgres's `DISTINCT ON (...)`. It is one engine's extension, so if it ever arrives
  it arrives through the `Cap` catalogue with a `Nope` on the other two — not as a method that works
  on one engine of three and stays quiet on the rest. For a Postgres-only query today,
  `session.raw`.

## Of numbers and JSON

- **A `dict` in `JSONB` gets NORMALIZED.** It reorders keys, drops duplicates and normalizes numbers
  (`100.0` == `100`). It's the nature of `jsonb`. For exact text:
  `json_storage=SnakeJsonStorage.JSON`.
- **`json_get(as_type=...)` only takes `str`, `int`, `float` or `bool`.** A `Decimal` or a
  `datetime` raises `SnakeUnsupportedFeature`.
- **A JSON key has to be a plain identifier.** It is emitted INSIDE the statement, not as a
  parameter, so a key with a space or a dot is rejected with `SnakeValueError`.
- **An `int` larger than ±9.2·10¹⁸ doesn't fit.** The default is `BIGINT` (64-bit). Beyond it, use
  `Decimal` (maps to `NUMERIC`, arbitrary precision). The `scale` is **validated on write**
  (`SnakeValueError`).
- **A `datetime` column has no default shape: you pick it.** `snake_datetime()` over
  `SnakeColumn[datetime]` is a WALL-CLOCK time (`TIMESTAMP`, no zone); `snake_datetimetz()` over
  `SnakeColumn[SnakeUtc]` is an INSTANT (`TIMESTAMPTZ`). A `datetime` declared with a bare
  `snake_column()` is rejected at import time, and mixing the two —a zoned value into a wall-clock
  column, a naive one into an instant column— raises `SnakeValueError` on write. The ORM never
  throws a `tzinfo` away in silence.
- **A `TIMESTAMPTZ` column only accepts UTC.** It stores the instant, not the offset: `14:30+02:00`
  would come back from Postgres as `12:30+00:00` and from SQLite as `14:30+02:00`, so `.hour` would
  depend on the engine. Convert it yourself with `to_utc(value)`.

## Of SQLite

- **No named schemas.** The "schemas" are attached databases (`ATTACH`); `schema=` is ignored when
  emitting.
- **No `ALTER TABLE ADD CONSTRAINT`, and there are two outcomes, not one.** CHECKs and FKs go inside
  the `CREATE TABLE`, so changing one on a table that already exists means remaking it. An
  autodetected migration DOES that: the diff collapses the change into a single `RebuildTable`, and
  SQLite spells it out (`PRAGMA defer_foreign_keys = ON`, create the new shape beside it, copy the
  rows, drop the old table, rename). What still **stops and says so** is a plan written by hand: an
  `AddCheck` or an `AddForeignKey` asks `Cap.ADD_CONSTRAINT`, which is `Nope` here, and the plan
  refuses it naming the way out. `UNIQUE` does get translated (to a unique index).
- **Rebuilding is the only way to drop a column a foreign key still holds.** SQLite
  answers `unknown column ... in foreign key definition`, so `Cap.DROP_COLUMN_CASCADES_FK` is `Nope`
  and the plan stops the `DropColumn` naming the key. Unlike MySQL, putting a `DropForeignKey` in
  front does NOT unblock it: this engine has no `DROP CONSTRAINT` either, so that operation stops on
  `Cap.ADD_CONSTRAINT` instead — measured, an autodetected migration that removes a relation and its
  column refuses on both operations. The table has to be rebuilt by hand, with a `RunSQL`.
- **No `ALTER COLUMN`.** Changing the type or nullability of an existing column doesn't exist here.
- **No `CREATE OR REPLACE VIEW` or stored functions.** The first is rewritten as `DROP` + `CREATE`;
  the second stops in the plan.
- **`COMMENT ON`s are dropped when creating, and refused when altering.** A `CREATE TABLE` carrying
  `db_comment` emits the table and leaves the comments out; an `AlterTableComment` — an operation
  whose only job is to change one — stops in the plan with `Cap.COMMENTS`. There is nothing to
  change on an engine that stores none.
- **No `SELECT ... FOR UPDATE`.**
- **It doesn't store sizes or precision.** Its system is one of **affinities**:
  `SMALLINT/INTEGER/BIGINT` are the same `INTEGER`; `VARCHAR(50)/TEXT/CHAR(10)` the same `TEXT`.
  `int_size`, `max_length` and `precision`/`scale` are honored by Postgres; here they're accepted for
  portability but not enforced.
- **A `Decimal` is ordered as TEXT.** Stored as `TEXT` to not lose exactness, so `ORDER BY` is
  lexicographic (`'100.00'` before `'99.00'`). For numeric order: `ORDER BY CAST(price AS REAL)` by
  hand.
- **No arrays either.** Same as MySQL: a `list[T]` is stored as JSON in a `TEXT` column and comes
  back being the same list, but you can't query inside it from SQL.
- **A NaN `float` comes back as `NULL`.** SQLite can't store it (`Inf`/`-Inf` do). Postgres does.
- **No server-side statement timeout.** `TimeoutDriver` refuses to wrap a SQLite driver
  (`SnakeDialectError`): `busy_timeout` waits for a lock, it does nothing about a slow query.

## Of MySQL / MariaDB

- **No stored functions either.** `Cap.STORED_FUNCTIONS` is `Nope` here as well as on SQLite, and for
  a different reason: a routine's body is raw SQL and replacing one relies on
  `CREATE OR REPLACE FUNCTION`, which MariaDB accepts and MySQL rejects outright. One dialect serves
  both, so it cannot promise what only one of them does. `@snake_function` is **PostgreSQL only**.
- **No `RETURNING`.** `add()` recovers the autoincrement PK (`lastrowid`); `add_all()` of a batch does
  NOT fill in the PKs. It isn't silent: the ORM emits a `SnakeWarning` once per engine, and the rows
  DO get inserted — what's left empty is the `id` in memory. If that id was going to be the foreign
  key of the next row, the required-value guard raises `SnakeValueError` naming the column. If you
  need the ids, insert with `add()` one by one, or branch on `session.dialect.supports_returning`.
- **No native instants: `snake_datetimetz()` falls back to TEXT.** MySQL's only zoned type
  (`TIMESTAMP`) tops out in 2038 and `DATETIME` isn't tz-aware, so a `SnakeUtc` is stored as ISO-8601
  text. The instant comes back **whole**, offset included; what's lost is the engine treating it as a
  date when ordering, comparing or operating. It's declared `Degraded`, so the session warns about it
  once. A `snake_datetime()` (wall clock) IS a native `DATETIME`, and its declared precision is
  honoured (`snake_datetime(precision=3)` → `DATETIME(3)`), capped at 6 digits.
- **A `Decimal` has to declare its precision.** There is no unbounded decimal here: a bare
  `DECIMAL` is `DECIMAL(10,0)`, so `9.99` is stored as `10` — measured. It is refused when emitting
  rather than degraded, because Postgres's `NUMERIC` is arbitrary precision and the same model is
  lossless there. Declare `snake_decimal(precision=..., scale=...)` and it is portable across all
  three.
- **A `DECIMAL` tops out at 65 digits and 30 decimals.** Postgres goes up to 1000, so a
  `snake_decimal(precision=500, scale=2)` is valid there and impossible here: it is rejected when
  emitting the DDL, naming the engine. They are two separate ceilings — `DECIMAL(40,35)` has the
  precision within the limit and the scale outside it.
- **No type for `timedelta` or arrays.** Neither is rejected: a `timedelta` is stored as `TEXT` and a
  `list[T]` as JSON in a `TEXT` column, and both come back as themselves. `Cap.INTERVAL` and
  `Cap.ARRAYS` are `Degraded`, not `Nope` — what you lose is the engine adding a duration to a date
  or querying INSIDE the array. `bool` is `TINYINT(1)` and `UUID` is `CHAR(36)` (they round-trip, not
  native).
- **No partial indexes, and the same `Nope` has TWO destinations.** `WHERE` isn't part of MySQL's
  `CREATE INDEX`, so `Cap.PARTIAL_INDEXES` is `Nope` — and what happens next depends on the index. A
  SEARCH index declared with `where=` is **degraded**: the `WHERE` is dropped and the index is
  created over the whole table. It finds the same rows and costs more space, and the session says so
  once. A partial **UNIQUE** index **stops the plan**: widening `UNIQUE(email) WHERE deleted_at IS
  NULL` into `UNIQUE(email)` forbids rows the domain allows, which is a different schema and not a
  slower one. Either drop the `unique=True`, or express the rule with a generated column plus a
  plain `UNIQUE` over it in a `RunSQL`.
- **Dropping the key first is what frees a column a foreign key still holds.** InnoDB needs the index the key sits on and
  answers error `1553`, so `Cap.DROP_COLUMN_CASCADES_FK` is `Nope` and the plan stops the
  `DropColumn` naming the key. The way out is one operation earlier: a `DropForeignKey` before the
  `DropColumn`, which is exactly what the autodetected migration already emits — a hand-written one
  has to say it, and saying it is also what lets the rollback put the key back.
- **DDL isn't transactional.** Each `ALTER`/`CREATE` does an implicit commit: if step 3 fails, 1 and 2
  stay applied. The runner warns about it. Migrate in small, reversible steps.
- **A "schema" IS a database.** There are no named schemas inside one, so `@snake_model(schema=...)`
  doesn't apply here.
- **A comment is a clause, and changing a COLUMN's one rewrites the column.** MySQL has no
  `COMMENT ON` — it's a syntax error — but it does store comments: the table's goes inside the
  `CREATE TABLE` (`... COMMENT = '...'`) and changes with `ALTER TABLE ... COMMENT = '...'`, and a
  column's lives in the column's own definition. That first half is a spelling, and the dialect
  translates it, so a `db_comment` is no longer dropped here. The second half is why
  `Cap.COMMENTS` is `Degraded` and not `Full`: there is no statement that changes ONE column's
  comment, so the ORM emits `MODIFY COLUMN` with the whole definition respelled from your model.
  Everything the model declares survives; anything the database holds that the model doesn't
  describe — a collation, an `ON UPDATE CURRENT_TIMESTAMP`, a generated expression — does not. Note
  too that an empty comment and no comment are the same value on this engine.
- **`TimeoutDriver` emits `SET SESSION max_statement_time`**, which is MariaDB's variable. Oracle's
  MySQL rejects it with `1193 Unknown system variable` when the driver is wrapped.

## Of introspection

- **The round-trip isn't bijective.** `TEXT`, `VARCHAR(50)` and `CHAR(10)` all come back as `str`.
  It's correct, not a bug.
- **What the ORM can't express is warned about, not represented.** Triggers, exotic types and
  expression indexes come out as a comment and a console warning.

## Of migrations

- **Renames aren't detected on their own.** The diff sees a `DROP` and an `ADD`; it **suggests** a
  `RenameColumn` on the console, but doesn't decide. Guessing loses data.
- **A squash stops when it crosses a data migration.** `RunPython`/`RunSQL` mutate rows, so
  collapsing them would mean RUNNING them, and a squash never touches the database. Collapse the
  stretch that reaches up to it and leave the rest of the history as it is.
- **A squash does not delete the migrations it replaces, and that is deliberate.** A database may
  have only some of them applied, and the originals are what let it catch up. Deleting them is a
  decision for a human, later.
- **Toggling `int` ↔ autoincrement is emitted, and on Postgres it's the sequence spelled out.**
  `BIGSERIAL` is not a type: it's a `CREATE TABLE` shorthand, and an `ALTER ... TYPE BIGSERIAL` gets
  `type "bigserial" does not exist` back from the server. So the migration emits what the shorthand
  MEANS — `CREATE SEQUENCE`, `SET DEFAULT nextval(...)`, `ALTER SEQUENCE ... OWNED BY` and a
  `setval` at the current `MAX` so no key repeats — and the reverse drops the default and the
  sequence. MySQL carries it inside the `MODIFY COLUMN`, and demands the column be a key
  (`1075 there can be only one auto column and it must be defined as a key`). SQLite stops at the
  plan, with `Cap.ALTER_COLUMN`.
- **`RebuildTable` only collapses a PURE constraint change, and on SQLite it isn't always enough.**
  When the only thing that changed about a table is its CHECKs and foreign keys, the diff emits one
  `RebuildTable` instead of loose `AddCheck`/`AddForeignKey` operations, and each engine spells it
  its own way — Postgres and MySQL with the minimal `ALTER`, SQLite with the whole rebuild. Two
  limits come with that. First, the collapse needs the constraints to be the ONLY difference: add a
  column in the same step and the table takes the ordinary path, because a pair of snapshots that
  disagreed about a column would apply on SQLite (which recreates from `after`) and not on Postgres
  (whose minimal `ALTER` emits nothing for it) — `RebuildTable` refuses to be built that way and
  names what disagrees. Second, the rebuild carries `PRAGMA defer_foreign_keys = ON`, which moves the
  verdict to the `COMMIT`; that is enough for a table nothing else points at, and NOT enough when
  another table's key names the one being rebuilt — the `DROP TABLE` raises the deferred counter,
  nothing brings it down, and the `COMMIT` refuses. A loud, atomic rollback, not a corrupt schema.
- **`RunPython` without `backward` can't be undone.** The rollback raises an error saying what to add.
- **The async runner doesn't run data migrations.** `RunPython` receives a synchronous session.

## Of polymorphic inheritance

- **A child's own columns have to allow `NULL`.** The table is a single one and they exist in the
  siblings' rows too. Checked when declaring.
- **An unknown discriminator is hydrated as the base class.** The subclass's fields are lost; not the
  row.
- **There is no joined-table inheritance, and it was DISCARDED rather than postponed.** One table per
  subclass joined by the primary key —Django calls it multi-table; SQLAlchemy, `joined table
  inheritance`— does not exist and is not planned. The single table with a discriminator already
  covers the polymorphism the domain asks for, and its price is the `NULL` rule above: a child's own
  columns exist in its siblings' rows too. The joined table would buy those columns back and charge
  a JOIN on every read for them, and it would be a SECOND inheritance strategy running through the
  compiler, the linker, the emitter and the hydrator. If a domain ever outgrows the single table,
  the argument will arrive with it.

## Of declaration and sessions

- **A relation target only importable under `TYPE_CHECKING` breaks `snake_link()`.** The linker uses
  `get_type_hints` (evaluates at runtime): you get a raw `NameError`. Declare models at module level,
  importable at runtime.
- **The session's `__exit__` doesn't close the driver (by design).** It commits/rolls back on exit;
  the driver is injected. To return it to the pool, `session.close()` (sync and async).
- **On Postgres, `TimeoutDriver` sets `statement_timeout` with `SET`, not `SET LOCAL`.** A
  `rollback` reverts it. For a robust timeout, put it in the DSN
  (`options='-c statement_timeout=...'`).
- **The routine name of `call()` / `execute_procedure()` is validated, not quoted.** The arguments
  travel parametrised; the name cannot — no engine takes a placeholder where an identifier goes — so
  it reaches the SQL as written and every dot-separated part must be a plain identifier (a letter or
  `_`, then letters, digits, `_` or `$`). Anything else is a `SnakeValueError` before any SQL exists.
  It is not quoted for you on purpose: an unquoted `CREATE FUNCTION CalculatePayroll` lands in
  PostgreSQL's catalogue as `calculatepayroll`, so quoting the call would stop finding it. For a name
  that genuinely needs quotes, write the statement with `raw(...)`.

## A string primary key needs a length on MySQL

`snake_str(primary_key=True)` with no `max_length` becomes `TEXT`, and MySQL and MariaDB will not
put a `TEXT` column in a key — a key needs a length and `TEXT` has none. The ORM refuses to emit
that `CREATE TABLE` and says which column and which argument:

```python
key: SnakeColumn[str] = snake_str(primary_key=True, max_length=32)
```

**It does not pick a length for you**, and that is the point rather than an omission. A default
`VARCHAR(255)` would make the table build and would put a limit nobody chose into the schema; the
day a value outgrew it, the data would be truncated instead of refused.

Only the PRIMARY KEY is refused. A `UNIQUE` or an index over an unbounded string is accepted by
MariaDB and is left alone, because forbidding what the engine allows is its own kind of wrong.

## What flat-out doesn't exist

- **Identity map.** Two queries to the same row return two objects. `a == b` is `True` (by PK), but
  `a is b` is `False`.
- **Lazy loading.** On purpose: accessing an unloaded relation raises. It's what makes N+1 impossible
  by default.
- **Full-text search.** With `session.raw`, but no typed API.
- **JSON containment and path operators.** `json_get()` reads a key with a declared cast; `@>`, `?`
  and their friends have no typed API. The three engines use three different mechanisms for them.
- **Array operators.** A `list[T]` column round-trips on the three — native on PostgreSQL, JSON text
  elsewhere — but querying INSIDE it has no API. That is what `Cap.ARRAYS` calls degraded.
- **Server notices and `statusmessage`.** The driver Protocol does not expose the cursor, which is
  what lets one dialect serve every driver; the price is that a trigger's warning is invisible.
- **An error page of the ORM's own.** When it blows up inside a framework, the page you get is the
  framework's, and it knows nothing about the ORM.
- **Engines beyond PostgreSQL, MySQL/MariaDB and SQLite.** Those three are all first-class, sync and
  async. For a fourth —SQL Server, Oracle— the seam is ready and the files aren't written.
```python
# No typed API for any of the four. The way through is `raw()`, which still hydrates:
from snakeorm import SnakeRow, snake_row

@snake_row
class Hit(SnakeRow):
    id: int
    title: str

hits = session.raw(
    "SELECT id, title FROM posts WHERE to_tsvector(title) @@ to_tsquery(%s)",
    ["orm"],
    into=Hit,
)
```


---

Back to [how typing works](typing.md) or to the [architecture](../../contributors/architecture.md).
