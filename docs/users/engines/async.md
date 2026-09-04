# Async

```bash
uv sync --extra async     # psycopg 3, for PostgreSQL
uv sync --extra mysql     # PyMySQL, for MySQL / MariaDB
# SQLite needs nothing extra: sqlite3 ships with the standard library
```

## The recommended way: let the config assemble it

```python
from snakeorm import SnakeBackend, SnakeConnectionConfig

config = SnakeConnectionConfig(
    backend=SnakeBackend.POSTGRES,
    name="app",
    host="localhost",
    user="app",
    password="secret",
)
session = await config.open_async()
```

`open_async()` is the async twin of `open()`: it picks driver AND dialect **paired** off the
`backend`, so nobody can wire an `AsyncSQLiteDriver` to a `PostgresDialect` — you never choose the
two pieces separately.

If your app has a debug panel, go through `contrib` instead: it's the same call with the driver
wrapped so the panel sees the SQL.

```python
from snakeorm.contrib import open_session_async

session = await open_session_async(config)
```

## Or wire it by hand

```python
from snakeorm import AsyncPsycopgDriver, AsyncSession, PostgresDialect, SnakeQuery

driver = await AsyncPsycopgDriver.connect(dsn)
session = AsyncSession(driver, PostgresDialect())

cars = await session.all(
    SnakeQuery(Car).filter(Car.brand.name == "Seat").include(Car.brand)
)
await session.commit()
```

## Three engines, three async drivers

```python
from snakeorm import AsyncPsycopgDriver, AsyncPyMySQLDriver, AsyncSQLiteDriver

pg     = await AsyncPsycopgDriver.connect(dsn)
mysql  = await AsyncPyMySQLDriver.connect(host="localhost", database="app", user="app")
sqlite = await AsyncSQLiteDriver.connect("./my.db")
```

| Driver | Engine | How it talks | Extra dependency |
|---|---|---|---|
| `AsyncPsycopgDriver` | PostgreSQL | Native asyncio (psycopg 3) | extra `async` |
| `AsyncPyMySQLDriver` | MySQL / MariaDB | Synchronous driver on its own thread | extra `mysql` |
| `AsyncSQLiteDriver` | SQLite | Synchronous driver on its own thread | none |

All three are `AsyncDriver`. The session can't tell them apart, and that's the whole point of the
seam — but you deserve to know which is which, because they don't scale the same.

## Two of the three run on a thread, and you should know it

Only one engine has a native asyncio library among the project's dependencies: psycopg 3. For the
other two, `ThreadedAsyncDriver` wraps a `SnakeDriver` in a `ThreadPoolExecutor(max_workers=1)` and
awaits each call on it.

**It is not fake async.** It's exactly what `aiosqlite` does internally, and for MySQL it gives you
REAL concurrency: Python releases the GIL while the socket waits, so two queries from two different
tasks genuinely overlap.

**And it is not free either.** It doesn't perform like a native protocol under heavy concurrency,
because **every connection occupies an OS thread**. A hundred simultaneous connections is a hundred
threads. That's the number to size against, and it's why the pool matters more here, not less.

!!! info "One thread per connection, not a shared pool"

    A DBAPI connection isn't thread-safe: `sqlite3` checks and refuses outright, and PyMySQL just
    corrupts itself if two threads use it at once. With a single thread per driver the calls
    serialise by construction and the connection always sees the same thread. Serialising costs
    nothing here —a session already awaits each query before firing the next— and whoever wants
    parallelism opens more connections.

    The connection is also **opened inside** that thread, because `sqlite3` binds a connection to its
    creating thread and raises if another one touches it.

The day a native driver exists for one of these engines, it comes in as another implementation of the
same Protocol and nothing upstream changes.

## The models and the queries are the SAME

There's no `AsyncModel` or `AsyncQuery`. `SnakeQuery` doesn't execute —it only emits `(sql, params)`—
so it **has no color** and is reused as-is. The only thing with color is the execution seam, and
that's where `AsyncSession` lives.

## Parity

`AsyncSession` exposes **exactly** the same public methods as `SnakeSession` (same `include`,
`iterate`, `upsert`…). Same names, with `async def` + `await` and `async with`. The behaviour
matches too, down to the corners: `add()` fills the autoincrement PK from `last_insert_id` on an
engine without `RETURNING`, and `add_all()` emits the same warning about generated keys a bulk insert
can't hand back.

## Driver decorators

```python
from snakeorm import AsyncLoggingDriver, AsyncTimeoutDriver, PostgresDialect

driver = AsyncLoggingDriver(driver, write=print)
driver = await AsyncTimeoutDriver.apply_to(driver, PostgresDialect(), statement_timeout_ms=5000)
```

The session has no idea they're there.

`AsyncTimeoutDriver` is applied with `apply_to` and not with the constructor because it has to run a
`SET` on the connection, and you can't await inside `__init__`. The statement comes from the dialect:
Postgres and MySQL each have one; SQLite has no server-side timeout, so `apply_to` refuses with
`SnakeDialectError`.

## Pooling

Async is where a pool earns its keep: a server with a hundred concurrent tasks opens a hundred
connections if nobody hands them out, and with the threaded drivers that's also a hundred threads.
`AsyncSnakePool` is the mirror of `SnakePool`, with the same three safeguards — see
[multiple databases](multi-connection.md).

## Async migrations

```python
from snakeorm import PostgresDialect
from snakeorm.migration import AsyncMigrationRunner, load

runner = AsyncMigrationRunner(driver, PostgresDialect())
applied = await runner.apply(load("migrations"))
```

!!! warning "DATA migrations don't run here"

    `RunPython` receives a **synchronous** `SnakeSession`: its body would block the event loop. The
    async runner **stops and says so**. Apply those migrations with `MigrationRunner` over a
    synchronous driver; schema ones do go here.

## When NOT to use it

If your application is synchronous, async won't make it faster — only harder to debug. It makes sense
when the process spends most of its time waiting on I/O. A batch-load script isn't that case. And on
SQLite it's rarely worth it at all: there's no network to wait on, so the thread hop buys you
nothing but the ability to sit in an `async def`.

---

Next: [multiple databases](multi-connection.md).

!!! info "And the machine checks it"

    A test reads the public methods of `SnakeSession` and `AsyncSession` and compares them. It exists
    because `AsyncSession` once shipped with twelve of twenty-two: two long classes do not get
    compared by eye. The same holds for `AsyncMigrationRunner` against `MigrationRunner`.

