"""SSR routes of the LAB (the panel's Jinja pages). The JSON API lives in `api_urls.py`.

The `lab` namespace (`app_name`) is what lets `apps/nav.py` name these routes without colliding with
the rest of the demo, and what lets the sub-nav resolve its links by name. The `/lab/` prefix comes
from the root urls include; the API hangs apart from `/api/lab/…` (same as Flask and FastAPI).

The landing page is `list`, not `index`, and the rename was not cosmetic: the shared catalogue gives
every section a `list` page so that "each domain has a listing" is an invariant rather than a rule
with one carve-out in it, and a carve-out is what a sidebar link falls through.
"""

from __future__ import annotations

from django.urls import path

from apps.lab import views

app_name = "lab"

urlpatterns = [
    # SSR: one page per family of ORM experiments (MIRROR of the Flask Lab).
    path("", views.listing, name="list"),
    path("aggregates", views.aggregates, name="aggregates"),
    path("subqueries", views.subqueries, name="subqueries"),
    path("joins", views.joins, name="joins"),
    path("expressions", views.expressions, name="expressions"),
    path("plans", views.plans, name="plans"),
    path("asynchronous", views.asynchronous, name="asynchronous"),
    path("pagination", views.pagination, name="pagination"),
    path("problems", views.problems, name="problems"),
]
