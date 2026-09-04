"""JSON routes of the orders domain. The `/api/orders/` prefix comes from the root urls include.

`urls.py` is the JSON surface and `web_urls.py` the pages, which is the split `auth`, `inventory`
and `billing` already make in this demo. The name says which surface it serves.

THE COLLECTION IS `/api/orders/`, WITH THE SLASH, and it is worth knowing before you send a POST
without one. Django's `APPEND_SLASH` redirects a GET to the canonical URL, but it REFUSES to do it
for a POST and says why — a 301 cannot carry a body, so redirecting would silently drop the order
somebody just placed. Django raises instead of losing it, which is the framework behaving exactly
like this ORM does. The blog's API already ends every path in a slash for the same reason; Flask and
FastAPI serve `/api/orders` because neither has this rule. What the parity net compares is the
OPERATION, so one slash of difference between three routers is not drift.

The paths mirror the other two demos exactly — `shared/tests/test_the_demos_serve_the_same_routes.py`
is what holds them to it — and three of them route two verbs to ONE view, because that is how Django
routes: a URL resolves to a single callable, so the collection answers GET and POST from `api.orders`
and the item GET and DELETE from `api.order`.
"""

from __future__ import annotations

from django.urls import path

from apps.orders import api

urlpatterns = [
    path("", api.orders, name="orders_api"),
    path("page", api.paginate_orders, name="orders_api_page"),
    path("report", api.order_report, name="orders_api_report"),
    path("states", api.orders_per_state, name="orders_api_states"),
    path("customers", api.customer_orders, name="orders_api_customers"),
    path("export", api.export_lines, name="orders_api_export"),
    path(
        "customers/<int:customer_id>",
        api.orders_of_customer,
        name="orders_api_of_customer",
    ),
    path("<int:order_id>", api.order, name="orders_api_detail"),
    path("<int:order_id>/lines", api.order_lines, name="orders_api_lines"),
    path(
        "<int:order_id>/lines/<int:sku_id>",
        api.remove_line,
        name="orders_api_remove_line",
    ),
    path("<int:order_id>/invoice", api.attach_invoice, name="orders_api_invoice"),
    path("<int:order_id>/reserve", api.reserve, name="orders_api_reserve"),
    path("<int:order_id>/settle", api.settle, name="orders_api_settle"),
    path("<int:order_id>/cancel", api.cancel_order, name="orders_api_cancel"),
]
