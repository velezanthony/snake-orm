"""JSON API of the LAB with flask-smorest: every ORM experiment, returned as JSON.

A MIRROR of FastAPI's Lab router (`apps/lab/urls.py`): THIN endpoints that delegate to the SHARED
use cases (`shared.usecases.lab_usecases`), which already return JSON-able "sections" (title . note
. columns . rows). The SSR (`urls.py`) and this API consume exactly the same functions: the Lab is
identical across the three frameworks without duplicating any logic.

The ORM session is hung on `g.session` by the blog's app-wide hook. Because this is a smorest
blueprint registered with `api.register_blueprint(...)`, EVERY endpoint here shows up in the Swagger
at `/api/docs`.
"""

from __future__ import annotations

from typing import Any

from flask import g, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps.lab.urls import async_pool_sections
from shared.usecases import lab_usecases

blp = Blueprint(
    "lab-api",
    __name__,
    url_prefix="/api/lab",
    description="Laboratory: the ORM's experiments, in JSON",
)


@blp.route("/")
def index() -> ResponseReturnValue:
    """Lab index: one COUNT(*) for each of the 20 seeded tables."""
    return {"sections": lab_usecases.index_sections(g.session)}


@blp.route("/aggregates")
def aggregates() -> ResponseReturnValue:
    """Aggregates: typed `annotate` (1 hop) and `GROUP BY`+`SUM` at the SQL level."""
    return {"sections": lab_usecases.aggregates_sections(g.session)}


@blp.route("/subqueries")
def subqueries() -> ResponseReturnValue:
    """Subqueries: EXISTS, NOT EXISTS and IN (over the N-N bridge)."""
    return {"sections": lab_usecases.subqueries_sections(g.session)}


@blp.route("/joins")
def joins() -> ResponseReturnValue:
    """Joins and include: loading relations in ONE single query (no N+1)."""
    return {"sections": lab_usecases.joins_sections(g.session)}


@blp.route("/expressions")
def expressions() -> ResponseReturnValue:
    """Scalar functions: text, maths, JSON, case-insensitive match, dates and named pairs."""
    return {"sections": lab_usecases.expressions_sections(g.session)}


@blp.route("/asynchronous")
async def asynchronous() -> ResponseReturnValue:
    """The same reads over an `AsyncSession`, borrowed from the pool. Flask awaits it natively."""
    return {"sections": await async_pool_sections()}


@blp.route("/plans")
def plans() -> ResponseReturnValue:
    """EXPLAIN (a prediction) beside a DebugReport (a measurement)."""
    return {"sections": lab_usecases.plans_sections(g.session)}


@blp.route("/pagination")
def pagination() -> dict[str, Any]:
    """Pagination over the high-volume table (visits): LIMIT/OFFSET with prev/next."""
    page = request.args.get("page", default=0, type=int)
    return lab_usecases.pagination_result(g.session, page=page, size=20)


@blp.route("/problems")
def problems() -> ResponseReturnValue:
    """Deliberately provokes a duplicate and an N+1 so the panel flags them; the value is in the panel."""
    lab_usecases.run_problems(g.session)
    return {"ran": True}
