"""billing domain — SERVICES: subscribe/cancel, issue an invoice and collect it.

`pay_invoice` is the compound operation: it creates the `Payment` AND marks the invoice paid (two
writes in the same unit of work). Every framework re-exports them from `apps/billing/services.py`.
"""

from __future__ import annotations


from snakeorm import SnakeUtc, SnakeSession

from shared.models import (
    CardPayment,
    Invoice,
    Payment,
    PaypalPayment,
    Subscription,
    TransferPayment,
    WalletPayment,
)
from shared.selectors.billing_selectors import invoice_by_id, subscription_by_id


def subscribe(session: SnakeSession, user_id: int, plan_id: int) -> Subscription:
    """Subscribes a user to a plan (active, starting now)."""
    return session.add(
        Subscription(user_id=user_id, plan_id=plan_id, started_at=SnakeUtc.now())
    )


def cancel_subscription(session: SnakeSession, subscription_id: int) -> bool:
    """Cancels a subscription (marks it inactive). `False` if it does not exist.

    The look-up goes through the `subscription_by_id` fragment rather than an inline query, so that
    the asynchronous twin cancels the row it found with the SAME `WHERE` and not with a second one
    that happens to look alike today.
    """
    subscription = session.first(subscription_by_id(subscription_id))
    if subscription is None:
        return False
    subscription.active = False
    session.update(subscription)
    return True


def issue_invoice(
    session: SnakeSession, subscription_id: int, amount_cents: int
) -> Invoice:
    """Issues an (unpaid) invoice against a subscription."""
    return session.add(
        Invoice(
            amount_cents=amount_cents,
            subscription_id=subscription_id,
            issued_at=SnakeUtc.now(),
        )
    )


# The four kinds a payment can be, by the word a form sends. It is a mapping and not a chain of
# `if`s so that the set is CLOSED and readable in one line: a word that is not a key here is not a
# payment, and the caller is the one that decides what to do about it.
PAYMENT_KINDS: dict[str, type[Payment]] = {
    "card": CardPayment,
    "transfer": TransferPayment,
    "paypal": PaypalPayment,
    "wallet": WalletPayment,
}


def pay_invoice(
    session: SnakeSession, invoice_id: int, method: str, **details: str
) -> Payment | None:
    """Collects an invoice: creates the `Payment` and marks the invoice paid. `None` if it does not exist.

    The look-up goes through the `invoice_by_id` fragment for the same reason `cancel_subscription`'s
    does: collecting an invoice is "find it, add the payment, mark it paid", and the asynchronous twin
    has to find it with the very same `WHERE`.

    The KIND comes from the word, and the word is not written into the row: `method` is the
    discriminator, so it is the class that carries it. `details` are the columns of that kind — a
    card's last four digits, a transfer's reference — and they belong to the kind that declares them.
    """
    kind = PAYMENT_KINDS.get(method)
    if kind is None:
        return None
    invoice = session.first(invoice_by_id(invoice_id))
    if invoice is None:
        return None
    payment = session.add(
        kind(
            amount_cents=invoice.amount_cents,
            invoice_id=invoice_id,
            paid_at=SnakeUtc.now(),
            **details,
        )
    )
    invoice.paid = True
    session.update(invoice)
    return payment
