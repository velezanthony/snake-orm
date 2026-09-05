from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from fastapi import FastAPI  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

# ▶ SnakeORM: the ROOT config (SnakeOrmConfig) + its connection + the debug panel (ASGI)
from snakeorm.contrib import (  # noqa: E402
    SnakeDebugASGI,
    SnakeDebugLanguage,
    SnakeOrmConfig,
)

from apps.accounts.urls import router as accounts_router  # noqa: E402
from apps.auth.urls import router as auth_router  # noqa: E402
from apps.billing.urls import router as billing_router  # noqa: E402
from apps.blog.urls import router as blog_router  # noqa: E402
from apps.content.urls import router as content_router  # noqa: E402
from apps.engagement.urls import router as engagement_router  # noqa: E402
from apps.lab.urls import router as lab_router  # noqa: E402
from apps.logistics.urls import router as logistics_router  # noqa: E402
from apps.orders.urls import router as orders_router  # noqa: E402
from apps.inventory.urls import router as inventory_router  # noqa: E402
from apps.taxonomy.urls import router as taxonomy_router  # noqa: E402
from shared import config  # noqa: E402
from shared.data import demo_scale  # noqa: E402
from shared.data import seed as seed_data  # noqa: E402

_SECRET_KEY = os.environ.get("DEMO_SECRET_KEY", "snakeorm-demo-secret-change-me")
_FRAMEWORK = "fastapi"

# ▶ SnakeORM: the connection comes from the shared config, which knows all THREE engines. This used
#   to be a two-branch `if` copy-pasted into every demo, and `DB_BACKEND=mysql` fell into the `else`:
#   the app talked to MySQL while the migrations were applied to a SQLite file.
_CONNECTION = config.connection_config(_FRAMEWORK)

# ▶ SnakeORM: THE root config — connections (databases) + panel (debug, advise_ms, language) in ONE
#    object. Copy this into your app: it is everything SnakeORM needs, together and typed.
SNAKE = SnakeOrmConfig(
    databases={"default": _CONNECTION},
    # The `envelope` channel = debug ships in the JSON of every response (no `?_debug=1`, no separate flag).
    debug=os.environ.get("SNAKE_ORM_DEBUG", "envelope,timing,sidecar"),
    advise_ms=float(os.environ.get("SNAKE_ORM_ADVISE_MS", 10)),
    language=SnakeDebugLanguage.coerce(os.environ.get("SNAKE_ORM_LANG")),
    # ▶ SnakeORM: WHERE this runs. The channels above hand the SQL to whoever asks, so this is
    #   not optional: without it the middleware refuses to start instead of guessing. A real
    #   deployment reads it from its own environment; a demo says so out loud.
    production=os.environ.get("SNAKE_ORM_PRODUCTION", "false").lower()
    in {"1", "true", "yes", "on"},
)


def _seed() -> None:
    # ▶ SnakeORM: the schema is built by the per-domain MIGRATIONS (not init_schema). drop_all resets
    #   it (deterministic reseed), SNAKE.migrate() applies apps/*/migrations in order, then we seed.
    config.drop_all(_FRAMEWORK)
    SNAKE.migrate()
    session = config.make_session(_FRAMEWORK)
    try:
        seed_data(session, demo_scale())
    finally:
        session.close()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    # ▶ SnakeORM: the seed runs on the SYNCHRONOUS session, and on purpose. Booting is not serving:
    #   nothing is competing for the loop yet, and the seeder is the domain code the other two demos
    #   run too. Making it async would be a second seeder to keep in step for no gain at all.
    _seed()
    # ▶ SnakeORM: the pool of ASYNC connections the requests borrow from, opened once for the whole
    #   process and closed when it stops. Per request it would be a connection per request, which is
    #   precisely what a server must not do.
    pool = config.make_async_pool(_FRAMEWORK)
    application.state.snake_pool = pool
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="SnakeORM · FastAPI demo", lifespan=lifespan)
app.state.snakeorm = (
    SNAKE  # ▶ SnakeORM: the dependency opens it through request.app.state
)

app.add_middleware(SessionMiddleware, secret_key=_SECRET_KEY)

# ▶ SnakeORM: the panel, with channels/threshold that COME FROM the root config itself.
#
# ORDER MATTERS for the `otel` channel: Starlette builds the stack INWARDS, so the LAST
# `add_middleware` is the OUTERMOST one — the same reading as Flask, the opposite of Django's list.
# An OpenTelemetry middleware therefore goes AFTER this call, wrapping ours: our spans hang off the
# application's only while its server span is still open. Backwards it does not fail, it just emits
# detached traces. Verified over the real FastAPI in
# `src/test/contrib/test_otel_middleware_order.py`.
app.add_middleware(
    SnakeDebugASGI,
    channels=SNAKE.channels(),
    config=SNAKE.debug_config(),
    production=False,
)
# app.add_middleware(OpenTelemetryMiddleware)   # ← OTel goes HERE, wrapping ours


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "auth": {
            "register": "POST /api/auth/register",
            "login": "POST /api/auth/login",
            "logout": "POST /api/auth/logout",
        },
        "posts": {
            "list": "GET /api/posts",
            "detail": "GET /api/posts/{id}",
            "stats": "GET /api/posts/stats",
            "create": "POST /api/posts",
            "update": "PATCH /api/posts/{id}",
            "delete": "DELETE /api/posts/{id}",
        },
        # ▶ The six domains exposed over the JSON API (reads + writes through use cases).
        "domains": {
            "accounts": "GET|POST /api/accounts/roles · /api/accounts/users/{id}/roles",
            "auth": "GET|POST /api/auth/users/{id}/tokens · GET /api/auth/users/{id}/sessions",
            "billing": "GET /api/billing/plans · POST /api/billing/subscriptions · /api/billing/invoices/{id}/pay",
            "content": "GET|POST /api/content/posts/{id}/revisions · /api/content/posts/{id}/attachments",
            "engagement": "GET|POST /api/engagement/posts/{id}/comments · /reactions · /visits",
            "taxonomy": "GET /api/taxonomy/tags · POST /api/taxonomy/posts/{id}/tags",
            "logistics": "GET /api/logistics/depots · /api/logistics/dispatch · /api/logistics/load · GET|PATCH /api/logistics/deliveries/{id}",
        },
        "lab": "GET /api/lab · /api/lab/aggregates · /api/lab/subqueries · /api/lab/joins · /api/lab/pagination · /api/lab/problems",
        "debug_hint": "the envelope channel adds a snakeorm block to every JSON response; panel at /__snake__/{token}",
    }


app.include_router(accounts_router)
app.include_router(inventory_router)
app.include_router(logistics_router)
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(blog_router)
app.include_router(content_router)
app.include_router(engagement_router)
app.include_router(orders_router)
app.include_router(lab_router)
app.include_router(taxonomy_router)
