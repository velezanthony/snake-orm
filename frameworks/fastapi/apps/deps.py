"""Dependencies shared by the API routers of the ten domains (accounts, auth, billing...).

The session is an `AsyncSession`, and that is the whole point of this demo rather than a detail of
it. FastAPI is an ASGI framework: an `async def` endpoint runs ON the event loop, so a blocking
driver call there does not slow its own request down — it stops every OTHER request sharing that
loop. These endpoints were already `async def` while the session underneath them was synchronous,
which is the worst of the two arrangements: the shape of an asynchronous server with the behaviour
of a blocking one, and nothing anywhere saying so.

The connection comes from a POOL created once at startup (`main.py`'s lifespan) rather than being
opened per request. In async that matters more than in sync, not less: a hundred concurrent tasks
without a pool are a hundred connections, and a Postgres connection costs the server memory even
while it sits idle. `session.close()` is what gives the connection back — the pool hands out a
wrapper whose `close` returns it to the queue — so the `finally` below is both the release and the
tidy-up, exactly as it reads.

It does NOT commit: the use case is the transaction and it closes its own. What this does is roll
back when the endpoint raises, so a half-written operation never survives an exception.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from snakeorm import AsyncSession, SnakeSession

from shared.config import async_session_over, make_session
from shared.usecases.result import FAILURE_STATUS, Failure


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One asynchronous session per request, over a pooled connection, with the SQL captured."""
    session = async_session_over(await request.app.state.snake_pool.acquire())
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_sync_session() -> Iterator[SnakeSession]:
    """One SYNCHRONOUS session per request, for the ONE router that cannot use the other.

    The lab is a developer's page: it renders `shared/usecases/lab_usecases.py`, which is built on
    `shared/selectors/catalog.py` — fifteen showcase reads that exist to demonstrate the ORM's read
    surface, not to serve this demo's API. An asynchronous twin of the catalogue would be fifteen
    more functions to keep in step with fifteen that already have no second caller, which is the
    duplication the `shared/aio/` seam was designed to avoid rather than to spread.

    So the lab stays synchronous, ON PURPOSE and said out loud, instead of being dropped from the
    demo to make a claim tidy. It blocks the event loop while it runs, and that is the honest cost
    of the choice: the page fires one COUNT per table and is the slowest thing here. If it ever
    stops being a developer's corner, the catalogue is what has to move first.
    """
    session = make_session("fastapi")
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SyncSessionDep = Annotated[SnakeSession, Depends(get_sync_session)]


def http_error(failure: Failure) -> HTTPException:
    """Map a use case `Failure` to the `HTTPException` with its status (the `reason` doubles as detail)."""
    return HTTPException(
        status_code=FAILURE_STATUS[failure.reason], detail=failure.reason
    )
