# PostgreSQL, MySQL and SQLite

```python
from snakeorm import (
    MySQLDialect, PostgresDialect, PsycopgDriver, PyMySQLDriver,
    SQLiteDialect, SQLiteDriver, SnakeSession,
)

pg     = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())
mysql  = SnakeSession(PyMySQLDriver.connect(host="...", database="..."), MySQLDialect())
sqlite = SnakeSession(SQLiteDriver.connect("./my.db"), SQLiteDialect())
```

Same model, same query. Only the **driver** and the **dialect** change. And you don't even have to
pick them by hand: `SnakeConnectionConfig(backend=...)` pairs them up, so nobody can wire one
engine's driver to another engine's dialect. Every driver, dialect and config in that block is in
[Engines](../reference/api/engines.md).

## The three axes

| Axis | What it decides | Protocol |
|---|---|---|
| **Dialect** | How the SQL is WRITTEN | `SnakeDialect` |
| **Driver** | How it is EXECUTED | `SnakeDriver` |
| **Introspector** | How the schema is READ | `SnakeIntrospector` |

Keeping them apart is what makes adding an engine **a new file, not a refactor**.

## The golden rule

**Models and the metadata graph are 100% engine-agnostic.** The dialect only comes into play when
emitting and executing SQL. That's why `SnakeFkAction`, `SnakeServerDefault` and `SnakeIndexMethod`
are agnostic enums the dialect translates, not PostgreSQL strings written into the model.

## What changes between the three

| Capability | PostgreSQL | MySQL / MariaDB | SQLite |
|---|---|---|---|
| Named schemas | Yes | **No** — a schema IS a database | **No** — they're attached databases |
| `ALTER TABLE ADD CONSTRAINT` | Yes | Yes | **No** |
| `ALTER COLUMN` | Yes | Yes (`MODIFY COLUMN`) | **No** |
| Transactional DDL | Yes | **No** — implicit commit | Yes |
| `SELECT ... FOR UPDATE` | Yes | Yes | No |
| Table and column comments | Yes (`COMMENT ON`) | Yes, as a CLAUSE (`... COMMENT = '...'`) | **No** — it stores none |
| `RETURNING` | Yes | **No** — the PK comes from `lastrowid` | Yes |
| `ILIKE` | Yes, the operator | Written `LOWER()`; folds what the collation folds | Written `LOWER()`; folds ASCII only |

!!! danger "A dialect that forgets one capability does not import"

    `Cap` is answered WHOLE or the dialect raises `SnakeDialectError` on construction, naming every
    capability it left out. There is no default: an undeclared one would read as unsupported without
    anybody having decided that, which is a silent default in the ORM that shouts.

The ORM reads those capabilities from the dialect. **It never ignores them silently**: it either
translates to an exact equivalent, or it stops and says so.

### And what's done HALFWAY gets declared too

There's a third answer besides yes and no, and it's the one you notice most day to day: the engine
does it, but it lies about something. A `Decimal` in SQLite is stored as TEXT — it comes back
**exact**, and it sorts like text, so `'9.99'` lands after `'10.00'`. A `SnakeUtc` in MySQL keeps the
whole instant, and the engine doesn't treat it as a date when comparing.

The session tells you about all of that **when you open it, once per thing**, and only about what
your models actually use. If you already have one under control:

```python
import warnings
from snakeorm import SnakeWarning

warnings.filterwarnings("ignore", category=SnakeWarning)
```

### A type the engine doesn't have

It isn't rejected: it falls back to `TEXT` and **works**. The value goes in and comes out exact —text
loses nothing— and what degrades is the SQL semantics. That's how the same model runs on all three
engines, with whatever each one leaves behind said out loud instead of discovered in production.

### Non-transactional DDL in MySQL

MySQL commits implicitly on every DDL statement, so **a migration of N steps is not all-or-nothing**:
if step 3 fails, the first two are already applied. The ORM can't fix that —it isn't its business—
but it does stop in the PLAN everything it knows that engine can't do, so the failure doesn't land
halfway through a deploy.

## The capability catalog

Everything above comes out of one place: `Cap`, the enum that lists everything any engine could do.
Each dialect declares a `SnakeCapabilities` answering the **whole** catalog, member by member, with
one of three values.

How many members it has today is not written here on purpose: the catalog grows, and a number copied
into prose is a copy nobody updates. The order that answers it:

```bash
uv run python -c "from snakeorm.dialects.capabilities import Cap; print(len(list(Cap)))"
```

```python
from snakeorm.dialects.capabilities import Cap, Degraded, Full, Nope, SnakeCapabilities

capabilities = SnakeCapabilities(
    {
        Cap.RETURNING: Full(),                       # does it, and does it right
        Cap.UPSERT: Nope("no ON CONFLICT in this engine"),
        Cap.DECIMAL_ORDERING: Degraded("stored as TEXT: sorts lexicographically"),
        # ... and the rest of the catalogue, every last member of it
    }
)
```

`Degraded` and `Nope` **demand a reason**, and it isn't a comment: it's the exact text the user reads
when the session opens or when the plan stops. Without it the message would say something can't be
done and leave you just as lost.

!!! danger "A dialect that forgets one capability cannot be imported"

    `SnakeCapabilities.__post_init__` checks that they are ALL answered and raises
    `SnakeDialectError` listing the missing ones — `Cap` does the counting, so nothing here has a
    number to keep up to date. Since the dialect builds its catalog as a class attribute, that check
    fires **when the module is imported** — you can't get a half-declared dialect into a running
    process.

    ```text
    SnakeDialectError: This dialect does not answer 2 capability(ies) of the catalogue: UPSERT,
    ILIKE. Every engine declares them ALL: an undeclared capability would read as
    unsupported without anyone having decided so.
    ```

    This is the deliberate difference from a `frozenset` of supported capabilities, which would be
    shorter to write: in a set, the capability you forgot simply isn't there, and "isn't there" reads
    as "not supported" — a silent default, in the ORM that shouts. So adding an engine is three
    files and nothing in the core changes, but those three files have to answer everything.

### What STOPS the plan and what only WARNS

The catalog splits into two frozensets, and the difference is what happens to you:

| Set | How many | What it does |
|---|---|---|
| `PLAN_CAPS` | `len(PLAN_CAPS)` | Somebody **reads it to decide**: it stops an operation or changes the shape of the emitted SQL. |
| `ADVISORY_CAPS` | `len(ADVISORY_CAPS)` | Nothing in the plan depends on them. They're declared **to warn**. |

The column is the expression and not a number for the same reason as above: `ADVISORY_CAPS` is
literally `frozenset(Cap) - PLAN_CAPS`, so both sizes move the day a member is added.

`PLAN_CAPS` holds the STRUCTURAL ones — the kind of question whose answer changes the SQL or stops
the operation, rather than colouring a warning. `RETURNING` and row locking are that kind; the
character a dialect uses to quote an identifier is not.

The roll call is not written down here, and that is the same decision as not writing the size above:
a membership list copied into prose rots exactly like a number, silently — and this one had, by the
time anybody went to check. The set answers for itself:

```bash
uv run python -c "from snakeorm.dialects.capabilities import PLAN_CAPS; print(sorted(c.name for c in PLAN_CAPS))"
```

The two people actually run into are `PARTIAL_INDEXES` and `DROP_COLUMN_CASCADES_FK`: a partial
`UNIQUE` index stops on MySQL, and a `DROP COLUMN` over a column a foreign key still holds stops on
MySQL and on SQLite.

`ADVISORY_CAPS` is the rest: the nine type-fidelity ones (`DECIMAL_ORDERING`, `TIMESTAMPTZ`,
`INTERVAL`, `JSON`, `UUID`, `BOOLEAN`, `INT_WIDTHS`, `ARRAYS`, `FLOAT_SPECIALS`) plus **three that
aren't about types at all**:

- `INDEX_METHODS`, enforced by the dialect's own `index_method()` — it rejects a method it doesn't
  know instead of emitting a plain index and lying about it.
- `ILIKE`, which moved here from `PLAN_CAPS` and is the reason `Nope` used to mean two things. All
  three engines match without regard to case — one has the operator, the other two get
  `LOWER(a) LIKE LOWER(b)` from the emitter — so nothing is refused and no plan stops. Which SHAPE to
  write is `syntax.has_ilike`; what this says is how much the folding covers, which is a `Degraded`.
- `CALENDAR_INTERVAL`: adding MONTHS or YEARS to a date, the only part of date arithmetic a calendar
  has to interpret. `2026-01-31` plus one month is `2026-02-28` on PostgreSQL and MySQL, which clamp,
  and `2026-03-03` on SQLite, which overflows. Nothing is refused — the date is computed and comes
  back — so it warns rather than stopping. Days, hours, minutes and seconds are a fixed span and the
  three engines agree on them exactly.

### How the startup warning actually works

`SnakeSession(...)` and `AsyncSession(...)` both call the same `warn_reduced_fidelity()` — the one
in `session/shared.py`, which is why there is only one — from their constructor — **the two sessions emit the same warnings**, from the same catalog, with the same text.

- **One warning per caveat, not one concatenated blob.** So you can locate the one that affects you,
  and silencing the one you already handle doesn't silence the other six.
- **Deduplicated by `(engine, capability)`**, in a set the ORM keeps itself — not by message text, so
  tweaking a comma in one reason doesn't bring the whole set of warnings back.
- **The filter is a table of nine capabilities, and it is not the same line as `PLAN_CAPS`.**
  `Cap.DECIMAL_ORDERING` only warns if some registered model has a `Decimal` column; `Cap.ARRAYS`,
  only if there's a `list`. Telling somebody what happens to a `Decimal` when they don't have one is
  noise, and noise ends up in a blanket `filterwarnings("ignore")` for the whole category.
- **Generics are reduced to their base**: a `list[str]` column counts as `list`. The caveat belongs
  to the container (the engine has no arrays), not to what's inside.
- **Everything outside that table warns whatever your models say.** All of `PLAN_CAPS`, because
  whether you're going to call `upsert()` or `for_update()` can't be known by reading them — and
  also the two advisory ones that aren't about a type. `INDEX_METHODS` and `CALENDAR_INTERVAL` have
  no Python type to key on: any date column can be given a month, so on SQLite, the one engine that
  doesn't answer `Full()` to `CALENDAR_INTERVAL`, its caveat comes out on every session.

| Capability | Warns only if a model declares |
|---|---|
| `DECIMAL_ORDERING` | `Decimal` |
| `TIMESTAMPTZ` | `SnakeUtc` |
| `INTERVAL` | `timedelta` |
| `JSON` | `dict` |
| `UUID` | `UUID` |
| `BOOLEAN` | `bool` |
| `INT_WIDTHS` | `int` |
| `ARRAYS` | `list` |
| `FLOAT_SPECIALS` | `float` |

That table is the WHOLE filter. A capability that isn't a row of it isn't filtered at all.

PostgreSQL answers `Full()` to the entire catalog, so its `caveats()` is empty and opening a session
against it says nothing at all. That isn't a template — it's the measuring stick for the other two.

### Grammar is not capability: `SnakeSyntax`

The SHAPE of a statement isn't a capability. All three engines drop indexes; they just write it
differently, and mixing that into the capabilities is what once left `emit_alter_column` hardwired to
Postgres's shape. The differences that are pure grammar live in `SnakeSyntax`, get **translated** in
the emitter, and never stop the plan:

| Field | PostgreSQL | MySQL | SQLite |
|---|---|---|---|
| `triggers_are_table_scoped` | `DROP TRIGGER x ON t` | `DROP TRIGGER x` | `DROP TRIGGER x` (global) |
| `indexes_are_table_scoped` | `DROP INDEX x` | `DROP INDEX x ON t` | `DROP INDEX x` |
| `alter_column_style` | `POSTGRES_TYPE_USING` | `MYSQL_MODIFY` | `UNSUPPORTED` |
| `empty_insert_style` | `DEFAULT_VALUES` | `EMPTY_ROW` | `DEFAULT_VALUES` |

One of those looks academic and is not: **`empty_insert_style`** is what an INSERT with no values
looks like — a row that is all defaults. It fires on any join table or event table whose only own
column is the autoincrement id. `INSERT INTO t DEFAULT VALUES` is the standard and MySQL doesn't have
it; it needs `INSERT INTO t () VALUES ()`.

`alter_column_style` is an enum of three (`AlterColumnStyle`), not a boolean, because there is no
"the" way: Postgres writes `ALTER COLUMN c TYPE t USING c::t` with `SET`/`DROP NOT NULL` as separate
statements, MySQL rewrites the whole definition with `MODIFY COLUMN c t NOT NULL`, and SQLite can't
do it at all without rebuilding the table — so the plan stops before emitting anything.

A third piece, `SnakeLimits`, holds the engine's **numeric ceilings**: bind parameters per statement
(65535 in Postgres and MySQL, 32766 in SQLite), the precision and scale of a `NUMERIC`, and a date's
fractional-second digits. `None` there doesn't mean "no ceiling": it means the engine ignores the
declared parameter, which is SQLite's answer — it has a per-column affinity and nothing else.

The placeholder ceiling is where the ORM **chunks on its own**, in two places: `add_all()` splits the
bulk INSERT, and `include()` splits the select-in. A prefetch over 100,000 parents emits several
statements instead of one the driver would reject.

### FKs in SQLite

SQLite doesn't support `ALTER TABLE ... ADD CONSTRAINT`. FKs go **inside the `CREATE TABLE`**:

```sql
CREATE TABLE "orders" (
  "id" INTEGER, "customer_id" INTEGER NOT NULL,
  PRIMARY KEY ("id"),
  CONSTRAINT "fk_orders_customer" FOREIGN KEY ("customer_id") REFERENCES "customers" ("id")
)
```

Adding an FK to a table that already existed would require rebuilding it whole: the ORM **stops and
says so**.

!!! info "The driver turns on `PRAGMA foreign_keys = ON` when connecting"

    SQLite ignores FKs by default. An ORM that emits them but doesn't enforce them is the silent
    failure this project is out to kill.

### The three ways to name a SQLite database

A path, `:memory:`, or a `file:` URI — and the URI is the one that buys something the other two
cannot: a database in memory that SEVERAL connections share, which is what a pool or a test suite
wants.

```python
SQLiteDriver.connect("./my.db")                                  # a file
SQLiteDriver.connect(":memory:")                                 # private to this connection
SQLiteDriver.connect("file:cache?mode=memory&cache=shared")      # in memory, SHARED
```

`SQLiteDriver.connect` takes a NAME, not a DSN: handed a `sqlite:` scheme it raises. A DSN is
translated in ONE place, and that place hands back the name:

```python
config = SnakeConnectionConfig.from_dsn(
    "sqlite:///file:cache?mode=memory&cache=shared", SnakeBackend.SQLITE
)
driver, dialect = config.driver_and_dialect()
```

!!! warning "How many slashes an absolute path takes"

    The third slash is the URL's SEPARATOR and not part of the path, so `sqlite:///var/data/app.db`
    names the RELATIVE `var/data/app.db`, and an absolute path takes four:
    `sqlite:////var/data/app.db`. It is the rule SQLAlchemy documents, and it rewards the obvious
    thing: pasting an absolute path into `f"sqlite:///{path}"` produces the four by plain
    concatenation.

    A relative path STAYS relative. SQLite resolves it against the working directory, and deciding
    otherwise would be this ORM guessing what you meant.

Only a string beginning with `file:` is read as a URI; everything else is a literal filename,
question marks included. So `weird?name.db` is that file and not a malformed URI.

!!! warning "A malformed `file:` DSN raises, and it did not always"

    Until the driver passed `uri=True`, `file:cache?mode=memory&cache=shared` was taken as a
    FILENAME: SQLite created a file called exactly that, ampersands and all, and carried on. It
    never failed — it opened a real database, just not the one that was asked for. One of those
    files escaped as far as a commit in this repository. Now a `file:` DSN the engine cannot parse
    stops instead.

### Translate vs. refuse

- **Translated** (an exact equivalent exists): `UNIQUE` → `CREATE UNIQUE INDEX`; `DROP TRIGGER`
  without the `ON table`; `CREATE OR REPLACE VIEW` → `DROP` + `CREATE`.
- **Dropped** (no equivalent, and it doesn't touch the data): the comments on SQLite. The
  `db_comment` isn't emitted; the column is created just the same. This entry used to name MySQL
  too, and it was wrong: that engine stores comments, it just spells them as a clause. Spelling one
  intention differently on each engine is the definition of a dialect's job, so it's now a
  translation — see the row above.
- **Stopped in the PLAN** (no equivalent): `ALTER COLUMN`, `CREATE SCHEMA`, a CHECK over an existing
  table, stored functions. `realize()` cuts with the reason and the alternative:

```text
SnakeMigrationError: The operation AlterColumn cannot be applied: this engine does not
know how to alter an existing column. On SQLite the table has to be rebuilt (create
the new one, copy the rows, drop the old one and rename), and this is the one case
the ORM does NOT do for you: `RebuildTable` only carries constraints and refuses a
pair that disagrees about a column, so do it with an explicit `RunSQL`.
```

## Adding an engine

Three files: a dialect (`SnakeDialect`), a driver (`SnakeDriver`) and —if you want scaffolding— an
introspector. Nothing in the core changes, but the dialect owes the catalog three complete answers:
its `SnakeCapabilities` (the whole catalog), its `SnakeSyntax` and its `SnakeLimits`. Miss one and
the module cannot be imported at all, which is the point.

---

Next: [async](async.md).
