"""Every invoice a CUSTOMER has, across all their subscriptions, in ONE statement.

The billing selectors could answer "the invoices of a subscription" and nothing above it, so a page
that wanted a customer's invoices had to ask per subscription — a lookup per row, which is invisible
on the two-subscription customer the seed makes and an N+1 on anybody real.

WHY IT BELONGS HERE AND NOT IN THE PAGE. `Invoice.subscription.user_id` is a two-hop navigation, and
the ORM plans both hops as JOINs inside one statement. Doing it in Python means fetching the
subscriptions to get their ids and then fetching invoices by those ids: two round trips that grow,
to answer a question the engine answers in one that does not.

It arrived because the orders operation page needed it: billing an order against an invoice that
ALREADY exists was the last write the API could do and the pages could not, and a form cannot offer
a choice it has no cheap way to list.
"""

from __future__ import annotations

from snakeorm import SnakeSession
from snakeorm.debug import capture_queries

from shared.models import Plan, User
from shared.usecases import billing_usecases as billing


def _customer_with_two_subscriptions(session: SnakeSession) -> tuple[int, int]:
    """A user on two plans, with one invoice against each. Returns `(user_id, other_user_id)`.

    The second customer exists so the filter has something to leave OUT: a selector that returned
    every invoice in the table would pass a test with one customer in it.
    """
    user = session.add(User(username="ana", email="ana@demo.dev", password_hash="x"))
    other = session.add(User(username="bo", email="bo@demo.dev", password_hash="x"))
    basic = session.add(Plan(name="Basic", price_cents=900))
    pro = session.add(Plan(name="Pro", price_cents=2900))
    session.commit()

    for plan in (basic, pro):
        subscription = billing.subscribe(session, user.id, plan.id)
        billing.issue_invoice(session, subscription.id, plan.price_cents)
    stranger = billing.subscribe(session, other.id, basic.id)
    billing.issue_invoice(session, stranger.id, 100)
    session.commit()
    return user.id, other.id


def test_it_returns_the_invoices_of_every_subscription_the_customer_has(
    session: SnakeSession,
) -> None:
    """Two subscriptions, one invoice each, and both come back."""
    user_id, _ = _customer_with_two_subscriptions(session)

    invoices = billing.invoices_of_customer(session, user_id)

    assert sorted(invoice.amount_cents for invoice in invoices) == [900, 2900]


def test_another_customers_invoice_is_NOT_in_it(session: SnakeSession) -> None:
    """The half that a selector returning everything would also pass without."""
    user_id, other_id = _customer_with_two_subscriptions(session)

    mine = billing.invoices_of_customer(session, user_id)
    theirs = billing.invoices_of_customer(session, other_id)

    assert [invoice.amount_cents for invoice in theirs] == [100]
    assert 100 not in [invoice.amount_cents for invoice in mine]


def test_it_is_ONE_statement_however_many_subscriptions(session: SnakeSession) -> None:
    """The point of the two-hop navigation: the count does not grow with the subscriptions.

    Asked per subscription this is one query to list them and one more each — which is the shape
    that made this selector worth writing rather than looping in the page.
    """
    user_id, _ = _customer_with_two_subscriptions(session)

    with capture_queries() as collector:
        billing.invoices_of_customer(session, user_id)

    assert collector.report().count == 1, collector.report().to_text()


def test_a_customer_with_no_subscriptions_gets_an_empty_list(
    session: SnakeSession,
) -> None:
    """An answer, not a failure: a customer who has never subscribed has no invoices."""
    lonely = session.add(User(username="cy", email="cy@demo.dev", password_hash="x"))
    session.commit()

    assert billing.invoices_of_customer(session, lonely.id) == []
