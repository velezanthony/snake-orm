# SnakeORM · FastAPI demo (JSON API only)

A **JSON API only** demo app (no SSR at all) on top of **SnakeORM**, built on the shared domain of
`frameworks/shared/`: ten domains and 29 tables. It is the **ASYNCHRONOUS** demo of the three, and
that is not an implementation detail: it is what it is here to demonstrate.

## Why this demo exists

FastAPI **is** ASGI: an `async def` endpoint runs ON the event loop, so a blocking call in there does
not slow down its own request — it slows down every other one sharing the loop. This demo spent a
long time with `async def` endpoints and a SYNCHRONOUS session underneath, which is the worst of the
two arrangements: the shape of an asynchronous server with the behaviour of one that blocks, and
nothing anywhere saying so.

Today the session is an **`AsyncSession`** over a **pool** created once in the `lifespan`. In async
the pool matters MORE than in sync, not less: a hundred concurrent tasks with no pool are a hundred
connections, and a Postgres connection costs the server memory even while it sits idle.

## The seam: an asynchronous twin, not a second domain layer

The asynchronous use cases live in **`frameworks/shared/aio/`**, one per domain, twins of
`frameworks/shared/usecases/`. What is NOT duplicated is the SQL: every read is a **colourless
`SnakeQuery` fragment** in `frameworks/shared/selectors/`, and both colours execute the same object.
Generating SQL does not execute anything, so there is nothing that can drift.

What does stay duplicated is a use case's CONTROL FLOW —the two or three lines that validate, decide
and commit—, because `await` is syntax and Python will not let one body serve both colours. **That is
exactly what two nets watch**:

- `shared/tests/test_async_mirror.py` — each twin covers every use case of its domain. A
  half-mirrored domain is a demo that answers fewer questions than the other two without saying so.
- `shared/tests/test_sync_async_parity.py` — the same question to both sessions gives the same
  answer, the same SQL **and the same message the ORM emits about that SQL**. The third one is not
  zeal: the two sessions have already drifted once —the same complaint explained in two wordings—
  and the test that only looked at the SQL let it through for months.

### One router is still synchronous, and it is written down

The **lab** uses `SyncSessionDep` in `apps/deps.py`. It is a developer page built on
`shared/selectors/catalog.py`: fifteen shop-window reads that exist to show off the ORM's read
surface, not to serve this API. An asynchronous twin of the catalogue would be fifteen more functions
to maintain in parallel with fifteen that have no second caller — precisely the duplication that
`shared/aio/` exists to avoid, not to extend.

It blocks the loop while it runs, and that is the honest cost of the decision. What was NOT done was
removing the router from the demo so the figure would come out clean.

## Structure

```
frameworks/fastapi/
├── main.py                 # la app: lifespan (pool + migraciones + siembra), routers, debug
├── apps/deps.py            # la sesión por request: AsyncSession, y SyncSessionDep para el lab
├── apps/<dominio>/         # urls.py (router) + re-exports de shared/ o de shared/aio/
├── apps/<dominio>/migrations/
└── tests/
```

`frameworks/` is added to `sys.path` in order to import `shared`.

## Database

**The `.env` lives at the ROOT of the repository**, one single file for the ORM and the three demos.
`DB_BACKEND` picks `sqlite` / `postgres` / `mysql`; `FASTAPI_DB_NAME` gives this demo its own
database, which is created for you.

**The schema is built by the per-domain MIGRATIONS**, not by an `init_schema`. On boot, the `lifespan`
does `config.drop_all("fastapi")`, applies `apps/*/migrations` in order and seeds at the `DEMO_SCALE`
scale (`normal` by default). That the migrations and the models say the same thing is watched by
`shared/tests/test_migration_drift.py`, across all three demos at once.

> **The seeding runs on the SYNCHRONOUS session, on purpose.** Booting is not serving: there is
> nothing competing for the loop yet, and the seeder is the same domain code the other two demos run.
> Making it asynchronous would be a second seeder to maintain in parallel, for nothing.

## Routes

Eleven routers under `/api/`: `accounts`, `auth`, `billing`, `blog`, `content`, `engagement`,
`inventory`, `logistics`, `orders`, `taxonomy` and `lab`. That is the ten domains plus the `lab`, and
the count comes out of `main.py` —out of the `include_router` calls— and not out of anybody's memory:
the line used to say nine, and `orders` had been mounted for a while. The OpenAPI schema is at
`/openapi.json` and the interactive documentation at `/docs`.

The blog adds **signed-cookie authentication** (Starlette's `SessionMiddleware`, the secret in
`DEMO_SECRET_KEY`) and a CRUD where each user manages only their own posts: with no session, 401.

The seeded users are `demo1`, `demo2`, ... and **they all share the password `test1234`**.

## How to run it

```bash
cd frameworks/fastapi
uv run uvicorn main:app --reload --port 8001   # http://127.0.0.1:8001 · docs en /docs
uv run pytest                      # verificación con TestClient, sin servidor
```

## ORM debug

The middleware plugs in with one line (API only, so no `ssr` channel):

```python
os.environ.setdefault("SNAKE_ORM_DEBUG", "envelope,timing,sidecar")  # antes de crear la app
app.add_middleware(SnakeDebugASGI, production=False)
```

- **`envelope`** — with the channel on, every JSON response carries a `snakeorm` block with the
  summary and each query, with no query param and no header. To an object it is added as a sibling
  key; an array gets wrapped under `{data, snakeorm}`.
- **`timing`** — W3C `Server-Timing` header on every response, a 401 included.
- **`sidecar`** — every response carries an `X-Debug-Token`; the HTML panel is served at
  `/__snake__/{token}`.

Under `production=True` the channels that expose SQL fall away by themselves.

## What the suites verify

- `tests/test_demo.py` — the blog's full flow: register → login → create → list → edit → delete →
  logout, with the CRUD closed (401) before login and after logout; the `password_hash` never leaks;
  the `include` does not fire an N+1 (`assert_queries(1)`); and the three debug channels.
- `tests/test_inventory.py` — the composite-key domain, over HTTP.
- `tests/test_every_router_answers.py` — **it walks the 36 GET routes the app declares in its own
  OpenAPI and demands that none of them answer 5xx.**

That last one exists because of a measured failure. When the demo moved to `AsyncSession`, four
domains were still calling their synchronous use cases, so `session.all(...)` handed them back a
coroutine and the endpoint died:

```
TypeError: 'coroutine' object is not iterable       /api/content/posts/1/revisions
RuntimeWarning: coroutine 'AsyncSession.all' was never awaited
```

And the suite said **18 passed** the whole time, because those eighteen tests did not touch those
domains. A count that comes out full over a trimmed universe is the exact shape of failure this
repository writes nets against, and there it was again, one floor up. The net asks OpenAPI itself for
the routes instead of reading a list, because a list is something you have to remember to extend —
and whoever forgets is precisely the person the check was written for.

## What it demonstrates

- SnakeORM's metadata graph is **agnostic of the engine and of the framework**: the SAME models from
  `shared/` run here by changing only Driver + Dialect.
- **The async seam is colourless**: the same `SnakeQuery` fragment serves both sessions, and the
  parity is checked on the response, on the SQL and on the message.
- **N+1 impossible by default**: with no `include`, touching `post.author` raises
  `SnakeRelationshipNotLoaded` instead of going to the database behind your back.
- The debug tool integrates without coupling the core to the framework: `snakeorm.debug` is the
  kernel and `snakeorm.contrib.asgi` the adapter.
