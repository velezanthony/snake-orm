# Columns and types

```python
from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeUtc,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_model,
    snake_str,
)

@snake_model(table="users")
class User(SnakeModel):
    id: SnakeColumn[int] = snake_auto()  # autoincrement PK (out of __init__)
    email: SnakeColumn[str] = snake_str(unique=True)
    bio: SnakeColumn[str | None] = snake_str(default=None)  # nullable by the annotation
    active: SnakeColumn[bool] = snake_column(default=True)
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)

user = User(email="a@b.com")  # keyword-only; only what has no default is required
```

**The rule: the type comes from Python. The metadata only adds SQL information.**

!!! warning "Nullable is not a default"

    `str | None` says the column accepts `NULL`. It does **not** make the argument optional: without
    a `default=` or a `default_factory=`, `User(email="a@b.com")` raises
    `TypeError: User() missing required argument: 'bio'`. They are two separate decisions.

## One specifier per type family

`snake_column()` declares columns **without type parameters**: `bool`, `date`, `UUID`, `bytes`,
`timedelta`, `list[T]`... The families that do have something to declare bring their own specifier.
There are **seven**, and two of them split into a pair of declarators because the choice itself is
the parameter:

```python
stock:      SnakeColumn[int]      = snake_int(size=SnakeIntSize.SMALLINT)
name:       SnakeColumn[str]      = snake_str(max_length=50)       # fixed=True -> CHAR(50)
ratio:      SnakeColumn[float]    = snake_float(size=4)
price:      SnakeColumn[Decimal]  = snake_decimal(precision=12, scale=2)
meta:       SnakeColumn[dict[str, object]] = snake_json(storage=SnakeJsonStorage.JSON)
created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(precision=3)  # or snake_datetime(precision=3)
opening:    SnakeColumn[time]     = snake_time()                   # or snake_timetz()
```

`Decimal` decides the column is `NUMERIC`; `precision` and `scale` decide *which* one. No parameter
changes the type or contradicts the annotation.

They are separate because a `max_length` on an integer means nothing: on a single `snake_column()`
your editor would autocomplete it on **every** column. And if you put one where it doesn't belong,
the compiler **fails at import time**, not during `migrate`:

```python
age: SnakeColumn[int] = snake_str(max_length=50)
# SnakeModelDefinitionError: ... declares max_length=50 with snake_str(), which only
# applies to a str column, but its type is 'int'. The ANNOTATION is what rules the type: ...
```

A parameter that **needs another one** fails at import time too — `fixed=True` without `max_length`
is the case you'll hit:

```text
SnakeModelDefinitionError: A fixed-length column has to say HOW MANY characters: declare
snake_str(max_length=n, fixed=True). A CHAR without a length is CHAR(1) in SQL, and that is almost
never what anyone wants.
```

Same pattern as `snake_enum(...)` for enums and `snake_auto()` for the autoincrement PK.

## Supported types

| Python | Declarator | PostgreSQL | MySQL | SQLite |
|---|---|---|---|---|
| `int` | `snake_int()` | `BIGINT` | `BIGINT` | `INTEGER` |
| `int` (PK) | `snake_auto()` | `BIGSERIAL` | `BIGINT AUTO_INCREMENT` | `INTEGER` |
| `str` | `snake_str(max_length=50)` | `VARCHAR(50)` | `VARCHAR(50)` | `TEXT` |
| `str` (fixed) | `snake_str(max_length=2, fixed=True)` | `CHAR(2)` | `CHAR(2)` | `TEXT` |
| `bool` | `snake_column()` | `BOOLEAN` | `TINYINT(1)` | `INTEGER` |
| `float` | `snake_float()` | `DOUBLE PRECISION` | `DOUBLE` | `REAL` |
| `float` (4 bytes) | `snake_float(size=4)` | `REAL` | `FLOAT` | `REAL` |
| `Decimal` | `snake_decimal(precision=12, scale=2)` | `NUMERIC(12,2)` | `DECIMAL(12,2)` | `TEXT` |
| `SnakeUtc` | `snake_datetimetz()` | `TIMESTAMPTZ` | `TEXT` | `TEXT` |
| `datetime` | `snake_datetime()` | `TIMESTAMP` | `DATETIME(6)` | `TEXT` |
| `date` | `snake_column()` | `DATE` | `DATE` | `TEXT` |
| `time` | `snake_time()` | `TIME` | `TIME(6)` | `TEXT` |
| `time` (with zone) | `snake_timetz()` | `TIMETZ` | `TEXT` | `TEXT` |
| `timedelta` | `snake_column()` | `INTERVAL` | `TEXT` | `TEXT` |
| `UUID` | `snake_column()` | `UUID` | `CHAR(36)` | `TEXT` |
| `bytes` | `snake_column()` | `BYTEA` | `LONGBLOB` | `BLOB` |
| `dict` | `snake_json()` | `JSONB` | `JSON` | `TEXT` |
| `list[int]` | `snake_column()` | `BIGINT[]` | `TEXT` | `TEXT` |

### Four helpers, and why they are not `datetime.now()`

```python
from snakeorm import utc_now, parse_utc, to_utc, utc_from_zone
from datetime import datetime

utc_now()                                          # now, zoned, in UTC
parse_utc("2026-01-01T12:00:00+01:00")             # ISO with a zone -> the instant in UTC
utc_from_zone(datetime(2026, 1, 1, 12, 0), "Europe/Madrid")   # a wall clock -> the instant
to_utc(already_zoned)                              # re-expresses; it does not move the instant
```

`SnakeUtc` is an INSTANT: it goes in zoned and comes back zoned. A naive `datetime.now()` has no
zone, so the instant it names depends on the machine that produced it — which is why these exist
instead of the standard library's shortest call. `utc_from_zone` is the one to reach for when what
you have is a wall clock somebody read off a form.

Every type has a round-trip test on the three engines
(`src/test/integration/test_type_round_trip.py`): it writes a value and demands it come back with its
value **and its type**.

Two entries in that table deserve a word:

- On **MySQL** a `snake_datetimetz()` falls back to `TEXT` in ISO-8601, which keeps the whole
  instant, offset included — more than a `DATETIME` would. MySQL's own zoned type (`TIMESTAMP`) tops
  out in 2038.
- On **SQLite** a `Decimal` is stored as `TEXT`: the `NUMERIC` affinity would turn it into `REAL` and
  you would lose the precision.

!!! danger "On MySQL a `Decimal` MUST declare its precision"

    Postgres maps a bare `Decimal` to an unbounded `NUMERIC` and loses nothing, so the model looks
    fine there. MySQL has no unbounded decimal: a bare `DECIMAL` is `DECIMAL(10,0)`, and **9.99 is
    stored as 10**.

    ```python
    price: SnakeColumn[Decimal] = snake_column()                          # refused on MySQL
    price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)    # portable
    ```

    So the dialect stops the plan instead of choosing a precision nobody declared. And note this is
    not something `Degraded` could have covered: what is lost is not a query capability, it is the
    VALUE.

!!! note "What an engine hasn't got falls back to TEXT, and the VALUE comes back exact"

    That is the rule behind every `TEXT` in the table above: a type the engine has no equivalent for
    is **not rejected**. It falls back to `TEXT` and works — the value goes in and comes out exact.
    What degrades is the **SQL semantics**: ordering, comparing, operating on it. A `list[T]` is the
    clearest case: neither MySQL nor SQLite has arrays, so in both it is stored as JSON in a `TEXT`
    column and comes back being the same list; what you can't do there is query **inside** it.

    Every caveat is a **declared** capability, so you can ask instead of guessing:
    `session.dialect.supports_returning` is public. On opening, the session also warns **once per
    caveat**, and only about the ones your models actually use.

## Primary keys

`snake_auto()` is the autoincrement case. Any other PK is `primary_key=True` on the specifier of its
family, and it is available on all of them:

```python
from uuid import UUID, uuid4

@snake_model(table="countries")
class Country(SnakeModel):                                       # NATURAL key
    code: SnakeColumn[str] = snake_str(max_length=2, fixed=True, primary_key=True)
    name: SnakeColumn[str] = snake_str()

@snake_model(table="invoices")
class Invoice(SnakeModel):                                       # UUID key, generated in Python
    id: SnakeColumn[UUID] = snake_column(primary_key=True, default_factory=uuid4)
    total: SnakeColumn[int] = snake_int()

@snake_model(table="order_lines")
class OrderLine(SnakeModel):                                     # COMPOSITE key
    order_id: SnakeColumn[int] = snake_int(primary_key=True)
    line_no:  SnakeColumn[int] = snake_int(primary_key=True)
    qty:      SnakeColumn[int] = snake_int()
```

Composite is just `primary_key=True` twice: simple and composite share the same internal structure,
so nothing downstream (diff, migrations, joins) has a special case for either. For a UUID generated
by the server instead of by Python, use `server_default=SnakeServerDefault.UUID_V4`.

## A type the ORM doesn't ship

The type vocabulary is **open**: if you need an `INET`, a `CITEXT`, a `TSVECTOR` or a type of your
own domain, you register it and from then on declare it like any other.

There are **two axes**, and both have to be declared: how the column is WRITTEN and how the value
TRAVELS.

```python
from snakeorm import (
    PostgresDialect, SnakeColumn, SnakeModel, SQLiteDialect,
    register_converter, snake_auto, snake_column, snake_model,
)

class Inet:
    """An IP address in your domain."""

    def __init__(self, value: str) -> None:
        self.value = value

# Axis 1 — how it is WRITTEN. Per DIALECT: each engine writes the same Python type differently.
PostgresDialect().register_type(Inet, "INET")
SQLiteDialect().register_type(Inet, "TEXT")

# Axis 2 — how the value TRAVELS. Global, and `from_db` has to be IDEMPOTENT.
register_converter(
    Inet,
    to_db=lambda ip: ip.value,
    from_db=lambda raw: raw if isinstance(raw, Inet) else Inet(str(raw)),
)

@snake_model(table="servers")
class Server(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    address: SnakeColumn[Inet] = snake_column()
```

The first axis goes **per dialect** because the same Python type is written differently by each
engine: `Inet` is `INET` on Postgres and `TEXT` on SQLite, and the model knows about neither one.
Global, importing a library that registers a type would leak it into every dialect in the process.

The second one IS global, on one condition: `from_db` has to be **idempotent**. That is the
`if isinstance` in the example, and it is what lets a single converter read from all three engines,
because each returns the column in a different shape — Postgres with a native `INET` can hand you
the object already, SQLite gives you the text. It is checked when registering, not on the first read
in production. Skip this axis and the type reaches the driver as an object it can't send.

Lookup is by **MRO**, so a `class IPv4(Inet)` inherits the journey — and in the other direction, if
your type inherits from one the ORM already handles (`class Slug(str)`), writing would work and
**reading would give you back a `str`**.

What `register_converter` will **not** do is rewrite a type the ORM already handles — `Decimal`,
`UUID`, `datetime` and company raise `SnakeConfigError`:

```text
SnakeConfigError: <class 'decimal.Decimal'> is a type the ORM already handles, so its converter is
not rewritten. A global registry is shared by the whole process: changing here how a core type
travels would change it too for code that asked for nothing.
```

The dialect axis has no such problem —it is per instance— which is why `register_type(str, "CITEXT")`
IS allowed and makes the whole database case-insensitive.

Unregistered, an unknown type **still fails**. Guessing the SQL type of an arbitrary class would be
worse than refusing; what the error does is tell you how to register it.

## A declared limit is enforced in Python, not delegated to the engine

```python
code:     SnakeColumn[str]     = snake_str(max_length=5)
quantity: SnakeColumn[int]     = snake_int(size=SnakeIntSize.SMALLINT)
amount:   SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
```

These are rules of your domain, and the ORM enforces them **on write**, before touching the
database — with one exception named below:

```python
session.add(Product(code="TOO LONG TO FIT"))
# SnakeValueError: ... declares max_length=5 but an attempt was made to write a text of
#                  15 characters. Trim it yourself before saving it: the ORM does not
#                  truncate in silence.
```

It's what makes **your model mean the same thing on all three engines**. Postgres would reject the
first two (`value too long`, `smallint out of range`); SQLite would accept them, because it ignores
VARCHAR length and collapses every integer to 64 bits. Without the check, developing on SQLite and
deploying to Postgres would be a trap.

!!! warning "`precision` is NOT one of them"

    The guard covers `max_length`, `int_size` and `scale`. It does **not** check `precision`: a
    `Decimal` wider than the digits you declared goes through, and what happens next is the engine's
    call — SQLite stores it, Postgres raises `numeric field overflow`. So this one knob does not
    behave the same on all three, which is the opposite of what the rest of this section buys you.
    Until it does, treat a declared `precision` as documentation for the DDL rather than a rule the
    ORM keeps.

It **shouts**, it never trims. It applies to `add`, `add_all`, `upsert`, `update` and to the bulk
`update_where` too.

### And a required column with no value shouts too

A sibling guard fires on the opposite problem: a column that arrived with **no value at all**.
Leaving one out of the `INSERT` is right almost every time —an autoincrement PK, a column with a
default, one the server fills— so the guard carves out the one case where it isn't: `NOT NULL`, no
default of any kind (`default=`, `default_factory=`, `server_default=`) and no autoincrement. There,
a missing value doesn't mean "let the database put it", it means nobody put it.

```text
SnakeValueError: 'lines.order_id' is mandatory (NOT NULL, without a default and without
autoincrement) and an attempt was made to write it without a value. It usually means the value comes
from another row whose id never came back: on an engine without RETURNING, `add_all()` does not fill
in autoincrementing keys, so use `add()` for the rows whose id you need afterwards.
```

## Dates: an instant or a wall time, and the TYPE says which

```python
from datetime import datetime
from snakeorm import SnakeColumn, SnakeUtc, snake_datetime

created_at: SnakeColumn[SnakeUtc] = snake_datetimetz()  # an INSTANT    -> TIMESTAMPTZ
opening:    SnakeColumn[datetime] = snake_datetime()    # a WALL TIME   -> TIMESTAMP
```

`SnakeUtc` is an instant in UTC, and **one that isn't cannot be built**. A bare `datetime` is a wall
time —an opening hour, a local holiday— that identifies no moment at all until someone says which
zone it belongs to. A guard requires the annotation to match the declarator, and a `snake_column()`
on a date is an error, because it does not say which of the two you want.

There is no `tz=` knob, and that is deliberate: with one, the type and the declarator would both say
the same thing and could contradict each other. Two sources of truth, one of them free to lie — the
exact reason `nullable=` does not exist either.

### Where dates come from, and how they get in

```python
from snakeorm import SnakeUtc

# 1. JS: date.toISOString() -> "2026-06-01T12:30:00.000Z". Already in UTC.
when = SnakeUtc.parse(payload["when"])

# 2. A form: <input type="datetime-local"> -> "2026-06-01T14:30". NO zone.
#    Only YOU know which zone that time is in, so you are the one who supplies it.
when = SnakeUtc.from_zone(datetime.fromisoformat(form["when"]), user.zone)

# 3. Right now
when = SnakeUtc.now()

# 4. A datetime you already have, with a zone
when = SnakeUtc.of(other_aware)
```

### And back out, to render it

```python
appointment.when                              # SnakeUtc: 2026-06-01 12:30:00+00:00
appointment.when.to_zone("Europe/Madrid")     # datetime: 2026-06-01 14:30:00+02:00
```

Stored in UTC, shown in the reader's zone. Converted to Madrid it is **no longer** a `SnakeUtc`
—because it is no longer in UTC— and that is why the type becomes `datetime`.

!!! tip "It is a `datetime` to everything outside"

    `SnakeUtc` inherits from `datetime`, so `isinstance`, `isoformat()`, `strftime()`, DRF, Pydantic,
    Jinja and `json` all work without knowing it exists. What the checker stops is the opposite:
    putting any old `datetime` where an instant is asked for.

!!! warning "An `<input type=\"datetime-local\">` cannot resolve itself"

    `"2026-06-01T14:30"` does not say which zone that time is in, so `SnakeUtc.parse()` **rejects**
    it. Either send the zone along (a hidden field with
    `Intl.DateTimeFormat().resolvedOptions().timeZone`), or take it from the user's profile, or
    convert in JS before sending. What the ORM will not do is assume it.

!!! tip "To see `+00` from `psql` too"

    `TIMESTAMPTZ` stores the instant but **displays** it in the session's time zone. Connections
    opened by the ORM already ask for UTC (it travels in the DSN, no statement executed), so
    anything going through it sees `+00`. Somebody else's `psql` session uses the server's zone
    instead; if you want the eyeball check to hold for everyone, pin it on the database:

    ```sql
    ALTER DATABASE my_database SET timezone = 'UTC';
    ```

## Nullability

```python
nickname: SnakeColumn[str | None] = snake_str()  # NULL allowed
email:    SnakeColumn[str]        = snake_str()  # NOT NULL
```

There's no `nullable=`. The annotation decides.

## Defaults: there are three, and they're different

```python
from snakeorm import SnakeServerDefault

active:     SnakeColumn[bool]     = snake_column(default=True)
created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)
stamped:    SnakeColumn[SnakeUtc] = snake_datetimetz(server_default=SnakeServerDefault.NOW)
```

| | Who computes it | Where it ends up |
|---|---|---|
| `default=` | Nobody: it's a literal | In the DDL's `DEFAULT` **and** in the object |
| `default_factory=` | Python, when building | Only in the object (a fresh value per instance) |
| `server_default=` | The server, on insert | In the DDL; excludes the column from `__init__` |

Declaring two at once is an error when defining the model. `SnakeServerDefault` is engine-agnostic
and has five members (`NOW`, `UUID_V4`, `TRUE`, `FALSE`, `ZERO`); the dialect translates it. For raw
SQL there's `server_default_sql=` (no longer portable).

## Uniqueness

```python
email: SnakeColumn[str] = snake_str(unique=True)
```

It emits a **constraint** `uq_users_email`, not an index. The constraint SAYS the rule; it's what
`ON CONFLICT` and error messages reference. The only exception is the **partial** unique (an index
comes out, because PostgreSQL doesn't allow `UNIQUE ... WHERE`). See
[indexes and constraints](indexes-and-constraints.md).

## Enums

```python
from enum import StrEnum
from snakeorm import snake_enum

class Status(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"

@snake_model(table="users")
class User(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    status: SnakeColumn[Status] = snake_enum(Status, default=Status.ACTIVE)
```

By default it is stored as a string with a `CHECK IN (...)` derived from the members: adding a value
changes the CHECK and the diff generates the migration. The WIDTH is derived too — the longest
member — so the column is `VARCHAR(n)` where the engine has lengths and `TEXT` on SQLite, which has
none. Nothing declares that width: the ORM already knows it from the enum. The round trip returns
the **member**:

```python
user.status is Status.ACTIVE  # True
```

`storage=` chooses which DB object does the checking, and there are two:

```python
from snakeorm import SnakeEnumStorage

status: SnakeColumn[Status] = snake_enum(Status, storage=SnakeEnumStorage.PLAIN)
```

| | What comes out | Cost |
|---|---|---|
| `CHECK` (default) | base type + `CHECK col IN (...)` | removing a member fails at `migrate` if rows still use it |
| `PLAIN` | base type only, no validation | a bad value slipped in through raw SQL blows up **on read** |

There is no `NATIVE`, deliberately. In Postgres `ADD VALUE` has no inverse (recreating the type
rewrites the table under `ACCESS EXCLUSIVE`), the value can't be used in the same transaction that
adds it — and migrations are transactional — and two models sharing the enum share the type. With
`CHECK` none of that happens.

!!! warning "Annotating an Enum without `snake_enum()` is a declaration-time error"

    A single path, explicit. Without it, the value would come back as a raw `str`: the promised type
    would be a lie. The `default=` is a **member**, not a string (`default="active"` doesn't compile).

## Column name different from the attribute's

```python
created: SnakeColumn[SnakeUtc] = snake_datetimetz(name="created_at")
```

The attribute is `created`; the column is `created_at`. Useful above all with
[DB-first](../engines/db-first.md), where the SQL name already exists.

## Comments

```python
email: SnakeColumn[str] = snake_str(db_comment="Login key; unique")
```

It emits `COMMENT ON COLUMN`, enters the diff and travels in the migrations. There's also
`SnakeComment = "..."` at the class level for the table.

---

Next: [relationships](relationships.md).
