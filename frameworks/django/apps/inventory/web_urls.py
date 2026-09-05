"""Routes of the inventory PAGES (SSR). The JSON side lives in `urls.py` next door, under `/api/`.

Two files because there are two surfaces, the same split `apps/auth/` already made: `urls.py` is the
API router mounted at `/api/inventory/`, and this one is the pages, mounted at `/inventory/`. One
file serving both would make the include line in `config/urls.py` decide which half it wanted, which
it cannot.

The `/inventory/` prefix comes from that include, and the ACTION is part of the path —`list/`,
`detail/`, `create/`— rather than implied by the verb. That is the page taxonomy written into the
URL: opening any domain of the demo tells you where the same page lives in the others, and a reader
who has seen `/inventory/list/` can guess `/orders/list/` before it exists.

The trailing slash stays. It is Django's convention, `APPEND_SLASH` is what redirects the requests
that arrive without one, and Flask's mirror of these pages deliberately does not have it: the two
demos are meant to look like what a developer of each framework would actually have written.

Both halves of the composite key are in the path of every route that needs one, and they are typed
`<int:...>` so a URL with a word in it is a 404 from the router rather than a `ValueError` from a
view.
"""

from __future__ import annotations

from django.urls import path

from apps.inventory import views

urlpatterns = [
    path("list/", views.stock_list, name="inventory_list"),
    path(
        "detail/<int:warehouse_id>/<int:sku_id>/",
        views.stock_detail,
        name="inventory_detail",
    ),
    path("create/", views.stock_create, name="inventory_create"),
    path(
        "update/<int:warehouse_id>/<int:sku_id>/",
        views.stock_update,
        name="inventory_update",
    ),
    path(
        "delete/<int:warehouse_id>/<int:sku_id>/",
        views.stock_delete,
        name="inventory_delete",
    ),
    path(
        "detail/<int:warehouse_id>/<int:sku_id>/receive/",
        views.stock_receive,
        name="inventory_receive",
    ),
    path(
        "detail/<int:warehouse_id>/<int:sku_id>/ship/",
        views.stock_ship,
        name="inventory_ship",
    ),
    path("catalogue/", views.stock_catalogue, name="inventory_catalogue"),
    path(
        "catalogue/warehouses/",
        views.warehouse_create,
        name="inventory_warehouse_create",
    ),
    path("catalogue/skus/", views.sku_create, name="inventory_sku_create"),
    path(
        "catalogue/warehouses/<int:warehouse_id>/reserve/",
        views.warehouse_reserve,
        name="inventory_warehouse_reserve",
    ),
    # The reorder screen takes NO key: "what is running out" is a question about the whole
    # stockroom, which is why the sidebar can link it. The sheet next to it takes one HALF of the
    # composite key, and that is the point rather than an inconsistency — a warehouse is a row in its
    # own right, and everything this page shows hangs off it.
    path("alerts/", views.stock_alerts, name="inventory_alerts"),
    # The book takes no key either, and for a third reason: it is about the two origins that
    # write the movements, not about a warehouse or a pair.
    path("book/", views.movement_book, name="inventory_book"),
    path(
        "warehouse/<int:warehouse_id>/",
        views.warehouse_sheet,
        name="inventory_warehouse",
    ),
    path("report/", views.stock_report, name="inventory_report"),
    # The export takes no key at all, and its filter rides on the query string rather than in the
    # path: `?warehouse=` narrows what the file contains, which is not the same kind of thing as a
    # route naming the row it is about. A sidebar link has to reach the unfiltered whole, and it
    # does — the parameter is optional everywhere it appears.
    path("export/", views.stock_movements_export, name="inventory_export"),
]
