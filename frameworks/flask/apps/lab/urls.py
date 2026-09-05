"""LAB routes (SSR): every page exercises one family of ORM operations so you can try it out.

The views are THIN, and now genuinely so: each one calls `shared.usecases.lab_usecases`, which is
the same function the JSON API calls, and hands the result to a template. Nothing here builds a
section.

It used to build them, and that is what this file is a correction of: a hundred and ten lines that
assembled the very same titles, notes, headers and rows the shared use cases already assembled, with
their own private `_section`. Two copies of one page's meaning, and they had already drifted — the
column headers were translated in one and left Spanish in the other, and the Django demo was calling
the shared ones the whole time. That is the point of `shared`: the demo is a WRAPPER.

The session is `g.session` (opened by the blog blueprint's app-wide hooks). The debug panel injects
itself at the end of every response: that is where you see the SQL, the timings and the duplicates
that this very page generated.

Every experiment page paints its sections with `lab/_section.html`, and that partial is an INCLUDE
and not a Jinja macro on purpose: Django can only include, and the two demos are meant to read the
same way. Jinja hands the surrounding context to an include, so inside a `{% for section in
sections %}` the Flask file sees `section` exactly as the Django one does.
"""

from __future__ import annotations

from flask import Blueprint, g, make_response, render_template, request, url_for
from flask.typing import ResponseReturnValue

from snakeorm.drivers import AsyncSnakePool

from shared import config
from shared.viewmodels import lab_viewmodels
from shared.usecases import lab_usecases
from shared.web import lab_pages

lab = Blueprint("lab", __name__, url_prefix="/lab")


@lab.get("/list")
def list_sections() -> ResponseReturnValue:
    """The lab's landing listing: one COUNT per table, plus the links out to the experiments.

    Counting table by table is deliberate: 20 SELECTs the panel lists at a glance, so you can see
    the seeded volume and, along the way, notice that 20 separate COUNTs is NOT optimal (a reading
    lesson).

    It is `list` and not `index`, in the action, in the route and in the template's path. The
    catalogue in `shared.web.nav` gives every section a `list` page, and a lab that called its
    landing something else would be the one section the sidebar had to special-case — which is
    exactly what a link falls through.
    """
    section = lab_usecases.index_sections(g.session)[0]
    return render_template("lab/list/lab_list.html", section=section)


@lab.get("/aggregates")
def aggregates() -> ResponseReturnValue:
    """Aggregates: typed `annotate` (1 hop) and `GROUP BY`+`SUM` at the SQL level."""
    return render_template(
        "lab/experiment/lab_experiment.html",
        page_title="Aggregates",
        intro="Typed annotate and GROUP BY/SUM. Open the panel to see the SQL of each one.",
        sections=lab_usecases.aggregates_sections(g.session),
    )


@lab.get("/subqueries")
def subqueries() -> ResponseReturnValue:
    """Subqueries: EXISTS, NOT EXISTS and IN (over the N-N bridge table)."""
    return render_template(
        "lab/experiment/lab_experiment.html",
        page_title="Subqueries",
        intro="EXISTS / NOT EXISTS / IN. Open the panel to see the subquery nested in the WHERE.",
        sections=lab_usecases.subqueries_sections(g.session),
    )


@lab.get("/joins")
def joins() -> ResponseReturnValue:
    """Joins and include: loading relations in ONE query (no N+1)."""
    return render_template(
        "lab/experiment/lab_experiment.html",
        page_title="Joins / include",
        intro=(
            "include resolves the relationships in one query. Open the panel: you will see a "
            "SINGLE SELECT with JOINs."
        ),
        sections=lab_usecases.joins_sections(g.session),
    )


@lab.get("/expressions")
def expressions() -> ResponseReturnValue:
    """Scalar functions: text, maths, JSON, case-insensitive match, dates and named pairs."""
    return render_template(
        "lab/experiment/lab_experiment.html",
        page_title="Scalar functions",
        intro="The engine computes and Python only reads. Open the panel: the function is in the SQL.",
        sections=lab_usecases.expressions_sections(g.session),
    )


_ASYNC_POOL: AsyncSnakePool | None = None


def _async_pool() -> AsyncSnakePool:
    """The process's pool of asynchronous connections, opened on first use.

    Flask has no lifespan the way an ASGI app does, so it is built lazily here. One per REQUEST is
    the thing a pool exists to prevent; one built at import would open sockets while the CLI is
    only importing the app.
    """
    global _ASYNC_POOL
    if _ASYNC_POOL is None:
        _ASYNC_POOL = config.make_async_pool("flask")
    return _ASYNC_POOL


async def async_pool_sections() -> list[dict[str, object]]:
    """Borrow, read, give back. The one place that owns the connection's lifetime.

    Shared by the page and the API so the borrow/return dance is written once: two copies of a
    `finally` is one copy away from a pool that leaks on the surface nobody looked at.
    """
    session = config.async_session_over(await _async_pool().acquire())
    try:
        return list(await lab_viewmodels.async_sections(session))
    finally:
        await session.close()


@lab.get("/asynchronous")
async def asynchronous() -> ResponseReturnValue:
    """The same reads over an `AsyncSession`, on a connection borrowed from the pool.

    An `async def` view: Flask runs it through `asgiref` on a loop of its own. The session is closed
    in a `finally` because closing is what GIVES THE CONNECTION BACK — leak it and the pool empties
    one request at a time, and the failure surfaces much later as a timeout that names nothing.
    """
    sections = await async_pool_sections()
    return render_template(
        "lab/experiment/lab_experiment.html",
        page_title="The asynchronous seam",
        intro="The same queries, awaited. A SnakeQuery has no colour: these selectors are the ones the synchronous pages import.",
        sections=sections,
    )


@lab.get("/plans")
def plans() -> ResponseReturnValue:
    """EXPLAIN (a prediction) beside a DebugReport (a measurement)."""
    return render_template(
        "lab/experiment/lab_experiment.html",
        page_title="Plan and report",
        intro="What the engine SAYS it will do, and what a request actually did. Two questions that look alike.",
        sections=lab_usecases.plans_sections(g.session),
    )


@lab.get("/pagination")
def pagination() -> ResponseReturnValue:
    """Pagination over the HIGH-VOLUME table (visits): LIMIT/OFFSET with prev/next.

    ONE url answers twice: the whole page to a browser, the panel alone to HTMX. A sibling route for
    the fragment would put two addresses on every pager link — an `href` for the browser and an
    `hx-get` for HTMX — and two addresses for one answer is how a fragment ends up showing different
    rows from the page it replaces. The links carry the same string in both attributes, so the pager
    still pages with JavaScript switched off: nothing sends the header, and the browser navigates.

    Reading the headers is Flask's half; what they MEAN is `shared.web.lab_pages`, which the Django
    view asks the same question. `Vary` because two answers share a url, and a cache that does not
    know that serves a bare fragment to the back button.

    THE TWO LINKS ARE REVERSED HERE AND NOT IN THE TEMPLATE, which is what leaves `lab/_pagination.html`
    identical to Django's. Building a url needs the router, so it belongs to the framework: Django
    keeps a trailing slash where Flask does not, and a path written by hand in `shared/` would be
    right in one demo and a silent redirect in the other.
    """
    page = max(0, request.args.get("page", default=0, type=int))
    result = lab_usecases.pagination_result(g.session, page=page, size=20)
    result["previous_url"] = url_for("lab.pagination", page=max(0, page - 1))
    result["next_url"] = url_for("lab.pagination", page=page + 1)
    template = lab_pages.pagination_template(
        htmx=request.headers.get("HX-Request") == "true",
        restoring_history=request.headers.get("HX-History-Restore-Request") == "true",
    )
    response = make_response(render_template(template, **result))
    response.vary.add("HX-Request")
    return response


@lab.get("/problems")
def problems() -> ResponseReturnValue:
    """DELIBERATELY provokes a literal duplicate and an N+1, so that the panel flags them.

    `run_problems` runs healthy reads PLUS two anti-patterns: it asks twice for the same published
    posts (a literal duplicate) and fetches the tokens user by user in a loop (an N+1). Nothing is
    captured here: the queries fall inside the SSR middleware's scope, so the panel counts them and
    flags the duplicates.
    """
    lab_usecases.run_problems(g.session)
    return render_template("lab/problems/lab_problems.html")
