"""SSR views of the LAB: every page exercises a family of ORM operations in order to prove it.

MIRROR of the Flask Lab: the views are thin and delegate to the SHARED catalogue of experiments
(`shared.usecases.lab_usecases`), which builds "sections" (title · note · columns · rows) that are
already JSON-able; a generic template paints them — `lab/_section.html` is one section, title, note
and table, and every experiment page includes it once per section it has. They use `request.snake_session` (the request's
ORM session, opened by `SnakeSessionMiddleware`). The debug panel is injected at the end of every
response: that is where you see the SQL, the timings and the duplicates that this very page produced.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django_htmx.middleware import HtmxDetails


from asgiref.sync import async_to_sync

from snakeorm.drivers import AsyncSnakePool

from apps.session import snake_session
from shared import config
from shared.viewmodels import lab_viewmodels
from shared.usecases import lab_usecases
from shared.web import lab_pages


_session = snake_session


class HtmxHttpRequest(HttpRequest):
    """A request the HtmxMiddleware has been through, so `request.htmx` is there and is typed.

    The middleware sets the attribute dynamically, which no checker can see. django-htmx's own
    documentation prescribes this subclass rather than a cast, and a repository whose rule is zero
    `Any` takes the subclass.
    """

    htmx: HtmxDetails


def listing(request: HttpRequest) -> HttpResponse:
    """The lab's `list` page: counts the 29 tables (one COUNT per table) and links to the experiments.

    Named `listing` rather than `list` because the route name is what the sidebar reads, and shadowing
    a builtin inside a module that will grow more views is a trap for the next person, not a saving.
    """
    section = lab_usecases.index_sections(_session(request))[0]
    return render(request, "lab/list/lab_list.html", {"section": section})


def aggregates(request: HttpRequest) -> HttpResponse:
    """Aggregates: typed `annotate` (1 hop) and `GROUP BY`+`SUM` at the SQL level."""
    return render(
        request,
        "lab/experiment/lab_experiment.html",
        {
            "page_title": "Aggregates",
            "intro": "Typed annotate and GROUP BY/SUM. Open the panel to see the SQL of each one.",
            "sections": lab_usecases.aggregates_sections(_session(request)),
        },
    )


def subqueries(request: HttpRequest) -> HttpResponse:
    """Subqueries: EXISTS, NOT EXISTS and IN (over the N—N bridge table)."""
    return render(
        request,
        "lab/experiment/lab_experiment.html",
        {
            "page_title": "Subqueries",
            "intro": "EXISTS / NOT EXISTS / IN. Open the panel to see the subquery nested in the WHERE.",
            "sections": lab_usecases.subqueries_sections(_session(request)),
        },
    )


def joins(request: HttpRequest) -> HttpResponse:
    """Joins and include: loading relations in ONE query (no N+1)."""
    return render(
        request,
        "lab/experiment/lab_experiment.html",
        {
            "page_title": "Joins / include",
            "intro": "include resolves the relationships in one query. Open the panel: you will see a SINGLE SELECT with JOINs.",
            "sections": lab_usecases.joins_sections(_session(request)),
        },
    )


_ASYNC_POOL: AsyncSnakePool | None = None


def _async_pool() -> AsyncSnakePool:
    """The process's pool of asynchronous connections, opened on first use.

    Django has no lifespan hook the way an ASGI app does, so it is built here and lazily. A pool
    per REQUEST would be the thing the pool exists to prevent, and a module-level one built at
    import would open sockets during `manage.py check`.
    """
    global _ASYNC_POOL
    if _ASYNC_POOL is None:
        _ASYNC_POOL = config.make_async_pool("django")
    return _ASYNC_POOL


async def _async_sections() -> list[dict[str, object]]:
    """Borrow, read, give back. The one place that owns the connection's lifetime."""
    session = config.async_session_over(await _async_pool().acquire())
    try:
        return list(await lab_viewmodels.async_sections(session))
    finally:
        await session.close()


def async_sections_for_api() -> list[dict[str, object]]:
    """The same body from a SYNCHRONOUS caller: DRF's `@api_view` refuses a coroutine function.

    The bridge is here and not in `shared/`, deliberately. The shared half IS asynchronous; what
    has to cope with a framework that cannot await is that framework's adapter.

    `_async_sections` is CALLED inside a wrapper rather than handed to `async_to_sync` as a value,
    and that is not a style choice. Passed as an argument it is a name nobody invokes, so the call
    graph — the one `test_the_page_and_the_api_reach_one_usecase` walks — loses the thread and reads
    this route as reaching no use case at all. Which is exactly what it reported.
    """

    async def run() -> list[dict[str, object]]:
        return await _async_sections()

    return async_to_sync(run)()


async def asynchronous(request: HttpRequest) -> HttpResponse:
    """The same reads over an `AsyncSession`, on a connection borrowed from the pool.

    An `async def` view, which Django runs on its own loop. The session is closed in a `finally`
    because closing is what GIVES THE CONNECTION BACK: leak it and the pool empties one request at
    a time, and the failure arrives much later as a timeout that names nothing.
    """
    sections = await _async_sections()
    return render(
        request,
        "lab/experiment/lab_experiment.html",
        {
            "page_title": "The asynchronous seam",
            "intro": "The same queries, awaited. A SnakeQuery has no colour: these selectors are the ones the synchronous pages import.",
            "sections": sections,
        },
    )


def expressions(request: HttpRequest) -> HttpResponse:
    """Scalar functions: text, maths, JSON, case-insensitive match, dates and named pairs."""
    return render(
        request,
        "lab/experiment/lab_experiment.html",
        {
            "page_title": "Scalar functions",
            "intro": "The engine computes and Python only reads. Open the panel: the function is in the SQL.",
            "sections": lab_usecases.expressions_sections(_session(request)),
        },
    )


def plans(request: HttpRequest) -> HttpResponse:
    """EXPLAIN (a prediction) beside a DebugReport (a measurement)."""
    return render(
        request,
        "lab/experiment/lab_experiment.html",
        {
            "page_title": "Plan and report",
            "intro": "What the engine SAYS it will do, and what a request actually did. Two questions that look alike.",
            "sections": lab_usecases.plans_sections(_session(request)),
        },
    )


def pagination(request: HtmxHttpRequest) -> HttpResponse:
    """Pagination over the HIGH-VOLUME table (visits): LIMIT/OFFSET with prev/next.

    ONE url answers twice: the whole page to a browser, the panel alone to HTMX. A sibling route for
    the fragment would put two addresses on every pager link — an `href` for the browser and an
    `hx-get` for HTMX — and two addresses for one answer is how a fragment ends up showing different
    rows from the page it replaces. The links carry the same string in both attributes, so the pager
    still pages with JavaScript switched off: nothing sends the header, and the browser navigates.

    `request.htmx` is django-htmx's middleware and is Django's half of the question; what the flags
    MEAN is `shared.web.lab_pages`, which the Flask view asks the same way. `Vary` because two
    answers share a url, and a cache that does not know that serves a bare fragment to the back
    button.

    THE TWO LINKS ARE REVERSED HERE AND NOT IN THE TEMPLATE, which is what leaves
    `lab/_pagination.html` identical to Flask's. Building a url needs the router, so it belongs to
    the framework: Django keeps a trailing slash where Flask does not, and a path written by hand in
    `shared/` would be right in one demo and a silent redirect in the other.
    """
    page = _page_param(request)
    pager = reverse("lab:pagination")
    result = lab_usecases.pagination_result(_session(request), page=page, size=20)
    result["previous_url"] = f"{pager}?page={max(0, page - 1)}"
    result["next_url"] = f"{pager}?page={page + 1}"
    template = lab_pages.pagination_template(
        htmx=bool(request.htmx),
        restoring_history=request.htmx.history_restore_request,
    )
    response = render(request, template, result)
    patch_vary_headers(response, ["HX-Request"])
    return response


def problems(request: HttpRequest) -> HttpResponse:
    """Triggers ON PURPOSE a literal duplicate and an N+1, so that the panel flags them."""
    lab_usecases.run_problems(_session(request))
    return render(request, "lab/problems/lab_problems.html", {})


def _page_param(request: HttpRequest) -> int:
    """The page number from the query string (`?page=N`), 0 if missing or not a valid integer."""
    raw = request.GET.get("page", "0")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0
