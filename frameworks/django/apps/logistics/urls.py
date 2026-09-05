"""Routes of the logistics JSON API. The `/api/logistics/` prefix comes from the root urls include."""

from __future__ import annotations

from django.urls import path

from apps.logistics import api

urlpatterns = [
    path("depots", api.depots, name="logistics_api_depots"),
    path(
        "deliveries/<int:delivery_id>",
        api.delivery_sheet,
        name="logistics_api_delivery",
    ),
    path("dispatch", api.dispatch, name="logistics_api_dispatch"),
    path("load", api.load, name="logistics_api_load"),
]
