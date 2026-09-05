"""JSON API of the blog with flask-smorest: NATIVE OpenAPI + Swagger UI, over the same use cases.

Two blocks live together under `/api`:

  1. The demo's READ API (the historical one): `/api/posts` (all of them, with a `{posts: [...]}`
     envelope so the debug tooling can inject `snakeorm`), `/api/posts/<id>` and `/api/posts/stats`.
  2. The MIRROR of FastAPI's blog API: auth (register/login/logout) and post CRUD GATED on
     `session['user_id']`, reusing `shared.usecases.blog_usecases` + `shared.dto.blog_dto`.

The views stay thin: they call the use case with FLAT parameters and translate the result (data ->
DTO/serialization; `Failure` -> `abort(status)`). No logic and no `commit` here. The ORM session is
hung on `g.session` by the app-wide hook in `urls.py`, so this blueprint -smorest or not- receives
it just the same. Login stores `user_id` in the signed cookie; logout clears it.

Swagger UI at `/api/docs`, spec at `/api/openapi.json` (mounted by smorest's `Api` in `app.py`).
"""

from __future__ import annotations

from typing import NoReturn

from flask import g, request, session
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint, abort


from apps import wire
from apps.blog import usecases
from apps.blog.schemas import PostSchema, PostsResponse, UserStatsResponse
from shared.dto.blog_dto import (
    PostWithAuthorDto,
    post_dict,
    post_with_author_dict,
    user_dict,
)

blp = Blueprint(
    "blog-api",
    __name__,
    url_prefix="/api",
    description="Blog: auth, post CRUD and statistics",
)

# Translation of a `Failure` (a framework-agnostic reason) into the HTTP code it deserves.
# Same map FastAPI's blog uses (`_FAILURE_STATUS`): semantic parity across the frameworks.
_FAILURE_STATUS: dict[str, int] = {
    "missing_fields": 400,
    "taken": 409,
    "bad_credentials": 401,
    "not_found": 404,
    "forbidden": 403,
}


def _fail(failure: usecases.Failure) -> NoReturn:
    """Abort with the HTTP status of the `reason` (the reason itself doubles as the message).

    `NoReturn` and not `None`, and the difference is five errors long. `abort()` never returns, but a
    helper annotated `-> None` promises the opposite, so after `if isinstance(result, Failure): _fail(result)`
    the checker still believed `result` could be a `Failure` on the next line — and `post_dict(result)`
    was reported against a union that cannot reach it. The runtime was always right; the annotation
    was lying about it.
    """
    abort(_FAILURE_STATUS[failure.reason], message=failure.reason)


def _require_user_id() -> int:
    """The `user_id` from the session cookie; 401 if there is no session (the CRUD gate)."""
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        abort(401, message="authentication required")
    # `abort()` already raised; the assert re-narrows `user_id` to `int` for the type-checker (no `Any`).
    assert isinstance(user_id, int)
    return user_id


# --- The demo's READ API (with an envelope for the debug panel) ----------------------------------


@blp.route("/posts")
@blp.response(200, PostsResponse)
def list_posts() -> dict[str, object]:
    """List EVERY post with its author loaded (include -> 1 JOIN, no N+1)."""
    return {"posts": usecases.list_posts(g.session)}


@blp.route("/posts/<int:post_id>")
@blp.response(200, PostSchema)
def get_post(post_id: int) -> PostWithAuthorDto:
    """One post by id, FLAT. 404 if it does not exist.

    Flat and not `{"post": {...}}`, which is what this route used to answer while Django and FastAPI
    answered the post itself — so the shape of the blog's detail depended on WHICH DEMO you asked,
    on an endpoint the three exist to mirror.

    The flat one is the correct one, and `django/apps/blog/serializers.py` is where the rule is
    written: the envelope exists so the `envelope` channel can inject `snakeorm` INSIDE an object,
    and a post already IS an object — the block rides alongside its keys. The LISTING next door
    keeps its `{"posts": [...]}` because that one really is an array, and an array has nothing to
    hang the block off.
    """
    post = usecases.show_post(g.session, post_id)
    if isinstance(post, usecases.Failure):
        # In English, like every other message this code emits: it is what a caller reads.
        abort(404, message="post not found")
    return post_with_author_dict(post, post.author)


@blp.route("/posts/stats")
@blp.response(200, UserStatsResponse)
def post_stats() -> dict[str, object]:
    """Post count per user (annotate -> a typed aggregate)."""
    return {"users": usecases.user_stats(g.session)}


# --- Auth: register / login / logout (a mirror of FastAPI's blog) --------------------------------


@blp.route("/auth/register", methods=["POST"])
def register() -> ResponseReturnValue:
    """Create a new user (hashed password). 400 if fields are missing, 409 if the username is taken."""
    payload = wire.json_object(request)
    result = usecases.register(
        g.session,
        wire.text(payload.get("username")).strip(),
        wire.text(payload.get("email")).strip(),
        wire.text(payload.get("password")),
    )
    if isinstance(result, usecases.Failure):
        _fail(result)
    return user_dict(result), 201


@blp.route("/auth/login", methods=["POST"])
def login() -> ResponseReturnValue:
    """Verify the credentials and store `user_id` in the session cookie. 401 if they fail."""
    payload = wire.json_object(request)
    result = usecases.login(
        g.session,
        wire.text(payload.get("username")).strip(),
        wire.text(payload.get("password")),
    )
    if isinstance(result, usecases.Failure):
        _fail(result)
    session["user_id"] = result.id
    return user_dict(result)


@blp.route("/auth/me", methods=["GET"])
def me() -> ResponseReturnValue:
    """Who the session cookie says you are. 401 with no session, the user with one.

    THE ONE ROUTE AN SSR DEMO NEVER NEEDS AND A CLIENT-ROUTED ONE CANNOT WORK WITHOUT. A server that
    renders the page already knows who asked, so the answer arrives inside the HTML; a client that
    reloads on a route of its own has nothing but a cookie it is not allowed to read — `HttpOnly` is
    the whole point of the cookie — so asking is the only honest way to find out. The dishonest way
    is a copy of the user kept in `localStorage`, which survives the logout that made it wrong.

    IT READS `g.current_user` AND DOES NOT ASK AGAIN, which is the one thing that makes this route
    different from Django's and FastAPI's. `_open_session` is a `before_app_request`, so it runs for
    EVERY request this app serves — the JSON ones included — and its docstring already promises to
    "resolve the logged-in user exactly once". Asking a second time here broke that promise, and the
    ORM's own debug panel is what said so: two identical `SELECT ... FROM users WHERE id = %s`, and
    a `1 duplicates` on a page whose whole job is one lookup.

    A cookie that is signed, valid and names a row that is GONE resolves to `None`, and 401 is the
    honest reading of that — not a 200 with a shape invented to fill it.
    """
    user = g.get("current_user")
    if user is None:
        abort(401, message="authentication required")
    return user_dict(user)


@blp.route("/auth/logout", methods=["POST"])
def logout() -> ResponseReturnValue:
    """Clear the session (logout)."""
    session.clear()
    return {"logged_out": True}


# --- GATED post CRUD (ALWAYS the session user's own) ----------------------------------------------


@blp.route("/posts", methods=["POST"])
def create_post() -> ResponseReturnValue:
    """Create a post for the session user (the id arrives in the RETURNING). 400 if the title is missing."""
    user_id = _require_user_id()
    payload = wire.json_object(request)
    result = usecases.create_post(
        g.session,
        user_id,
        title=wire.text(payload.get("title")).strip(),
        body=wire.text(payload.get("body")).strip(),
        published=wire.flag(payload.get("published")),
    )
    if isinstance(result, usecases.Failure):
        _fail(result)
    return post_dict(result), 201


@blp.route("/posts/<int:post_id>", methods=["PATCH"])
def update_post(post_id: int) -> ResponseReturnValue:
    """Update one of your own posts (the use case validates ownership). 403 if it is not yours."""
    user_id = _require_user_id()
    payload = wire.json_object(request)
    result = usecases.edit_post(
        g.session,
        post_id,
        user_id,
        title=wire.optional_text(payload.get("title")),
        body=wire.optional_text(payload.get("body")),
        published=wire.optional_flag(payload.get("published")),
    )
    if isinstance(result, usecases.Failure):
        _fail(result)
    return post_dict(result)


@blp.route("/posts/<int:post_id>", methods=["DELETE"])
def delete_post(post_id: int) -> ResponseReturnValue:
    """Delete one of your own posts (the use case validates ownership). 403 if it is missing or not yours."""
    user_id = _require_user_id()
    result = usecases.remove_post(g.session, post_id, user_id)
    if isinstance(result, usecases.Failure):
        _fail(result)
    return {"deleted": post_id}
