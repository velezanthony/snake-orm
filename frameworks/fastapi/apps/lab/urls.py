"""Router of the LAB as a JSON API: every ORM experiment returned as JSON.

THIN endpoints: no queries and no inline logic. Each endpoint (1) receives the session through the
shared dependency and (2) delegates to a SHARED use case (`shared.usecases.lab_usecases`), which
already returns JSON-able "sections" (title . note . columns . rows). The SSR (Flask/Django) and the
API consume exactly the same functions: the Lab is identical in all three without duplicated logic.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.deps import SessionDep, SyncSessionDep
from shared.viewmodels import lab_viewmodels
from shared.usecases import lab_usecases

router = APIRouter(prefix="/api/lab", tags=["lab"])


# `def` and not `async def`, and that is the whole of it: these endpoints await nothing, and an
# `async def` runs on the event loop's thread while its SYNCHRONOUS dependency is resolved in the
# threadpool. That put the SQLite connection on one thread and its use on another, which `sqlite3`
# refuses outright (`check_same_thread`). Plain `def` sends both to the same threadpool thread.
# `asynchronous` below stays `async` because it really does await an AsyncSession.
@router.get("/")
def index(session: SyncSessionDep) -> dict[str, Any]:
    """Lab index: one COUNT(*) for each of the 20 seeded tables."""
    return {"sections": lab_usecases.index_sections(session)}


@router.get("/aggregates")
def aggregates(session: SyncSessionDep) -> dict[str, Any]:
    """Aggregates: typed `annotate` (1 hop) and `GROUP BY`+`SUM` at the SQL level."""
    return {"sections": lab_usecases.aggregates_sections(session)}


@router.get("/subqueries")
def subqueries(session: SyncSessionDep) -> dict[str, Any]:
    """Subqueries: EXISTS, NOT EXISTS and IN (over the N-N bridge)."""
    return {"sections": lab_usecases.subqueries_sections(session)}


@router.get("/joins")
def joins(session: SyncSessionDep) -> dict[str, Any]:
    """Joins and include: loading relations in ONE single query (no N+1)."""
    return {"sections": lab_usecases.joins_sections(session)}


@router.get("/expressions")
def expressions(session: SyncSessionDep) -> dict[str, Any]:
    """Scalar functions: text, maths, JSON, case-insensitive match, dates and named pairs."""
    return {"sections": lab_usecases.expressions_sections(session)}


@router.get("/asynchronous")
async def asynchronous(session: SessionDep) -> dict[str, Any]:
    """The lab's ONE route on `SessionDep`, and the exception is the point of the page.

    Every other lab endpoint takes `SyncSessionDep` because the catalogue it renders is synchronous.
    This one renders the ASYNC twin, so it takes the pooled `AsyncSession` the rest of this demo
    runs on — the borrow and the return are the dependency's, not this function's.
    """
    return {"sections": await lab_viewmodels.async_sections(session)}


@router.get("/plans")
def plans(session: SyncSessionDep) -> dict[str, Any]:
    """EXPLAIN (a prediction) beside a DebugReport (a measurement)."""
    return {"sections": lab_usecases.plans_sections(session)}


@router.get("/pagination")
def pagination(session: SyncSessionDep, page: int = 0) -> dict[str, Any]:
    """Pagination over the high-volume table (visits): LIMIT/OFFSET with prev/next."""
    return lab_usecases.pagination_result(session, page=page, size=20)


@router.get("/problems")
def problems(session: SyncSessionDep) -> dict[str, Any]:
    """Deliberately provokes a duplicate and an N+1 so the panel flags them; the value is in the panel."""
    lab_usecases.run_problems(session)
    return {"ran": True}
