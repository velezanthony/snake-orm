"""The billing DTOs: the shapes the JSON surface answers the money domain's five reads with.

These serialisers exist because the pages had five reads the API could not reach, and the closure had
to go through the SAME use cases rather than around them. What the tests below pin is not the JSON
key by key — that would be a change detector — but the three things that can go wrong silently:

THE SPLIT BETWEEN A BARE INVOICE AND ONE WITH ITS PARTIES. `invoices_of_customer` reads invoices
BARE and `show_invoice` reads them with the subscription, the plan and the customer joined in. One
serialiser over both would either fire two relation loads per row inside the response — the N+1 the
ORM raises `SnakeRelationshipNotLoaded` to stop — or make every caller pay for a plan name it never
reads. So there are two functions, and `test_the_bare_shape_refuses_to_reach_a_relation` is what
keeps the second one from quietly becoming the first.

THE REPORT CARRYING EVERY FIELD IT HAS. `order_report_dict` shipped five of `OrderReport`'s six and
dropped `baskets`, and nothing caught it because a payload gets compared against what somebody
expected rather than against the dataclass that defines it. So the test here asks
`dataclasses.fields` instead of listing keys: a sixth figure added to `BillingReport` fails this
file until it reaches the payload, which is the only version of the check that cannot go stale.

THE DUE DATE ARRIVING ENGINE-SHAPED. `overdue` is the one row in this domain whose date is COMPUTED
rather than stored, so the row mapper has no column declaration to type it with and hands over
whatever the driver gave: a `datetime` on Postgres, ISO-8601 text on SQLite, which has no date type
at all. This suite runs on SQLite, so the text shape is the one measured here — and the serialiser
takes both rather than pretending only one exists, exactly as `billing_viewmodels._day_of` does.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from snakeorm import SnakeSession, SnakeUtc
from snakeorm.core.exceptions import SnakeRelationshipNotLoaded

from shared.dto.billing_dto import (
    billing_report_dict,
    invoice_dict,
    invoice_page_dict,
    invoice_with_parties_dict,
    overdue_dict,
    plan_revenue_dict,
    plan_stats_dict,
)
from shared.models import Invoice, Plan, User
from shared.services.billing_services import PAYMENT_KINDS
from shared.usecases import billing_usecases as usecases

# Every fixture invoice is issued at this instant, so ordering is reproducible and the report's
# ageing has something to be older than.
_WHEN = SnakeUtc(2024, 5, 17, 9, 30)

# A cutoff AFTER every fixture date, which is what makes an unpaid invoice overdue on the report.
_LATER = SnakeUtc(2024, 12, 31, 0, 0)


def _account(session: SnakeSession, *, username: str, plan: str, cents: int) -> int:
    """A user on a plan, subscribed through the use case. Returns the subscription id.

    The `User` and the `Plan` go in directly because this repository has no use case that creates
    either — the same exception `test_billing_viewmodels.py` makes, for the same reason.
    """
    user = session.add(
        User(username=username, email=f"{username}@demo.dev", password_hash="x")
    )
    tariff = session.add(Plan(name=plan, price_cents=cents))
    session.commit()
    return usecases.subscribe(session, user.id, tariff.id).id


def _invoice(session: SnakeSession, subscription_id: int, cents: int) -> Invoice:
    """One invoice raised through the use case, with its date pinned. Comes back BARE."""
    invoice = usecases.issue_invoice(session, subscription_id, cents)
    invoice.issued_at = _WHEN
    session.update(invoice)
    session.commit()
    return invoice


def _pay(session: SnakeSession, invoice: Invoice, cents: int, method: str) -> None:
    """A PARTIAL payment, written directly because `pay_invoice` only settles in full."""
    session.add(
        PAYMENT_KINDS[method](amount_cents=cents, invoice_id=invoice.id, paid_at=_WHEN)
    )
    session.commit()


# ---- The split: a bare invoice and one with its parties --------------------------------------------


def test_the_bare_shape_carries_the_ids_and_touches_no_relation(
    session: SnakeSession,
) -> None:
    """`invoice_dict` serialises an invoice read bare, which is what `invoices_of_customer` returns."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    payload = invoice_dict(usecases.invoices_of_customer(session, 1)[0])

    assert payload == {
        "id": 1,
        "amount_cents": 4200,
        "paid": False,
        "subscription_id": subscription_id,
        "issued_at": _WHEN.isoformat(),
    }


def test_the_bare_shape_refuses_to_reach_a_relation(session: SnakeSession) -> None:
    """Serialising a BARE invoice with the with-parties shape raises instead of firing two queries.

    This is the whole reason the two functions are two. The ORM's anti-N+1 lock is what turns "the
    response quietly costs a query per row" into an error, and the error has to be reachable here —
    otherwise the split is a convention nobody is holding rather than a shape the runtime enforces.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)
    bare = usecases.invoices_of_customer(session, 1)[0]

    with pytest.raises(SnakeRelationshipNotLoaded):
        invoice_with_parties_dict(bare)


def test_the_with_parties_shape_adds_the_chain_on_top_of_the_bare_one(
    session: SnakeSession,
) -> None:
    """`show_invoice` loads subscription, plan and customer, and all three reach the payload.

    The bare keys are still there: the with-parties shape EXTENDS it rather than replacing it, so a
    client that reads a listing and then a detail gets the same names for the same facts.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    raised = _invoice(session, subscription_id, 4200)
    loaded = usecases.show_invoice(session, raised.id)
    assert isinstance(loaded, Invoice)

    payload = invoice_with_parties_dict(loaded)

    assert payload == {
        **invoice_dict(raised),
        "customer_id": 1,
        "customer": "ana",
        "plan_id": 1,
        "plan": "pro",
        "plan_price_cents": 2500,
    }


# ---- The page: the rows and the pager travel together ----------------------------------------------


def test_the_page_carries_the_pager_beside_its_rows(session: SnakeSession) -> None:
    """The four go out as ONE answer, which is what `InvoicePage` exists to keep together.

    A client that has to ask for the total separately is the client that filters the two questions
    differently, and then draws a pager saying 47 over a listing showing a different 47.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    for cents in (1000, 2000, 3000):
        _invoice(session, subscription_id, cents)

    payload = invoice_page_dict(usecases.paginate_invoices(session, per_page=2))

    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["pages"] == 2
    rows = payload["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 2


def test_the_pages_rows_carry_the_parties_the_read_loaded(
    session: SnakeSession,
) -> None:
    """`paginate_invoices` includes the chain, so the page rows are the with-parties shape.

    Which is the other half of the split: this read pays for the joins, so serialising it bare would
    throw away three columns the statement already fetched.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    rows = invoice_page_dict(usecases.paginate_invoices(session))["rows"]

    assert isinstance(rows, list)
    assert rows[0]["customer"] == "ana"
    assert rows[0]["plan"] == "pro"


def test_a_clamped_page_number_is_what_comes_back(session: SnakeSession) -> None:
    """`page=99` over one page of invoices answers page 1, because the number came from a URL."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    payload = invoice_page_dict(usecases.paginate_invoices(session, page=99))

    assert payload["page"] == 1
    assert payload["pages"] == 1


# ---- The report: five fields, and every one of them reaches the payload -----------------------------


def test_the_report_serialises_every_field_the_dataclass_has(
    session: SnakeSession,
) -> None:
    """No figure of `BillingReport` is dropped, asked of the DATACLASS rather than of a key list.

    `order_report_dict` serialises five of `OrderReport`'s six and loses `baskets`, and it went
    unnoticed because every test of it compares the payload against keys somebody typed out. Asking
    `dataclasses.fields` instead means a sixth figure added to the report fails here until it is
    serialised, which is the only version of this test that cannot go stale.

    The names have to match as well as the count: a payload with five keys that renamed one is a
    client reading `None` off a key that moved.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    payload = billing_report_dict(usecases.billing_report(session, _LATER))

    assert set(payload) == {
        field.name for field in dataclasses.fields(usecases.BillingReport)
    }


def test_the_report_counts_the_plans_and_the_money_that_is_open(
    session: SnakeSession,
) -> None:
    """The roll call and the arrears reach the payload as figures rather than as formatted text.

    Cents stay INTEGERS here and the viewmodel is what turns them into `"42.00"`. A JSON client
    formats money for its own locale, and a DTO that decided that for it would be handing over a
    string nobody can add up.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    payload = billing_report_dict(usecases.billing_report(session, _LATER))

    assert payload["unpaid_count"] == 1
    assert payload["unpaid_cents"] == 4200
    assert payload["plans"] == [
        {"id": 1, "name": "pro", "price_cents": 2500, "subscription_count": 1}
    ]


def test_a_plan_that_has_invoiced_reaches_the_revenue_rows(
    session: SnakeSession,
) -> None:
    """The `GROUP BY ... HAVING` row goes out with no id, because it was folded on the plan's NAME."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    payload = billing_report_dict(usecases.billing_report(session, _LATER))

    assert payload["revenue"] == [
        {"plan": "pro", "invoice_count": 1, "revenue_cents": 4200}
    ]


def test_the_overdue_row_carries_the_due_day_and_the_collected_fraction(
    session: SnakeSession,
) -> None:
    """The ageing row goes out with the day it was due and the SHARE of it that has been collected.

    The fraction travels raw — `0.2` and not `"20.0%"` — because it is what the engine computed and
    a percentage is a display decision. The page's view model is where that decision belongs; a
    client reading JSON has its own.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _invoice(session, subscription_id, 5000)
    _pay(session, invoice, 1000, "card")

    payload = billing_report_dict(usecases.billing_report(session, _LATER))

    assert payload["overdue"] == [
        {
            "invoice_id": invoice.id,
            "amount_cents": 5000,
            "due": "2024-06-16",
            "collected": 0.2,
        }
    ]


def test_the_due_day_survives_a_date_that_arrives_as_text(
    session: SnakeSession,
) -> None:
    """A computed date has no column to type it, so `overdue_dict` takes both shapes it can arrive in.

    On Postgres the driver hands back a `datetime`; on SQLite — which has no date type at all, the
    fact `Cap.TIMESTAMPTZ` already declares — it is ISO-8601 text. The demos run on both from one
    `.env`, so a serialiser that called `.isoformat()` would work on one engine and raise on the
    other, inside a response, which is the worst place to find out.
    """
    as_instant = overdue_dict((7, 5000, SnakeUtc(2024, 6, 16, 9, 30), 0.2))
    as_text = overdue_dict((7, 5000, "2024-06-16 09:30:00+00:00", 0.2))

    assert as_instant == as_text
    assert as_instant["due"] == "2024-06-16"


# ---- Nothing here needs a JSON encoder to be taught anything ----------------------------------------


def test_every_payload_is_json_able_as_it_stands(session: SnakeSession) -> None:
    """`json.dumps` takes all five shapes without a custom encoder, which is what a DTO is FOR.

    A value that needs `default=str` to go out is a value that reached the wire undecided: the DTO
    is the layer that decides, once, so the three frameworks do not each decide differently.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _invoice(session, subscription_id, 4200)
    _pay(session, invoice, 1000, "card")
    loaded = usecases.show_invoice(session, invoice.id)
    assert isinstance(loaded, Invoice)

    json.dumps(
        [
            invoice_dict(invoice),
            invoice_with_parties_dict(loaded),
            invoice_page_dict(usecases.paginate_invoices(session)),
            billing_report_dict(usecases.billing_report(session, _LATER)),
            plan_stats_dict(usecases.billing_report(session, _LATER).plans[0]),
            plan_revenue_dict(("pro", 1, 4200)),
        ]
    )
