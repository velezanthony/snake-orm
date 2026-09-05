"""Routes of the logistics PAGES (SSR). The JSON side lives in `urls.py` next door, under `/api/`.

Two files because there are two surfaces, the same split `apps/auth/`, `apps/inventory/`,
`apps/orders/`, `apps/billing/` and `apps/taxonomy/` already made: `urls.py` is the API router mounted
at `/api/logistics/`, and this one is the pages, mounted at `/logistics/`.

FOUR ROUTES AND NOT FIVE, and the missing one is a `create`. There is no page to book a delivery and
none to open a depot, and that is the domain's statement rather than two forms nobody wrote: a
delivery is booked by whatever system takes the customer's order, a depot is a building somebody
surveyed, and a box size is a fact about cardboard. What a dispatcher DOES is move a delivery to the
right depot, and that is the one write here.

`detail/<int:delivery_id>/` takes a POST as well as a GET, which is the one place in this module where
the taxonomy of pages bends: a browser `<form>` emits only GET and POST, so rerouting is a POST to the
page that shows the ranking rather than a `PATCH` on a delivery resource the way the API does it.

The trailing slash stays — Django's convention, `APPEND_SLASH` redirects what arrives without one —
and the Flask mirror of these pages deliberately does not have it.
"""

from __future__ import annotations

from django.urls import path

from apps.logistics import views

urlpatterns = [
    path("list/", views.depot_list, name="logistics_list"),
    path("detail/<int:delivery_id>/", views.delivery_sheet, name="logistics_detail"),
    path("dispatch/", views.dispatch_board, name="logistics_dispatch"),
    path("load/", views.slot_load, name="logistics_load"),
]
