"""Routes of the engagement PAGES (SSR). The JSON side lives in `urls.py` next door, under `/api/`.

Two files because there are two surfaces, the same split `apps/auth/`, `apps/inventory/`,
`apps/orders/`, `apps/billing/`, `apps/taxonomy/` and `apps/logistics/` already made: `urls.py` is
the API router mounted at `/api/engagement/`, and this one is the pages, mounted at `/engagement/`.

THREE ROUTES AND NOT FIVE, and the two that are missing are the domain's statement rather than two
forms nobody wrote. There is no `create` page: a comment, a reaction and a visit are all written from
the sheet of the post they belong to, because none of the three exists apart from a post. And there
is no `delete`: this demo has no operation that withdraws a comment or a reaction — the API has none
either, so a page for it would be a screen over a use case that does not exist.

`detail/<int:post_id>/` takes a POST as well as a GET, which is where the page taxonomy bends the way
`taxonomy` and `logistics` already bend it: a browser `<form>` emits only GET and POST, so the three
writes ride in the body under an `action` rather than being three verbs on a resource.

`export/` takes no key at all and its filter rides on the query string, exactly as the inventory and
orders exports do — and it answers a file rather than a page, which is why there is no template for
it anywhere.

The trailing slash stays — Django's convention, `APPEND_SLASH` redirects what arrives without one —
and the Flask mirror of these pages deliberately does not have it.
"""

from __future__ import annotations

from django.urls import path

from apps.engagement import views

urlpatterns = [
    path("list/", views.traffic_board, name="engagement_list"),
    path("detail/<int:post_id>/", views.engagement_sheet, name="engagement_detail"),
    path("export/", views.visits_export, name="engagement_export"),
]
