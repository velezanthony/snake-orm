"""BILLING domain: `Plan` (a tariff), `Subscription` (a subscribed `User`), `Invoice` and `Payment`.
A 1—N—N—N chain that gives money queries: revenue per plan (SUM), unpaid invoices (NOT EXISTS of a
payment), invoices per subscription, and so on.

Money is stored in integer CENTS (`*_cents`), not in float nor `Decimal`: exact and portable across
engines. Every date is spread by the seeder over the history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeResult,
    SnakeToMany,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_discriminator,
    snake_int,
    snake_model,
    snake_result,
    snake_str,
    snake_to_many,
    snake_to_one,
)

from shared.models.accounts_models import User

if TYPE_CHECKING:
    # For the TYPE-CHECKER only: `orders` imports this module, so the way back is the linker's.
    from shared.models.orders_models import Order


@snake_model(table="plans")
class Plan(SnakeModel):
    """A tariff. The price is in integer cents: exact and portable (no float, no `Decimal`)."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)
    price_cents: SnakeColumn[int] = snake_int()
    subscriptions: SnakeToMany["Subscription"] = snake_to_many("plan")


@snake_model(table="subscriptions")
class Subscription(SnakeModel):
    """A `User` subscribed to a `Plan`. `active=False` = cancelled. `started_at` is spread by the seeder."""

    id: SnakeColumn[int] = snake_auto()
    active: SnakeColumn[bool] = snake_column(default=True)
    user_id: SnakeColumn[int] = snake_int(index=True)
    user: SnakeToOne[User] = snake_to_one(user_id)
    plan_id: SnakeColumn[int] = snake_int(index=True)
    plan: SnakeToOne[Plan] = snake_to_one(plan_id)
    started_at: SnakeColumn[SnakeUtc] = snake_datetimetz()
    invoices: SnakeToMany["Invoice"] = snake_to_many("subscription")


@snake_model(table="invoices")
class Invoice(SnakeModel):
    """An invoice of a `Subscription` (1—N). `paid` marks it as settled. `issued_at` is spread by the seeder."""

    id: SnakeColumn[int] = snake_auto()
    amount_cents: SnakeColumn[int] = snake_int()
    paid: SnakeColumn[bool] = snake_column(default=False)
    subscription_id: SnakeColumn[int] = snake_int(index=True)
    subscription: SnakeToOne[Subscription] = snake_to_one(subscription_id)
    issued_at: SnakeColumn[SnakeUtc] = snake_datetimetz()
    payments: SnakeToMany["Payment"] = snake_to_many("invoice")
    # The joint with `orders`, from this side. An invoice normally closes one order, but the
    # foreign key lives on the order, so the shape of the inverse is a to-many and saying it is
    # one would be a lie the linker cannot check.
    orders: SnakeToMany["Order"] = snake_to_many("invoice")


@snake_model(table="payments")
class Payment(SnakeModel):
    """A payment against an `Invoice` (1—N: partial payments possible). `paid_at` is spread by the seeder.

    BASE OF A HIERARCHY, in one single table. `method` was a `str` holding one of four words, written
    by hand and read by hand — a discriminator with nobody in charge of it. As a
    `snake_discriminator()` it is excluded from `__init__` and its value comes from the CLASS, so a
    `CardPayment` is a `card` and cannot be made to say otherwise. Before, the word and the shape of
    the row were two independent facts that happened to agree.

    It is indexed because every read of a subclass carries `WHERE method = ...`; without the index
    the whole table gets scanned to find one kind.
    """

    id: SnakeColumn[int] = snake_auto()
    amount_cents: SnakeColumn[int] = snake_int()
    method: SnakeColumn[str] = snake_discriminator()
    invoice_id: SnakeColumn[int] = snake_int(index=True)
    invoice: SnakeToOne[Invoice] = snake_to_one(invoice_id)
    paid_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


@snake_model(discriminator_value="card")
class CardPayment(Payment):
    """Paid by card: the last four digits and the brand, which no other kind has.

    Both are nullable because the columns are PHYSICALLY shared with the other kinds — that is what
    one table means — and a transfer row has nothing to put in them. The nullability is the price of
    the single table; the alternative is a join per read.

    `default=None` on top of the annotation, because they are two different things: the annotation
    makes the COLUMN nullable, the default makes the ARGUMENT optional. A card paid at a terminal
    that does not report its brand is a card payment all the same.
    """

    card_last4: SnakeColumn[str | None] = snake_str(max_length=4, default=None)
    card_brand: SnakeColumn[str | None] = snake_str(max_length=20, default=None)


@snake_model(discriminator_value="transfer")
class TransferPayment(Payment):
    """Paid by bank transfer: the reference the bank gives back, which is how it gets reconciled."""

    reference: SnakeColumn[str | None] = snake_str(max_length=40, default=None)


@snake_model(discriminator_value="paypal")
class PaypalPayment(Payment):
    """Paid through PayPal: the account it came from."""

    paypal_account: SnakeColumn[str | None] = snake_str(max_length=120, default=None)


@snake_model(discriminator_value="wallet")
class WalletPayment(Payment):
    """Paid from the site's own wallet, which carries nothing else.

    A kind with no columns of its own is not a mistake and is worth keeping: it is what makes the set
    of kinds CLOSED. Without it, `wallet` would be the one word the use case had to let through as a
    bare `Payment`, and "any string goes in" would survive in exactly one branch.
    """


@snake_result
class PlanStats(SnakeResult[Plan]):
    """Typed container for `session.annotate()`: the plan + its subscription count."""

    plan: Plan
    subscription_count: int


# The domain's models, in local dependency order for the DDL.
BILLING_MODELS = (Plan, Subscription, Invoice, Payment)
