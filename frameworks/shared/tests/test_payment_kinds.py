"""A payment by card and a payment by transfer are not the same THING, and the table already said so.

`Payment.method` was a `str` holding one of four words, written by hand and read by hand. That is a
discriminator with nobody in charge of it: the column already said which class each row was, and the
ORM did not know, so nothing stopped a `card` row from carrying a transfer's reference — or from
carrying neither, which is what happened, because there was nowhere to put either.

WHAT SINGLE-TABLE INHERITANCE BUYS HERE. One table, one round trip, and the columns that only make
sense for one kind declared on that kind. The alternative everybody writes instead is the flat class
with every column nullable and a comment explaining which ones go together — which is the same table
with the knowledge moved into prose.

THE DISCRIMINATOR IS NOT AN ORDINARY COLUMN. `snake_discriminator()` excludes it from `__init__`:
its value comes from the CLASS, so a `CardPayment` is a `card` and cannot be made to say otherwise.
That is the whole difference from the `str` it replaces — before, the word and the shape of the row
were two independent facts that happened to agree.

AND THE FORM STILL SENDS A STRING. A page posts `method=card`, so something has to turn a word into a
kind. That mapping is in the use case, it is explicit, and an unknown word is a `Failure` rather than
a row of an unknown class: the write refuses at the door instead of storing a fifth kind nobody
declared.
"""

from __future__ import annotations

from snakeorm import SnakeQuery, SnakeSession

from shared.models import CardPayment, Payment, Plan, TransferPayment, User
from shared.usecases import billing_usecases as billing
from shared.usecases.result import Failure


def _invoice_id(session: SnakeSession) -> int:
    """A user on a plan with an invoice raised against it, all through the use cases.

    The `User` and the `Plan` go in directly because this repository has no use case that creates
    either — the same exception `test_billing_viewmodels.py` makes, for the same reason.
    """
    user = session.add(
        User(username="payer", email="payer@demo.dev", password_hash="x")
    )
    plan = session.add(Plan(name="Pro", price_cents=1000))
    session.commit()
    subscription = billing.subscribe(session, user.id, plan.id)
    invoice = billing.issue_invoice(session, subscription.id, 1000)
    session.commit()
    return invoice.id


def test_a_card_payment_is_a_card_payment(session: SnakeSession) -> None:
    """The kind comes from the CLASS, and the row says so without anybody writing the word."""
    payment = billing.pay_invoice(session, _invoice_id(session), "card")

    assert not isinstance(payment, Failure), payment
    assert isinstance(payment, CardPayment)
    assert payment.method == "card"


def test_the_kinds_share_ONE_table(session: SnakeSession) -> None:
    """Single-table inheritance: querying the base returns every kind, in one statement.

    This is the property that makes it worth doing at all. Four tables would mean four queries or a
    union to list the payments of an invoice.
    """
    invoice_id = _invoice_id(session)
    billing.pay_invoice(session, invoice_id, "card")
    billing.pay_invoice(session, invoice_id, "transfer")
    session.commit()

    payments = session.all(SnakeQuery(Payment).filter(Payment.invoice_id == invoice_id))

    assert {type(payment).__name__ for payment in payments} == {
        "CardPayment",
        "TransferPayment",
    }


def test_querying_a_kind_returns_only_that_kind(session: SnakeSession) -> None:
    """A query on the subclass carries the discriminator in its WHERE, which is why it is indexed."""
    invoice_id = _invoice_id(session)
    billing.pay_invoice(session, invoice_id, "card")
    billing.pay_invoice(session, invoice_id, "transfer")
    session.commit()

    cards = session.all(SnakeQuery(CardPayment))

    assert [type(payment).__name__ for payment in cards] == ["CardPayment"]


def test_a_kind_carries_the_columns_that_are_ITS_OWN(session: SnakeSession) -> None:
    """The reference belongs to a transfer. A card has no reference, and cannot be given one."""
    invoice_id = _invoice_id(session)
    payment = billing.pay_invoice(
        session, invoice_id, "transfer", reference="ES91-2100-0418-45"
    )
    session.commit()

    assert not isinstance(payment, Failure), payment
    assert isinstance(payment, TransferPayment)
    assert payment.reference == "ES91-2100-0418-45"


def test_an_unknown_method_is_REFUSED(session: SnakeSession) -> None:
    """A word nobody declared is not a fifth kind: it is a write that does not happen.

    Before, any string went in. The column typed `str` accepted `crypto`, `carrd` and the empty
    string, and the row was stored looking exactly as valid as the others.
    """
    result = billing.pay_invoice(session, _invoice_id(session), "crypto")

    assert isinstance(result, Failure)
    assert result.reason == "unknown_method"
