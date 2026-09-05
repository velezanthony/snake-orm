from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    # SSR showcase + OpenAPI of the blog (DRF/drf-spectacular).
    path("auth/", include("apps.auth.web_urls")),
    # Inventory PAGES. `web_urls` and not `urls`: that name is already the JSON router included
    # below at `/api/inventory/`, the same split `apps/auth/` made.
    path("inventory/", include("apps.inventory.web_urls")),
    # Orders PAGES. `web_urls` for the same reason inventory and billing have one: `apps/orders/
    # urls.py` is the JSON router included below at `/api/orders/`. That comment used to say this
    # domain had no JSON side, which is exactly the kind of note that stops being true and stays.
    path("orders/", include("apps.orders.web_urls")),
    # Billing PAGES. `web_urls` for the reason inventory has one: `apps/billing/urls.py` is already
    # the JSON router included below at `/api/billing/`, so the pages need a file of their own
    # rather than a second `urlpatterns` in the same module that the include line would have to
    # choose between.
    path("billing/", include("apps.billing.web_urls")),
    # Taxonomy PAGES, and the same `web_urls` split as the four above: `apps.taxonomy.urls` is the
    # JSON router included below at `/api/taxonomy/`.
    path("taxonomy/", include("apps.taxonomy.web_urls")),
    # Logistics PAGES, and the same `web_urls` split as the five above: `apps.logistics.urls` is the
    # JSON router included below at `/api/logistics/`.
    path("logistics/", include("apps.logistics.web_urls")),
    # The three sections the demos owed, and the same `web_urls`
    # split as everything above: `apps.<domain>.urls` is the JSON router included below at
    # `/api/<domain>/`. Until these three lines existed, the comment further down called them
    # "orphan" domains — which was true of the pages and never of the data.
    path("accounts/", include("apps.accounts.web_urls")),
    path("content/", include("apps.content.web_urls")),
    path("engagement/", include("apps.engagement.web_urls")),
    path("", include("apps.blog.urls")),
    # Lab: SSR (the panel pages) under /lab/, and its JSON API under /api/lab/ (the same prefix
    # as Flask and FastAPI). MIRROR of the Flask Lab.
    path("lab/", include("apps.lab.urls")),
    path("api/lab/", include("apps.lab.api_urls")),
    # The JSON API of every domain (DRF + shared DTOs). Three of these used to be called "orphan"
    # here — accounts, content and engagement answered only as JSON — and the three includes above
    # are what retired the word: each one now serves the same use cases in HTML.
    # BFF: the WHOLE API hangs off `/api/` per resource. `auth` coexists with the SSR session under
    # `/api/auth/` without colliding (distinct sub-paths: `/api/auth/users/<id>/tokens` vs `/api/auth/login`).
    path("api/accounts/", include("apps.accounts.urls")),
    path("api/auth/", include("apps.auth.urls")),
    path("api/billing/", include("apps.billing.urls")),
    path("api/content/", include("apps.content.urls")),
    path("api/engagement/", include("apps.engagement.urls")),
    path("api/inventory/", include("apps.inventory.urls")),
    path("api/logistics/", include("apps.logistics.urls")),
    path("api/orders/", include("apps.orders.urls")),
    path("api/taxonomy/", include("apps.taxonomy.urls")),
]
