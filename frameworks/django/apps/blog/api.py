"""JSON API of the blog with Django REST Framework + drf-spectacular: NATIVE OpenAPI/Swagger.

THIN views (`@api_view`): they call the use case (`apps.blog.usecases`) with the ORM session and
serialize with DRF; drf-spectacular generates the OpenAPI out of the serializers (`@extend_schema`).
No logic and no `commit` here. The SnakeORM session is hung on `request.snake_session` by
`SnakeSessionMiddleware` (DRF wraps the request, but delegates the attribute to the Django request).

CANONICAL surface (BFF), MIRROR of FastAPI/Flask, ALL of it under `/api/` and per resource:
  - `GET  /api/posts/`        EVERY post with its author (public) — the "showcase".
  - `POST /api/posts/`        creates a post (gated: a session is required).
  - `GET  /api/posts/stats/`  number of posts per user (typed aggregate).
  - `GET  /api/posts/<id>/`   one post with its author (public). 404 if it does not exist.
  - `PATCH|DELETE /api/posts/<id>/`  edits/deletes an OWN post (gated to the author).
  - `POST /api/auth/register|login|logout/`  session by signed cookie.
  - `GET  /api/auth/me/`      who the cookie says you are (401 with no session). The one route the
                              SSR demos never needed and a client that routes in the browser cannot
                              work without.

Schema at `/api/schema/`, Swagger UI at `/api/docs/` (drf-spectacular mounts them in `urls.py`).
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps import wire
from apps.session import snake_session
from apps.blog import usecases
from apps.blog.guards import current_user
from apps.blog.serializers import (
    PostSerializer,
    PostsResponseSerializer,
    UserStatsResponseSerializer,
    UserStatsSerializer,
)
from shared.dto.blog_dto import post_dict, post_with_author_dict, user_dict

# Translation of a `Failure` (a framework-agnostic reason) into the HTTP code it deserves.
# The same mapping as the canonical FastAPI/Flask API (surface parity).
_FAILURE_STATUS: dict[str, int] = {
    "missing_fields": 400,
    "taken": 409,
    "bad_credentials": 401,
    "not_found": 404,
    "forbidden": 403,
}


_session = snake_session


def _current_user_id(request: Request) -> int | None:
    """The `user_id` from the session cookie (the CRUD gate); `None` if no session was started."""
    user_id = request.session.get("user_id")
    return user_id if isinstance(user_id, int) else None


# --- Auth (session by signed cookie) -------------------------------------------------------------


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def auth_register(request: Request) -> Response:
    """Creates a new user (password hashed). 400 if fields are missing, 409 if the username exists."""
    payload = wire.json_object(request)
    result = usecases.register(
        _session(request),
        wire.text(payload.get("username")),
        wire.text(payload.get("email")),
        wire.text(payload.get("password")),
    )
    if isinstance(result, usecases.Failure):
        return Response(
            {"detail": result.reason}, status=_FAILURE_STATUS[result.reason]
        )
    return Response(user_dict(result), status=201)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def auth_login(request: Request) -> Response:
    """Checks the credentials and stores `user_id` in the session cookie. 401 if they fail."""
    payload = wire.json_object(request)
    result = usecases.login(
        _session(request),
        wire.text(payload.get("username")),
        wire.text(payload.get("password")),
    )
    if isinstance(result, usecases.Failure):
        return Response(
            {"detail": result.reason}, status=_FAILURE_STATUS[result.reason]
        )
    request.session["user_id"] = result.id
    return Response(user_dict(result))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def auth_me(request: Request) -> Response:
    """Who the session cookie says you are. 401 with no session, the user with one.

    THE ONE ROUTE A CLIENT THAT OWNS ITS ROUTING CANNOT DO WITHOUT. The three SSR demos never needed
    it: the server renders the page already knowing who asked, so the answer arrives inside the HTML.
    A client that reloads on a route of its own has nothing but a cookie it is not allowed to read —
    `HttpOnly` is the whole point of the cookie — so asking is the only honest way to find out. The
    dishonest way is a copy of the user kept in `localStorage`, which survives the logout, the
    expiry and the revocation that made it wrong.

    It READS and it does not mint, the same line `apps/auth/views.access` draws: the session is
    already there or it is not, and this route only reports which.

    IT USES THE MECHANISM THIS DEMO ALREADY HAS, which is `guards.current_user` — the same helper
    every page of the app asks this question with. Each of the three demos answers "who is logged
    in" its own way (Django a guard, Flask a `before_app_request` hook, FastAPI a dependency), and
    this route reaching for a second answer would be a second definition of the session's user
    inside a demo that already had one.

    A cookie that is signed, valid and names a row that is GONE resolves to `None`, and 401 is the
    honest reading of that — not a 200 with a shape invented to fill it.
    """
    user = current_user(request)
    if user is None:
        return Response({"detail": "authentication required"}, status=401)
    return Response(user_dict(user))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def auth_logout(request: Request) -> Response:
    """Clears the session (logout)."""
    request.session.flush()
    return Response({"logged_out": True})


# --- Posts (LEER es público; ESCRIBIR va gated al autor) -----------------------------------------


@extend_schema(methods=["GET"], responses=PostsResponseSerializer)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def posts_list(request: Request) -> Response:
    """GET (public): ALL posts with their author (JOIN, no N+1). POST (gated): creates one (401 with no session)."""
    if request.method == "POST":
        user_id = _current_user_id(request)
        if user_id is None:
            return Response({"detail": "authentication required"}, status=401)
        payload = wire.json_object(request)
        result = usecases.create_post(
            _session(request),
            user_id,
            title=wire.text(payload.get("title")),
            body=wire.text(payload.get("body")),
            published=wire.flag(payload.get("published")),
        )
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=_FAILURE_STATUS[result.reason]
            )
        return Response(post_dict(result), status=201)
    posts = usecases.list_posts(_session(request))
    return Response({"posts": PostSerializer(posts, many=True).data})


@extend_schema(responses=UserStatsResponseSerializer)
@api_view(["GET"])
def posts_stats(request: Request) -> Response:
    """Post count per user (the `user_stats` use case: annotate with a scalar subquery)."""
    stats = usecases.user_stats(_session(request))
    return Response({"users": UserStatsSerializer(stats, many=True).data})


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["PATCH"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@extend_schema(methods=["DELETE"], responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH", "DELETE"])
def post_detail(request: Request, post_id: int) -> Response:
    """GET (public): one post with its author. 404 if missing. PATCH/DELETE (gated to the author): 401/403."""
    session = _session(request)

    if request.method == "GET":
        post = usecases.show_post(session, post_id)
        if isinstance(post, usecases.Failure):
            return Response({"detail": "not_found"}, status=404)
        return Response(post_with_author_dict(post, post.author))

    user_id = _current_user_id(request)
    if user_id is None:
        return Response({"detail": "authentication required"}, status=401)

    if request.method == "PATCH":
        patch = wire.json_object(request)
        result = usecases.edit_post(
            session,
            post_id,
            user_id,
            title=wire.optional_text(patch.get("title")),
            body=wire.optional_text(patch.get("body")),
            published=wire.optional_flag(patch.get("published")),
        )
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=_FAILURE_STATUS[result.reason]
            )
        return Response(post_dict(result))

    result = usecases.remove_post(session, post_id, user_id)
    if isinstance(result, usecases.Failure):
        return Response(
            {"detail": result.reason}, status=_FAILURE_STATUS[result.reason]
        )
    return Response({"deleted": post_id})
