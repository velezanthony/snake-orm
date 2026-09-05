"""Routes of the billing JSON API. The `/api/billing/` prefix comes from the root urls include.

The PAGES of this domain live in `web_urls.py` next door, at `/billing/`; two files because there
are two surfaces and one include line cannot pick a half.

`invoices/unpaid` and `invoices/page` are LITERALS and they sit above `invoices/<int:invoice_id>`.
Django resolves in order, so the order is what keeps them reachable — and the `int` converter would
keep them reachable anyway, since neither word is a number. Both facts hold; relying only on the
second means the day somebody widens the converter, two endpoints disappear without a failure.

`shared/tests/test_the_demos_serve_the_same_routes.py` holds these paths against Flask's and
FastAPI's, so a route added here is a route owed there.
"""

from __future__ import annotations

from django.urls import path

from apps.billing import api

urlpatterns = [
    path("plans", api.list_plans, name="billing_list_plans"),
    path("report", api.billing_report, name="billing_report_api"),
    path(
        "users/<int:user_id>/subscriptions",
        api.subscriptions_of_user,
        name="billing_subscriptions_of_user",
    ),
    path(
        "users/<int:user_id>/invoices",
        api.invoices_of_customer,
        name="billing_invoices_of_customer",
    ),
    path("invoices/unpaid", api.unpaid_invoices, name="billing_unpaid_invoices"),
    path("invoices/page", api.paginate_invoices, name="billing_invoices_page"),
    path("invoices/<int:invoice_id>", api.invoice, name="billing_invoice"),
    path(
        "invoices/<int:invoice_id>/payments",
        api.invoice_payments,
        name="billing_invoice_payments",
    ),
    path("invoices/<int:invoice_id>/pay", api.pay_invoice, name="billing_pay_invoice"),
    path("subscriptions", api.subscribe, name="billing_subscribe"),
    path(
        "subscriptions/<int:subscription_id>/invoices",
        api.subscription_invoices,
        name="billing_subscription_invoices",
    ),
    path(
        "subscriptions/<int:subscription_id>",
        api.cancel_subscription,
        name="billing_cancel_subscription",
    ),
]
