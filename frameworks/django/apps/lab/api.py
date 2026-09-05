"""JSON API of the LAB with DRF: every ORM experiment returned as JSON (for the Swagger).

THIN endpoints (`@api_view(["GET"])`): there are no inline queries nor logic. Each one delegates to a
SHARED use case (`shared.usecases.lab_usecases`), which already returns JSON-able "sections" (title ·
note · columns · rows). The SSR (`apps.lab.views`) and this API consume exactly the same functions:
the Lab is identical in SSR and API without duplicating logic, MIRROR of the FastAPI/Flask router.

The SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`.
`@extend_schema` documents each operation at `/api/docs` (drf-spectacular).
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps.session import snake_session
from apps.lab.views import async_sections_for_api
from shared.usecases import lab_usecases


_session = snake_session


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def index(request: Request) -> Response:
    """Lab index: one COUNT(*) for each of the 20 seeded tables."""
    return Response({"sections": lab_usecases.index_sections(_session(request))})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def aggregates(request: Request) -> Response:
    """Aggregates: typed `annotate` (1 hop) and `GROUP BY`+`SUM` at the SQL level."""
    return Response({"sections": lab_usecases.aggregates_sections(_session(request))})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def subqueries(request: Request) -> Response:
    """Subqueries: EXISTS, NOT EXISTS and IN (over the N—N bridge table)."""
    return Response({"sections": lab_usecases.subqueries_sections(_session(request))})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def joins(request: Request) -> Response:
    """Joins and include: loading relations in ONE single query (no N+1)."""
    return Response({"sections": lab_usecases.joins_sections(_session(request))})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def expressions(request: Request) -> Response:
    """Scalar functions: text, maths, JSON, case-insensitive match, dates and named pairs."""
    return Response({"sections": lab_usecases.expressions_sections(_session(request))})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def asynchronous(request: Request) -> Response:
    """The same reads over an `AsyncSession`, borrowed from the pool.

    A SYNC view around an async body, because DRF's `@api_view` does not accept a coroutine
    function. The bridge is `async_to_sync`, and it lives here rather than in the shared layer: the
    shared half is genuinely asynchronous and it is this framework's adapter that has to cope.
    """
    return Response({"sections": async_sections_for_api()})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def plans(request: Request) -> Response:
    """EXPLAIN (a prediction) beside a DebugReport (a measurement)."""
    return Response({"sections": lab_usecases.plans_sections(_session(request))})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def pagination(request: Request) -> Response:
    """Pagination over the high-volume table (visits): LIMIT/OFFSET with prev/next."""
    page = _page_param(request)
    return Response(
        lab_usecases.pagination_result(_session(request), page=page, size=20)
    )


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def problems(request: Request) -> Response:
    """Deliberately triggers a duplicate and an N+1 so the panel flags them; the value is in the panel."""
    lab_usecases.run_problems(_session(request))
    return Response({"ran": True})


def _page_param(request: Request) -> int:
    """The page number from the query string (`?page=N`), 0 if missing or not a valid integer."""
    raw = request.query_params.get("page", "0")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0
