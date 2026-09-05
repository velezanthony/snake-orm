"""Routes of the Lab's JSON API, under `/api/lab/` (identical to Flask and FastAPI).

They are kept apart from the SSR urlconf (`urls.py`, under `/lab/`) so the prefix is `/api/lab/…`
—the SAME one the other two frameworks use— instead of `/lab/api/…`. The views are the very ones
from `apps.lab.api`.
"""

from __future__ import annotations

from django.urls import path

from apps.lab import api

app_name = "lab_api"

urlpatterns = [
    path("", api.index, name="index"),
    path("aggregates", api.aggregates, name="aggregates"),
    path("subqueries", api.subqueries, name="subqueries"),
    path("joins", api.joins, name="joins"),
    path("expressions", api.expressions, name="expressions"),
    path("plans", api.plans, name="plans"),
    path("asynchronous", api.asynchronous, name="asynchronous"),
    path("pagination", api.pagination, name="pagination"),
    path("problems", api.problems, name="problems"),
]
