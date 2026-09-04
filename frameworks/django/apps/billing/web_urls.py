"""Routes of the billing PAGES (SSR). The JSON side lives in `urls.py` next door, under `/api/`.

Two files because there are two surfaces, the same split `apps/auth/` and `apps/inventory/` already
made: `urls.py` is the API router mounted at `/api/billing/`, and this one is the pages, mounted at
`/billing/`. One file serving both would make the include line in `config/urls.py` decide which half
it wanted, which it cannot.

THREE ROUTES AND NOT SIX, and the three that are missing are the point of the domain. There is no
`create/`, no `update/` and no `delete/` here: an invoice is RAISED by an operation over in orders
and SETTLED by another, and a form that let somebody retype an amount would be a demo of the one
thing accounting software must never offer. `shared/tests/test_nav.py` asserts that absence, so it
is a decision the catalogue enforces rather than a page nobody got round to.

The trailing slash stays — Django's convention, `APPEND_SLASH` redirects what arrives without one —
and the Flask mirror of these pages deliberately does not have it. The action is in the path rather
than implied by the verb, which is the page taxonomy written into the URL: a reader who has seen
`/inventory/report/` can guess this one before opening it.

`<int:invoice_id>` and not a bare `<invoice_id>`: a URL with a word where the id goes is a 404 from
the router rather than a `ValueError` from a view.
"""

from __future__ import annotations

from django.urls import path

from apps.billing import views

urlpatterns = [
    path("list/", views.invoice_list, name="billing_list"),
    path("detail/<int:invoice_id>/", views.invoice_detail, name="billing_detail"),
    path("report/", views.billing_report, name="billing_report"),
]
