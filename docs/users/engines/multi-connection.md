# Multiple databases

```python
from snakeorm import SnakeColumn, SnakeModel, snake_auto, snake_model, snake_session, snake_str

@snake_model(table="events", database="analytics")  # tied to another connection
class Event(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    kind: SnakeColumn[str] = snake_str()

analytics = snake_session("analytics")  # opens the connection by name
```

`database` is **declarative and static**: it is read off the model, not decided at runtime. It
doesn't change a comma of the SQL — and it doesn't route anything either. Nothing in the session or
in the query reads it: a session sends to the connection IT was opened with, so opening one against
`default` and querying `Event` through it emits perfectly valid SQL against the wrong database, with
no error and no warning. What DOES read `database` is `snake_link()`, to refuse a relationship that
crosses connections, and the CLI's `--database`, to pick the tables and the migration history of one
connection. Handing the model to the right session is yours: the ORM has no router, because routing
would mean guessing at runtime what this label already states at import time.

## Declaring the connections

The `default` comes from `DATABASE_URL` / `SNAKEORM_DSN` / the `DB_*` pieces. The rest go by name, in
`SNAKEORM_DSN_<NAME>`:

```bash
DATABASE_URL=postgresql://user:pass@localhost/app
SNAKEORM_DSN_ANALYTICS=postgresql://user:pass@other-host/events
```

!!! note "If a DSN is missing, it says EXACTLY which one"

    ```text
    There is no DSN for connection 'analytics': set the environment variable
    SNAKEORM_DSN_ANALYTICS (or put it in the .env). Connection 'default' is the only
    one resolved from the DB_* pieces.
    ```

    A DSN that resolves blindly ends up connecting to the wrong database — worse than not connecting.

### Each connection carries its own engine

A named connection is not tied to PostgreSQL. The engine is READ, in this order: an explicit
`SNAKEORM_BACKEND_<NAME>` (or `DB_BACKEND` for the default connection), then the DSN's own scheme —
`postgresql://`, `mysql://`, `sqlite://` — because a scheme is a declaration and reading one is not
divination.

```bash
SNAKEORM_DSN_ANALYTICS=postgresql://user:pass@other-host/events   # engine read off the scheme
SNAKEORM_DSN_ARCHIVO=sqlite:////var/data/archivo.db               # SQLite: FOUR slashes = absolute
SNAKEORM_DSN_LEGACY=mysql://user:pass@old-host:3307/ventas        # MySQL, likewise

SNAKEORM_BACKEND_LEGACY=mysql   # only when you want to say it out loud
```

The fourth slash in the SQLite DSN is not a typo. The third one is the URL's separator, so
`sqlite:///var/data/archivo.db` would name the RELATIVE `var/data/archivo.db`, resolved against
whatever directory the process was started in. An absolute path takes four.

A DSN with no scheme at all is PostgreSQL, and that is a derivation rather than a fallback: the
shape `host=x dbname=y` is libpq keyword syntax and no other engine writes one.

!!! danger "A typo in the engine is refused, never rounded to the nearest one"

    ```text
    SNAKEORM_BACKEND_LEGACY='postgress' is not a known engine. The three are:
    postgres, mysql, sqlite. It is refused instead of falling back, because falling
    back means talking to another database without saying so.
    ```

## Opening a session

```python
from snakeorm import snake_session

session   = snake_session()  # "default"
analytics = snake_session("analytics")
```

The factory assembles driver and dialect from the configuration.

## Migrations per connection

```bash
uv run snakeorm makemigrations --database analytics
uv run snakeorm migrate --database analytics
```

Each NAMED connection has its own directory (`migrations/<database>/`) and its own numbering; the
`default` one stays in plain `migrations/`, so a project with a single database never sees the layout
change under it. Without the filter, `makemigrations` would try to create ALL the tables in EVERY
database.

## Relations across databases: no

```python
@snake_model(table="orders")  # default
class Order(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    event_id: SnakeColumn[int] = snake_int()
    event: SnakeToOne[Event] = snake_to_one(event_id)  # Event lives in "analytics"
```

`snake_link()` **fails at startup**, on purpose:

```text
Relationship Order.event crosses databases: Order lives in 'default' and Event in
'analytics'. There is neither a foreign key nor a JOIN possible across connections.
Move one of the two, or store the identifier as a plain column and resolve it
yourself with two queries.
```

Without the guard it would emit a `FOREIGN KEY` against a table that doesn't exist in that database.
If you need to cross the data, do it in the application: two queries and a `dict`.

## A pool that survives a deploy

Handing out connections is the easy part of a pool. The hard part is **what happens when the
connection is rotten and you don't know it**:

```python
from snakeorm import PostgresDialect, SnakeSession, psycopg_pool

pool = psycopg_pool(
    dsn,
    maximum=20,
    pre_ping=True,         # check the pulse before lending
    recycle_seconds=1800,  # drop connections older than 30 min
    timeout_seconds=5,     # wait up to 5 s for one to free up
)

with pool.connection() as driver:
    session = SnakeSession(driver, PostgresDialect())
```

`pool.connection()` is the way in: it hands you the driver and gives it back **always**, also when
the block blows up.

| Knob | The problem it removes |
|---|---|
| `pre_ping` | The database restarts (deploy, failover) and the pool keeps handing out dead connections. Without this the error doesn't surface in the pool: it surfaces in the user's first query. Costs one round trip per checkout. |
| `recycle_seconds` | MySQL's `wait_timeout` closes idle connections on its own and the pool never finds out. Recycling by age doesn't ask: it prevents. |
| `timeout_seconds` | With the pool exhausted, psycopg2 raises `PoolError` **instantly**. A traffic spike blows up even though a connection would have freed up 50 ms later. With a deadline it waits; once spent you get a `SnakePoolTimeout`, which has its own name because it calls for a different action (more pool, less load) than a one-off failure. |

All three are **off by default**: they cost round trips or throw away healthy connections, and that
price is decided by whoever knows the deployment, not by the library.

If three connections in a row come back dead, `acquire()` gives up with `SnakePoolTimeout` instead of
spinning on discard-and-retry: at that point it's the database that's down, not the connection.

### The same pool, async: `AsyncSnakePool`

`AsyncSnakePool` is the mirror, with the same three safeguards and the same discard ceiling. In async
the pool matters MORE, not less: a server with a hundred concurrent tasks opens a hundred connections
if nobody hands them out, and a Postgres connection costs memory on the server even while it sits
idle. With the threaded drivers (MySQL, SQLite) it also costs a thread each.

There's no `psycopg_pool()` twin for it, because the async pool is engine-agnostic: you give it three
coroutines —how to borrow, how to give back, how to close everything— and it puts the rules on top.

```python
import asyncio
from snakeorm import AsyncDriver, AsyncPsycopgDriver, AsyncSession, AsyncSnakePool, PostgresDialect

free: asyncio.Queue[AsyncDriver] = asyncio.Queue()

async def borrow() -> AsyncDriver:
    return free.get_nowait() if not free.empty() else await AsyncPsycopgDriver.connect(dsn)

async def give_back(driver: AsyncDriver) -> None:
    free.put_nowait(driver)

async def close_all() -> None:
    while not free.empty():
        await free.get_nowait().close()

pool = AsyncSnakePool(
    borrow,
    give_back,
    close_all,
    pre_ping=True,
    recycle_seconds=1800,
    timeout_seconds=5,
)

async with pool.connection() as driver:
    session = AsyncSession(driver, PostgresDialect())
```

Two differences from the synchronous sibling, and only two:

- While it waits for a connection to free up it **yields the event loop** (`asyncio.sleep`) instead
  of blocking the thread. That's what keeps one task waiting on a connection from stopping the other
  ninety-nine.
- The borrowed driver's `close()` **returns** the connection instead of closing it, and it's
  idempotent. That second part isn't a detail: a repeated `close()` —the session's plus an outer
  `finally`— would put the SAME connection back in the queue twice, and from then on two tasks would
  each believe they had their own.

---

Next: [DB-first and scaffolding](db-first.md).
