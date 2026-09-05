"""Routes of the orders PAGES (SSR). This domain has no JSON side, so there is no `urls.py` next door.

The five pages of the taxonomy are named the way `apps/inventory/web_urls.py` names them, with the
ACTION written into the path rather than implied by the verb — that is what lets a reader who has
seen `/inventory/list/` guess `/orders/list/`. The trailing slash stays: it is Django's convention,
`APPEND_SLASH` redirects the requests that arrive without one, and the Flask mirror of these pages
deliberately does not have it.

WHAT THIS DOMAIN ADDS IS `operate`, and its shape is a contract rather than a preference.
`shared/web/nav.py` puts `operate` in the sidebar, and a sidebar link carries no id — so the bare
`/orders/operate/` has to answer something useful on its own. It answers the CHOOSER: the listing
narrowed to the drafts an operation starts from. The path with an id is the operation page proper.
Two routes, one action, because the catalogue names things and the router locates them.

THE THREE OPERATIONS ARE POST-ONLY ROUTES OF THEIR OWN, and not one route branching on a button
name. Three reasons, in the order they cost something:

- each one is a different transaction with a different failure map, and a single handler would have
  to read the form before it knew which — a read, on the path where a read is exactly what must not
  happen (see `views.py`);
- the URL is then a name for the thing that happened, which is what a log line, a 405 and a redirect
  all end up quoting;
- and `require_POST` can then say what each one accepts. A GET that reserved an order would be an
  operation a crawler, a prefetch or a browser's back button can perform.

They hang UNDER `operate/<id>/` and not beside it, because they are what that page does. Deleting
the operation page would leave three routes pointing at nothing, and a URL tree that says so is one
fewer thing to remember.
"""

from __future__ import annotations

from django.urls import path

from apps.orders import views

urlpatterns = [
    path("list/", views.order_list, name="orders_list"),
    path("detail/<int:order_id>/", views.order_detail, name="orders_detail"),
    path("create/", views.order_create, name="orders_create"),
    path("update/<int:order_id>/", views.order_update, name="orders_update"),
    path("delete/<int:order_id>/", views.order_delete, name="orders_delete"),
    # A CUSTOMER's id and not an order's, which is the one route here whose key names something that
    # lives in another domain. It is reached from the report's customer table rather than from the
    # listing, because that table is where the question gets asked.
    path("customer/<int:customer_id>/", views.customer_sheet, name="orders_customer"),
    path("report/", views.order_report, name="orders_report"),
    # `?state=` narrows what the file contains and is optional everywhere, so the sidebar link — which
    # carries nothing — reaches the whole export. The filter is a query parameter and not a path
    # segment because it says how much of one thing you want, not which thing.
    path("export/", views.order_lines_export, name="orders_export"),
    path("operate/", views.order_operate_index, name="orders_operate_index"),
    path("operate/<int:order_id>/", views.order_operate, name="orders_operate"),
    path("operate/<int:order_id>/reserve/", views.order_reserve, name="orders_reserve"),
    path("operate/<int:order_id>/settle/", views.order_settle, name="orders_settle"),
    path("operate/<int:order_id>/attach/", views.order_attach, name="orders_attach"),
    path("operate/<int:order_id>/cancel/", views.order_cancel, name="orders_cancel"),
]
