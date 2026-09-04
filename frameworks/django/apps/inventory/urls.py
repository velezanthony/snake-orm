"""Routes of the inventory domain. The `/inventory/` prefix comes from the root urls include."""

from __future__ import annotations

from django.urls import path

from apps.inventory import api

urlpatterns = [
    path("warehouses", api.warehouses, name="inventory_warehouses"),
    path(
        "warehouses/<int:warehouse_id>",
        api.get_warehouse,
        name="inventory_get_warehouse",
    ),
    path("skus", api.skus, name="inventory_skus"),
    path("low-stock", api.low_stock, name="inventory_low_stock"),
    path("movement-book", api.movement_book, name="inventory_movement_book"),
    path("stats", api.warehouse_stats, name="inventory_stats"),
    # The pager hangs off `stock/` and not off a warehouse, because the filter is OPTIONAL: with no
    # `?warehouse_id` it pages the whole inventory, which is not a sub-resource of anything. It
    # cannot shadow `warehouses/<id>/stock` either — that path starts with a different segment, so
    # the two never reach the same matcher.
    path("stock/page", api.paginate_stock, name="inventory_stock_page"),
    # `_api` ON THE END OF BOTH NAMES, AND IT IS NOT DECORATION. `web_urls.py` next door already
    # calls its pages `inventory_report` and `inventory_export`, and a Django url NAME is global:
    # two routes claiming one name do not collide loudly, the second one WINS, and every `reverse()`
    # in the demo silently starts answering with the other surface's path. It happened — the sidebar
    # was measured serving `/api/inventory/report` under a link labelled "Report", so the Inventory
    # section's report and its CSV both sent a reader to raw JSON. Nothing raised; the page still
    # existed and still answered, and the only thing wrong was where every link to it pointed.
    #
    # `apps/billing/urls.py` spells its own `/api/billing/report` `billing_report_api` for exactly
    # this reason. The rule the two of them make: an API route in a domain that also has PAGES never
    # takes the bare name, because the pages had it first and they are what a template reverses.
    path("report", api.stock_report, name="inventory_report_api"),
    path("export", api.export_movements, name="inventory_export_api"),
    path(
        "warehouses/<int:warehouse_id>/stock",
        api.stock_of_warehouse,
        name="inventory_stock",
    ),
    path(
        "warehouses/<int:warehouse_id>/stock/movements",
        api.stock_with_movements,
        name="inventory_stock_movements",
    ),
    path(
        "warehouses/<int:warehouse_id>/stock/<int:sku_id>/movements",
        api.movements_of,
        name="inventory_movements_of",
    ),
    # THESE TWO HAD THE COLLISION ALREADY AND IT WAS NOT LATENT — it was live, and it was the SSR
    # demo posting its forms at the JSON API. `web_urls.py` names the receive and ship PAGES
    # `inventory_receive` and `inventory_ship`; this file claimed the same two names for the
    # endpoints, and this file is included second, so `reverse("inventory_receive", [1, 2])`
    # answered `/api/inventory/warehouses/1/stock/2/receive`. That is what
    # `templates/inventory/detail/inventory_detail.html` puts in the `action` of both of its forms,
    # so a reader pressing "Receive" on the stock sheet was posting to DRF and getting a JSON
    # document back instead of the page they were on.
    #
    # NOTHING COULD SEE IT, which is why it survived. `test_every_route_answers.py` walks routes and
    # both routes answer; the surface comparisons read the paths, which are right; the templates
    # match file for file, and the difference is inside one attribute. A url NAME is the one thing
    # in this demo that two files can claim without anybody being told.
    path(
        "warehouses/<int:warehouse_id>/stock/<int:sku_id>/receive",
        api.receive,
        name="inventory_receive_api",
    ),
    path(
        "warehouses/<int:warehouse_id>/stock/<int:sku_id>/ship",
        api.ship,
        name="inventory_ship_api",
    ),
    path(
        "warehouses/<int:warehouse_id>/stock/<int:sku_id>",
        api.stock_pair,
        name="inventory_stock_pair",
    ),
    path(
        "warehouses/<int:warehouse_id>/reserve",
        api.reserve,
        name="inventory_reserve",
    ),
]
