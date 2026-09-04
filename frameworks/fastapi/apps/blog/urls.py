"""Blog domain router: auth (register/login/logout) and post CRUD, JSON API ONLY.

THIN endpoints: no inline queries and no business rules. Each endpoint (1) parses the request
(Pydantic), (2) `await`s a USE CASE from `apps.blog.usecases` with FLAT parameters — never the
`Request` — and (3) translates the result to JSON: a value gets serialised, a `Failure` maps to its
`HTTPException`. All the domain logic (validating, orchestrating, committing) lives in
`shared/usecases`/`shared/aio`.

The session is `AsyncSession`, over a connection borrowed from the pool, and that is the whole point
of this router rather than a detail of it. FastAPI is an ASGI framework: an `async def` endpoint runs
ON the event loop, so a blocking driver call there does not slow its own request down — it stalls
every OTHER request sharing that loop. This is also the domain that carries its own login (the
`user_id` session cookie), which is exactly why it keeps its OWN `get_session` here instead of
importing `apps.deps.SessionDep`: the dependency wiring is identical to the other domains', but the
cookie-gated `current_user_id`/`UserIdDep` below belong to the blog, not to the shared plumbing.

The connection comes from the POOL created once at startup (`main.py`'s lifespan), the same way
`apps/deps.py` acquires one: a connection per request is what a pooled server must not do, and that
cost does not go away just because this router keeps its own copy of the dependency.

The `commit` is done by the use case itself (the operation is atomic and closes inside): the
dependency does not commit, it only rolls back if the endpoint raises and closes the session (which
returns the connection to the pool) at the end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from snakeorm import AsyncSession

from apps.blog import usecases
from apps.blog.usecases import Failure
from shared.config import async_session_over
from shared.dto.blog_dto import (
    PostDto,
    PostWithAuthorDto,
    UserDto,
    post_dict,
    post_with_author_dict,
    user_dict,
)

# Translation of a `Failure` (a framework-agnostic reason) into the HTTP code that fits it.
_FAILURE_STATUS: dict[str, int] = {
    "missing_fields": 400,
    "taken": 409,
    "bad_credentials": 401,
    "not_found": 404,
    "forbidden": 403,
}


def _http_error(failure: Failure) -> HTTPException:
    """Maps a use case `Failure` to the `HTTPException` with its status (the `reason` becomes detail)."""
    return HTTPException(
        status_code=_FAILURE_STATUS[failure.reason], detail=failure.reason
    )


# --- Input schemas (request validation) ------------------------------------------------------------


class RegisterIn(BaseModel):
    """Registration body: username, email and plaintext password (hashed on save)."""

    username: str
    email: str
    password: str


class LoginIn(BaseModel):
    """Login body: username and password."""

    username: str
    password: str


class PostIn(BaseModel):
    """Body for creating a post (the author comes from the session, not from the body)."""

    title: str
    body: str
    published: bool = False


class PostUpdate(BaseModel):
    """Body for updating a post (everything optional)."""

    title: str | None = None
    body: str | None = None
    published: bool | None = None


# --- Serialisation (model -> JSON dict) --------------------------------------------------------
# User and post serialisation lives in `shared.dto.blog_dto` (SHARED by all three frameworks): that
# way the blog serialises IDENTICALLY on Flask, FastAPI and Django. Here it is only imported.


# --- Dependencies (the framework glue) -----------------------------------------------------------


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One asynchronous session per request, over a pooled connection, with the SQL captured.

    Borrows the connection from `app.state.snake_pool` the same way `apps/deps.py` does — this router
    keeps its own copy of the dependency instead of importing `SessionDep` because it also owns the
    cookie-gated `current_user_id`/`UserIdDep` below, and the two belong together. It does NOT commit
    — the use case already does; if the endpoint raises it rolls back and re-raises. It always closes
    the session (returning the connection to the pool) at the end.
    """
    session = async_session_over(await request.app.state.snake_pool.acquire())
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def current_user_id(request: Request) -> int:
    """The user id in the session cookie; 401 if there is no session (the CRUD gate)."""
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="authentication required")
    return user_id


UserIdDep = Annotated[int, Depends(current_user_id)]


# The `/api` prefix puts the WHOLE blog under the BFF's JSON tree: the login session coexists with
# the `auth` domain (tokens) without collision, because the sub-paths differ.
router = APIRouter(prefix="/api")


# --- Auth: register / login / logout -------------------------------------------------------------


@router.post("/auth/register", status_code=201)
async def register(payload: RegisterIn, session: SessionDep) -> UserDto:
    """Creates a new user (password hashed). 400 if fields are missing, 409 if the username exists."""
    result = await usecases.register(
        session, payload.username, payload.email, payload.password
    )
    if isinstance(result, Failure):
        raise _http_error(result)
    return user_dict(result)


@router.post("/auth/login")
async def login(payload: LoginIn, request: Request, session: SessionDep) -> UserDto:
    """Checks the credentials and stores `user_id` in the session cookie. 401 if they fail."""
    result = await usecases.login(session, payload.username, payload.password)
    if isinstance(result, Failure):
        raise _http_error(result)
    request.session["user_id"] = result.id
    return user_dict(result)


@router.get("/auth/me")
async def me(request: Request, session: SessionDep) -> UserDto:
    """Who the session cookie says you are. 401 with no session, the user with one.

    THE ONE ROUTE AN SSR DEMO NEVER NEEDS AND A CLIENT-ROUTED ONE CANNOT WORK WITHOUT. A server that
    renders the page already knows who asked, so the answer arrives inside the HTML; a client that
    reloads on a route of its own has nothing but a cookie it is not allowed to read — `HttpOnly` is
    the whole point of the cookie — so asking is the only honest way to find out. The dishonest way
    is a copy of the user kept in `localStorage`, which survives the logout that made it wrong.

    It depends on `current_user_id`, the same gate the CRUD writes use, so there is one answer to
    "is there a session". A cookie that is signed, valid and names a row that is GONE gets a 401
    rather than a 200 with a shape invented to fill it.
    """
    user_id = current_user_id(request)
    user = await usecases.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user_dict(user)


@router.post("/auth/logout")
async def logout(request: Request) -> dict[str, object]:
    """Clears the session (logout)."""
    request.session.clear()
    return {"logged_out": True}


# --- Posts: READS are public, WRITES are gated to the author -------------------------------------


@router.get("/posts")
async def list_posts(session: SessionDep) -> dict[str, object]:
    """The showcase: ALL posts with their author loaded (to-one -> JOIN, NO N+1). Public.

    `{"posts": [...]}` and not a bare list, which is the rule the other two demos already follow and
    the one this route was breaking. Django's `serializers.py` states it: "The API returns JSON
    OBJECTS, not top-level arrays: the ORM's debug envelope is injected INSIDE an object."

    Answering an array does not opt out of that — it hands the debug middleware something it cannot
    hang `snakeorm` off, so the middleware wraps it in `{"data": [...]}` on the way out. The result
    was a listing whose envelope key depended on WHICH DEMO answered, on the one endpoint all three
    are supposed to mirror, while `/posts/stats` next door already used `{"users": [...]}`. A client
    that can switch backends is what found it: it read `.posts`, got `undefined`, and fell over.
    """
    posts = await usecases.list_posts(session)
    return {"posts": [post_with_author_dict(p, p.author) for p in posts]}


@router.get("/posts/stats")
async def posts_stats(session: SessionDep) -> dict[str, object]:
    """Post count per user (the showcase's typed aggregate: `annotate` -> `UserStats`). Public.

    Declared BEFORE `/posts/{post_id}`: FastAPI matches routes in order, so the literal `stats` is not
    swallowed by the dynamic parameter.
    """
    stats = await usecases.user_stats(session)
    users = [
        {"id": row.user.id, "username": row.user.username, "post_count": row.post_count}
        for row in stats
    ]
    return {"users": users}


@router.get("/posts/{post_id}")
async def get_post(post_id: int, session: SessionDep) -> PostWithAuthorDto:
    """One post by id (with its author loaded). Public. 404 if it does not exist."""
    result = await usecases.show_post(session, post_id)
    if isinstance(result, Failure):
        raise HTTPException(status_code=404, detail="post not found")
    return post_with_author_dict(result, result.author)


@router.post("/posts", status_code=201)
async def create_post(
    payload: PostIn, session: SessionDep, user_id: UserIdDep
) -> PostDto:
    """Creates a post for the session's user (the id arrives in the RETURNING). 400 if the title is missing."""
    result = await usecases.create_post(
        session,
        user_id,
        title=payload.title,
        body=payload.body,
        published=payload.published,
    )
    if isinstance(result, Failure):
        raise _http_error(result)
    return post_dict(result)


@router.patch("/posts/{post_id}")
async def update_post(
    post_id: int, payload: PostUpdate, session: SessionDep, user_id: UserIdDep
) -> PostDto:
    """Updates one of your own posts (ownership is validated by the use case). 403 if it is not yours."""
    result = await usecases.edit_post(
        session,
        post_id,
        user_id,
        title=payload.title,
        body=payload.body,
        published=payload.published,
    )
    if isinstance(result, Failure):
        raise _http_error(result)
    return post_dict(result)


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int, session: SessionDep, user_id: UserIdDep
) -> dict[str, object]:
    """Deletes one of your own posts (ownership validated by the use case). 403 if missing or not yours."""
    result = await usecases.remove_post(session, post_id, user_id)
    if isinstance(result, Failure):
        raise _http_error(result)
    return {"deleted": post_id}
