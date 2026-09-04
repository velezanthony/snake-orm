# Engine capabilities

What each engine can do, from which version, and what SnakeORM does instead when it cannot.

Every cell below was **measured against a real engine**, not read from a manual.

## Supported range

| Engine | Floor | Ceiling | Versions measured |
|---|---|---|---|
| PostgreSQL | 15 | 18.6 | 15.18, 16.14, 17.11, 18.6 |
| MariaDB | 10.11 | 11.8 | 10.11.19, 11.4.13, 11.8.8 |
| MySQL | 8.0 | 9.7 | 8.0.46, 8.4.11, 9.7.2 |
| SQLite | 3.46.1 | 3.53.1 | 3.45.1, 3.46.1, 3.50.4, 3.53.2, 3.53.4 |

Below the floor the ORM refuses to connect, the way Django does with
`minimum_database_version` — it does not degrade quietly into an untested engine.

MariaDB and MySQL share one dialect and are **different engines**, with different floors, as they
also are in Django: `(10, 11)` for MariaDB, `(8, 4)` for MySQL.

## The headline: version almost never matters

Fifteen engine versions probed. Inside each family, **every capability answers the same in every
supported version**, with one exception:

| Capability | Changes at |
|---|---|
| `CHECK_CONSTRAINT_ADD` / `CHECK_CONSTRAINT_DROP` | **SQLite 3.53** |

Everything else is decided by the engine and its flavour, not by the version. That is why the
matrix stays readable: one column per engine, one `Since` for the single case that needs it.

## How to read the table

| Mark | Meaning |
|---|---|
| `Full` | the engine does it natively |
| `≥ x.y` | it does it from that version on; below, it degrades |
| `Degr` | it does not do it; SnakeORM substitutes something and says so |
| `Nope` | it does not do it and there is no substitute; the ORM refuses at compile time |

## The matrix

| Capability | SQLite | MariaDB | MySQL | Postgres | Degrades into |
|---|---|---|---|---|---|
| `RETURNING` | Full | **Full** | Nope | Full | `lastrowid` + one extra round trip |
| `ROW_CONSTRUCTOR` | Full | Full | Full | Full | — |
| `TRANSACTIONAL_DDL` | Full | Nope | Nope | Full | nothing: an N-step migration is not all-or-nothing |
| `UPSERT` | Full | Full | Full | Full | — |
| `PARTIAL_INDEXES` | Full | Nope | Nope | Full | index over the WHOLE table |
| `TEXT_IN_PRIMARY_KEY` | Full | Nope | Nope | Full | none: needs `max_length` to become VARCHAR |
| `CHECK_CONSTRAINT_DDL` | **≥ 3.53** | Full | Full | Full | rebuild the table |
| `ADD_CONSTRAINT` | Nope | Full | Full | Full | FKs go inside `CREATE TABLE`, tables ordered topologically |
| `ALTER_COLUMN` | Nope | Full | Full | Full | rebuild the table |
| `SET_ISOLATION` | Nope | Full | Full | Full | none: one writer at a time is already serialisable |
| `ROW_LOCKING` | Nope | Full | Full | Full | none: SQLite locks the whole file |
| `SCHEMAS` | Nope | Nope | Nope | Full | none: there a "schema" IS a database |
| `STORED_FUNCTIONS` | Nope | **Full** | Nope | Full | none. Both have `CREATE FUNCTION`; only MariaDB can REPLACE one |
| `REPLACE_VIEW` | Nope | Full | Full | Full | `DROP` + `CREATE` |
| `PARENTHESISED_COMPOUND` | Nope | Full | Full | Full | none: a `LIMIT` cannot be confined to one branch |
| `CTE_IN_COMPOUND_BRANCH` | Nope | Nope | **Full** | Full | none: run the recursion on its own |
| `INDEX_METHODS` | Nope | Degr | Degr | Full | BTREE/HASH only, no GIN/GIST/BRIN |
| `DROP_COLUMN_CASCADES_FK` | Nope | Nope | Nope | Full | drop the key first, or rebuild the table |
| `COMMENTS` | Nope | Degr | Degr | Full | clause on `CREATE`/`ALTER TABLE`, not `COMMENT ON` |
| `ILIKE` | Degr | Degr | Degr | Full | `LOWER(a) LIKE LOWER(b)` |
| `JSON` | Degr | Degr | Degr | Full | TEXT (SQLite) / JSON without JSONB (MySQL) |
| `UUID` | Degr | **Full** | Degr | Full | SQLite: TEXT. MySQL: `CHAR(36)`. MariaDB has the type |
| `BOOLEAN` | Degr | Degr | Degr | Full | `INTEGER` 0/1 / `TINYINT(1)` |
| `ARRAYS` | Degr | Degr | Degr | Full | JSON in TEXT; cannot be queried inside nor indexed |
| `DECIMAL_ORDERING` | Degr | Full | Full | Full | TEXT: `'10.00'` sorts before `'9.99'` |
| `TIMESTAMPTZ` | Degr | Degr | Degr | Full | ISO-8601 TEXT; the zone travels in the text |
| `INTERVAL` | Degr | Degr | Degr | Full | TEXT; not comparable as a duration |
| `CALENDAR_INTERVAL` | Degr | Full | Full | Full | months overflow instead of clamping to month end |
| `INT_WIDTHS` | Degr | Full | Full | Full | one `INTEGER`: the range is not enforced |
| `FLOAT_SPECIALS` | Degr | Degr | Degr | Full | `NaN` comes back NULL (SQLite) / cannot be stored (MySQL) |

## MariaDB is not MySQL

The dialect serves both and declares **one** answer. Measured, they differ in four capabilities —
and in all four the declaration follows MySQL, so MariaDB pays for a limitation it does not have:

| Capability | MariaDB 10.11 / 11.4 / 11.8 | MySQL 8.0 / 8.4 / 9.7 | Declared |
|---|---|---|---|
| `RETURNING` | **yes** — answers `((1, 7),)` | no — `1064` | `Nope` **(wrong for MariaDB)** |
| `UUID` | **native type, validates** — bad input `1292` | no such type | `Degraded` **(wrong for MariaDB)** |
| `STORED_FUNCTIONS` | **yes** — `CREATE OR REPLACE FUNCTION` | `CREATE FUNCTION` yes, **`OR REPLACE` no** — `1064` | `Nope` **(wrong for MariaDB)** |
| `CTE_IN_COMPOUND_BRANCH` | no — `1064` | **yes** | `Nope` (wrong for MySQL) |

Three cost MariaDB real features; the fourth costs MySQL one. None of them varies by version: they
are flavour differences, stable across the whole supported range.

## What changed in SQLite 3.53

| Statement | 3.45.1 | 3.46.1 | 3.50.4 | 3.53.2 | 3.53.4 |
|---|---|---|---|---|---|
| `ALTER TABLE … ADD CONSTRAINT … CHECK` | no | no | no | **yes** | **yes** |
| `ALTER TABLE … DROP CONSTRAINT` | no | no | no | **yes** | **yes** |
| `ALTER TABLE … ADD CONSTRAINT … UNIQUE` | no | no | no | no | no |
| `ALTER TABLE … ADD CONSTRAINT … PRIMARY KEY` | no | no | no | no | no |
| `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY` | no | no | no | no | no |
| `ALTER TABLE … ALTER COLUMN` | no | no | no | no | no |

That is why the CHECK left the group and the rest stayed together: 3.53 enabled one of the four.

Debian 13 ships SQLite 3.46.1 and Ubuntu 24.04 ships 3.45.1, so **the degraded path is the normal
one for years to come** and the native one is the exception. Note that `uv`'s Python 3.12 build
links SQLite 3.45.1, below this project's floor.

## SQLite types, probed by behaviour

In SQLite **declaring a type never fails**: an unknown name falls back to TEXT affinity, so
`CREATE TABLE x (v TIPO_QUE_NO_EXISTE)` works and `typeof()` answers `text`. Checking that a type
name is accepted measures nothing there. Each row below probes the claim the reason makes, and every
one confirmed it on **3.45.1, 3.46.1, 3.50.4, 3.53.2 and 3.53.4** — none varies by version.

| Capability | The claim | The evidence |
|---|---|---|
| `UUID` | TEXT, no type, no validation | takes `'esto-no-es-un-uuid'`, `typeof` = `text` |
| `BOOLEAN` | no boolean: 0/1 in an INTEGER | takes `7`, `typeof` = `integer`, gives back `7` |
| `JSON` | TEXT: `json_*` work, no validation on write | takes `'{no soy json}'` as `text`, yet `json_extract` answers `1` |
| `ARRAYS` | no arrays: a `list[T]` goes as JSON in TEXT | `ARRAY[..]` is an error; an `INT[]` column stores `text` |
| `TIMESTAMPTZ` | does not tell tz from naive: both ISO-8601 TEXT | both columns `typeof` = `text`, offset kept inside the string |
| `INTERVAL` | TEXT, not comparable as a duration | ordering `['10 days','9 days']` puts `'10 days'` first |
| `FLOAT_SPECIALS` | a NaN comes back NULL | stored NaN reads back `None`, `typeof` = `null` |
| `DECIMAL_ORDERING` | TEXT, exact, but ORDER BY is lexicographic | the smallest of `'9.99'`/`'10.00'` is `'10.00'` |
| `INT_WIDTHS` | widths are not told apart | `SMALLINT` takes `100000`; same `typeof` as `BIGINT` |
| `ILIKE` | no ILIKE; `LOWER()` folds ASCII only | `ILIKE` is an error; `LOWER('Á')` gives back `'Á'` |

## What the user hears when a session opens

Measured on SQLite with the global registry:

| Kind of caveat | When it is said | How often |
|---|---|---|
| **type** (`Decimal`, `JSON`, `UUID`, `bool`…) | only if a model actually declares a column of that type | once per TYPE, not per column |
| **structural** (`SCHEMAS`, `ROW_LOCKING`, `ILIKE`…) | always | once per capability |

Measured: six `Decimal` columns across two models produce **one** warning; three `JSON` columns
produce **one**. A registry with only `int` and `str` gets no type warnings at all. And each caveat
is said **once per process** — `_warned_caveats` in `session/shared.py` keeps the set, so a second
session repeats nothing.

Seventeen caveats on SQLite: fifteen structural, plus one per degraded type in use. They are
seventeen different limitations, not a repetition.

Five of the structural ones could be filtered the same way the type ones are, because the answer is
in the models: `SCHEMAS` (no model declares `schema=`), `STORED_FUNCTIONS` (no `@snake_function`),
`INDEX_METHODS` (no index declares `method=`), `PARTIAL_INDEXES` (no index declares `where=`),
`COMMENTS` (no `db_comment`). The rest — `ROW_LOCKING`, `SET_ISOLATION`, `ILIKE` — depend on the
queries written at runtime, so warning at startup is the only chance there is.

## The capability states

| State | Resolves to | Carries a reason |
|---|---|---|
| `Full()` | yes, always | no |
| `Degraded(reason)` | works another way | **mandatory** |
| `Nope(reason)` | refuses at compile time | **mandatory** |
| `Since(version, sentence, below)` | `Full()` or whatever `below` says, per `engine_version` | composed at runtime |

`Since` reads the engine version and collapses into one of the others, so nothing downstream ever
sees a `Since`.

`below` is written out because only the capability knows what its absence MEANS: without the CHECK
the operation stops (`Nope`) and the user writes a `RebuildTable`; without a native type it only
warns (`Degraded`). Resolving to a fixed state would turn the first kind into the second and let the
plan emit a statement the engine refuses. The resulting reason names both versions:

> it does not accept `ALTER TABLE ... ADD CONSTRAINT`: a CHECK can only travel inside the
> `CREATE TABLE` … (this engine is 3.46.1; `ALTER TABLE … ADD CONSTRAINT … CHECK` exists from 3.53.0)

Where the version comes from: SQLite reads `sqlite3.sqlite_version_info`, a module constant, with no
connection. Postgres and MySQL read the server, so they answer from the connection — the same place
Django and SQLAlchemy read theirs.

## What the tests must do

A test never skips because "this does not apply here". It reads the matrix for the engine and
version plugged in, and demands what the matrix says:

| The matrix says | The test demands |
|---|---|
| `Full` | the native statement runs and works |
| `Degraded(reason)` | it works through the substitute, **and warns with that reason** |
| `Nope(reason)` | it refuses, with that reason and not a cryptic engine error |
| `Since(v)` | whichever of the two applies to the version in front of it |

And one more, in the other direction: the test also asks the **raw engine**. If the matrix says
`Nope` and the engine accepts the statement, the matrix is lying and the test fails. That is the
only reason anyone found out about SQLite 3.53.

## How to probe without fooling yourself

Five false results were produced while writing this page, all by lazy probes. **A sloppy probe does
not fail — it accuses the matrix of lying.**

| Trap | What it looked like | What it really was |
|---|---|---|
| "it did not raise" | `CAST('NaN' AS DOUBLE)` raises nothing → looks supported | it answers **`0.0`**; storing a NaN answers `1365` |
| a probe that is not the case | recursive CTE as the FIRST branch runs → `Nope` looks false | as the SECOND branch — what the reason says — it answers `1064` |
| an inverted probe | `INSERT 100000` into a `SMALLINT` fails → counted as "no range check" | failing IS the capability |
| a probe wider than the claim | `CREATE OR REPLACE FUNCTION` fails on MySQL → "it has no stored functions" | `CREATE FUNCTION` works fine; only `OR REPLACE` is missing |
| **SQLite accepts any type name** | `CAST('{}' AS JSONB)` works → looks like it has JSONB | `CREATE TABLE x (v TIPO_QUE_NO_EXISTE)` **also works**, and `typeof()` answers `text` |

The last one is the worst and is specific to SQLite: declaring a type NEVER fails there, so a probe
that only checks the type is accepted measures nothing. Probe the BEHAVIOUR — what `typeof()`
answers, how values sort, whether garbage is refused.

Rules that follow:

1. Check the **value** that comes back, not that nothing exploded.
2. Probe the case the reason **describes**, not one that looks like it.
3. When a capability is proved by a **rejection**, the rejection is the pass.
4. Never `pytest.raises(Exception)`: any exception passes it, and that is how `emit_drop_check` kept
   going green while the statement had worked since 3.53 — it dropped a constraint it had never
   created, got `no such constraint`, and took it for the syntax error it expected.

## Rules

1. One capability = one statement an engine can gain or lose on its own.
2. A reason is mandatory and is read by the user, so it names the substitute, not just the lack.
3. Nothing gets declared without being measured on a real engine.
4. The matrix is the source of truth. This page is its portrait, and a test keeps them equal.
