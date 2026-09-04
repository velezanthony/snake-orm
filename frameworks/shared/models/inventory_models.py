"""INVENTORY domain: warehouses, SKUs, per-warehouse stock and the movements that change it.

This domain exists for two things the other seven never exercised, and both only show up when
something actually writes and reads them.

The first is the COMPOSITE key, and here it is the natural modelling rather than an exercise. Stock
is identified by (warehouse, sku): there is no second row for the same pair, so a surrogate id would
be the artificial choice. From it hangs `StockMovement`, whose foreign key therefore has TWO columns
— which is the shape the select-in batches by, dividing its placeholder budget by the number of
columns in the key. Until this domain existed, nothing outside a unit test had a key wider than one.

The second is the TYPES. Between them, the seven older domains declared `int`, `str` and `SnakeUtc`
and nothing else. A warehouse with prices, weights, images, opening dates and per-SKU attributes
needs `Decimal`, `float`, `bytes`, `dict`, `UUID`, `date`, `time`, `bool`, `timedelta`, `list[int]`
and an enum — and several of those are DEGRADED outside Postgres (a `list` travels as JSON text on
MySQL and SQLite, an `INTERVAL` as text), so exercising them here is also what proves the ORM's own
warning path is telling the truth.

`Timestamped` is an abstract base with no table of its own: `created_at` is declared once and
inherited, which is the piece that puts column inheritance on a real path too.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from snakeorm import (
    SnakeColumn,
    SnakeQuery,
    SnakeIndex,
    SnakeModel,
    SnakeResult,
    SnakeServerDefault,
    SnakeToMany,
    SnakeToOne,
    SnakeUtc,
    SnakeView,
    snake_abstract,
    snake_auto,
    snake_check,
    snake_checks,
    snake_column,
    snake_datetime,
    snake_datetimetz,
    snake_decimal,
    snake_enum,
    snake_float,
    snake_indexes,
    snake_int,
    snake_json,
    snake_model,
    snake_result,
    snake_str,
    snake_time,
    snake_timetz,
    snake_to_many,
    snake_to_one,
    snake_view,
)

if TYPE_CHECKING:
    # For the TYPE-CHECKER only: `orders` imports this module, so the way back is the linker's.
    from shared.models.orders_models import Order


class SkuKind(StrEnum):
    """What a SKU is, which decides whether it takes up room in a warehouse."""

    PHYSICAL = "physical"
    DIGITAL = "digital"
    SERVICE = "service"


class MovementReason(StrEnum):
    """Why the stock moved. It is what turns a delta into something auditable."""

    PURCHASE = "purchase"
    SALE = "sale"
    RETURN = "return"
    ADJUSTMENT = "adjustment"


SHOP_REASONS: tuple[MovementReason, ...] = (
    MovementReason.SALE,
    MovementReason.RETURN,
)
"""What the SHOP writes into the movements: `ship` takes units out, a customer sends them back."""

FLOOR_REASONS: tuple[MovementReason, ...] = (
    MovementReason.PURCHASE,
    MovementReason.ADJUSTMENT,
)
"""What the FLOOR writes: `receive` puts a delivery away, a physical count corrects the shelf.

The two tuples PARTITION the enum, and they live here rather than in a query because "who wrote this
line" is vocabulary and not a filter. The book selects by them, the page names the origin from them,
and two spellings of that split is how one layer starts calling a return a floor movement.
"""

BOOK_SIZE = 10
"""How many lines of EACH origin the movement book prints. Per origin, which is the shape of the page.

A constant of the BOOK and not of one query: the selector bounds each branch by it, the use case
defaults to it and the page says it out loud in its heading, and three literals is how the heading
ends up promising a number the query does not deliver.
"""


@snake_abstract
class Timestamped(SnakeModel):
    """Abstract base with no table: it lends `created_at` to whoever inherits it.

    The value is put in by the SERVER, so it is not part of `__init__`: nobody passes a creation
    date by hand, and being able to is how two rows written in the same second end up disagreeing.
    """

    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )


@snake_model(table="warehouses")
class Warehouse(Timestamped):
    """A physical warehouse. `code` is FIXED-width on purpose: it is a three-letter code, not a name."""

    SnakeComment = "Physical warehouses that hold stock"

    id: SnakeColumn[int] = snake_auto()
    code: SnakeColumn[str] = snake_str(max_length=3, fixed=True, unique=True)
    name: SnakeColumn[str] = snake_str(max_length=80)
    active: SnakeColumn[bool] = snake_column(default=True)
    opened_on: SnakeColumn[date] = snake_column()
    shift_start: SnakeColumn[time] = snake_time()
    # The daily cutoff carries its OFFSET, and the shift start does not: the shift opens at 06:30
    # wherever you are, while the cutoff is one moment for everybody and has to say which.
    cutoff: SnakeColumn[time] = snake_timetz()
    stock: SnakeToMany[Stock] = snake_to_many("warehouse")
    # The warehouse's order book: the inverse of `Order.warehouse`. It is what the operations
    # of the orders domain read before they lock anything.
    orders: SnakeToMany["Order"] = snake_to_many("warehouse")


@snake_model(table="skus")
class Sku(Timestamped):
    """Something that can be stocked. It carries the types the rest of the domain never declared."""

    SnakeComment = "Catalogue of stockable items"

    id: SnakeColumn[int] = snake_auto()
    # Filled in by Python on building, one per instance: it is the id that travels outside, so it
    # must not be the sequential one the database hands out.
    public_id: SnakeColumn[UUID] = snake_column(default_factory=uuid4)
    name: SnakeColumn[str] = snake_str(max_length=120)
    kind: SnakeColumn[SkuKind] = snake_enum(SkuKind, default=SkuKind.PHYSICAL)
    price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
    # Four bytes is plenty for a weight in kilos, and it says so: the ceiling is a declared rule.
    weight_kg: SnakeColumn[float] = snake_float(size=4)
    lead_time: SnakeColumn[timedelta] = snake_column()
    thumbnail: SnakeColumn[bytes | None] = snake_column(default=None)
    attrs: SnakeColumn[dict[str, object]] = snake_json()
    related_ids: SnakeColumn[list[int]] = snake_column()
    stock: SnakeToMany[Stock] = snake_to_many("sku")


@snake_model(table="warehouse_stock")
class Stock(SnakeModel):
    """How much of a SKU sits in a warehouse. COMPOSITE PK `(warehouse_id, sku_id)`.

    There is no surrogate id and there should not be: the pair IS the identity, and a second row for
    the same pair is not a thing that can mean anything. `reserved` is what is already promised to an
    order; `quantity` is what is physically there.
    """

    SnakeComment = "Stock of one SKU in one warehouse"

    warehouse_id: SnakeColumn[int] = snake_int(primary_key=True)
    sku_id: SnakeColumn[int] = snake_int(primary_key=True)
    warehouse: SnakeToOne[Warehouse] = snake_to_one(warehouse_id)
    sku: SnakeToOne[Sku] = snake_to_one(sku_id)
    # `on_hand`, not `quantity`, and the rename is the point rather than taste. With `reserved` next
    # to it, "quantity" does not say whether the reserved units are inside it or not — and the
    # `LowStock` view made that ambiguity operational the day it started asking about what is
    # AVAILABLE. Warehouse vocabulary has three words for three numbers: on hand, reserved, and
    # available = on hand - reserved.
    on_hand: SnakeColumn[int] = snake_int()
    reserved: SnakeColumn[int] = snake_int(default=0)
    # Nullable is not the same as optional in `__init__`: the ORM still asks for it, and there is
    # no `default=` on a datetime declarator on purpose — a literal one would freeze at import time.
    # So whoever writes the row says `counted_at=None`, which is the ORM's stance: say what you mean.
    counted_at: SnakeColumn[SnakeUtc | None] = snake_datetimetz()
    # The same count, twice, and on purpose: `counted_at` is the INSTANT (TIMESTAMPTZ) and
    # `counted_local` is what the clock on that warehouse's wall read (TIMESTAMP, no zone). They are
    # not redundant — an audit is reconciled against the local paper form, and the instant is what
    # orders two counts done in different countries.
    #
    # Nothing else in the demos declared a naive `datetime`, which is the type whose confusion with
    # `SnakeUtc` once left twelve of twenty tables saying TIMESTAMP while the models said
    # TIMESTAMPTZ. Having both side by side is what makes that difference visible instead of
    # theoretical.
    counted_local: SnakeColumn[datetime | None] = snake_datetime()
    movements: SnakeToMany[StockMovement] = snake_to_many("stock")


@snake_model(table="stock_movements")
class StockMovement(SnakeModel):
    """A change of stock, with its reason. COMPOSITE FK towards `Stock`'s composite PK.

    The two columns pair up POSITIONALLY against `(warehouse_id, sku_id)`, in that order. This is the
    relationship that makes an `include(Stock.movements)` bind two placeholders per parent instead of
    one, which is exactly what the select-in's batching divides by.
    """

    id: SnakeColumn[int] = snake_auto()
    stock_warehouse_id: SnakeColumn[int] = snake_int()
    stock_sku_id: SnakeColumn[int] = snake_int()
    stock: SnakeToOne[Stock] = snake_to_one(stock_warehouse_id, stock_sku_id)
    delta: SnakeColumn[int] = snake_int()
    reason: SnakeColumn[MovementReason] = snake_enum(
        MovementReason, default=MovementReason.ADJUSTMENT
    )
    note: SnakeColumn[str | None] = snake_str(max_length=200, default=None)
    happened_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )

    SnakeIndexes = [SnakeIndex(stock_warehouse_id, stock_sku_id)]


@snake_view(query=SnakeQuery(StockMovement), name="stock_ledger")
class StockLedger(SnakeView):
    """READ-ONLY view: the movements read as a BOOK. It has NO primary key, and that is the point.

    A TABLE ROW IS AN ENTITY AND A LEDGER LINE IS A FACT, and the ORM will not let one be the other.
    `only()`/`defer()` over `stock_movements` always bring `id` back — a row that can be written has
    to keep its identity — so every projection of that table is unique by construction and two
    receipts of one unit can never be the same answer twice. A view is read-only, so it has no
    identity to preserve: `defer(StockLedger.id)` is accepted here and refused on the table, and
    what comes back is the LINE the book prints.

    That difference is what makes the book's `union_all` the only correct operator instead of a
    cheaper spelling of `union`. Two identical lines are two events — the same SKU leaving the same
    warehouse twice in the same second is two orders, not one printed twice — and a `UNION` would
    fold them into one line and leave the book disagreeing with the stock by a unit.
    """

    id: SnakeColumn[int] = snake_int()
    stock_warehouse_id: SnakeColumn[int] = snake_int()
    stock_sku_id: SnakeColumn[int] = snake_int()
    delta: SnakeColumn[int] = snake_int()
    reason: SnakeColumn[MovementReason] = snake_enum(MovementReason)
    note: SnakeColumn[str | None] = snake_str(max_length=200)
    happened_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


@snake_result
class WarehouseStats(SnakeResult[Warehouse]):
    """Typed container for `session.annotate()`: a warehouse and what it holds."""

    warehouse: Warehouse
    sku_count: int
    total_units: int


# Outside the class body: inside it `quantity` is still the raw descriptor and does not know its
# name. Negative stock is not a state to be recovered from later, it is a write that should not have
# happened, and the engine is the only place that holds under concurrency.
snake_checks(
    Stock,
    snake_check(Stock.on_hand >= 0, name="ck_warehouse_stock_on_hand_not_negative"),
    snake_check(Stock.reserved >= 0, name="ck_warehouse_stock_reserved_not_negative"),
)

# PARTIAL index: only the ACTIVE warehouses are ever looked up by code, and a closed warehouse stays
# in the table for the history of its movements. Indexing it too would pay for rows nobody queries.
snake_indexes(
    Warehouse,
    SnakeIndex(
        Warehouse.code,
        name="ix_warehouses_active_code",
        where=Warehouse.active == True,  # noqa: E712 - a SQL condition, not a Python truth test
    ),
)


# The domain's models, in local dependency order for the DDL.
INVENTORY_MODELS = (Warehouse, Sku, Stock, StockMovement)


# The threshold is INLINED, because a view takes no parameters: it is part of the object that lives
# in the database, not of the call. `query=` and not `sql=` on purpose — the demos run on three
# engines, and a hand-written SELECT would freeze one engine's quoting into a model that is supposed
# to be engine-agnostic.
#
# IT ASKS ABOUT WHAT IS AVAILABLE, AND IT USED TO ASK ABOUT WHAT IS ON THE SHELF. `on_hand < 10`
# flagged a pair holding nine units and nothing reserved, and stayed silent about one holding fifty
# of which forty-five are promised — five available, and a replenishment dashboard never heard of it.
# The right question is `on_hand - reserved`, and it could not be WRITTEN until the ORM learned to
# compare a column against a column: before that the right-hand side was always a literal, and the
# view had to settle for the question it could express.
@snake_view(
    query=SnakeQuery(Stock).filter(Stock.on_hand - Stock.reserved < 10),
    name="low_stock",
)
class LowStock(SnakeView):
    """READ-ONLY view: the pairs running out. What a replenishment dashboard reads.

    It is queried like any model and REFUSES to be written to — `session.add/update/delete` reject it,
    and the checker refuses first. That is the point of having one here: a read model that cannot be
    written to by accident is a different guarantee from a query that happens not to write.

    It projects `Stock` whole, so it carries the composite key too: the pair is still the identity.
    """

    warehouse_id: SnakeColumn[int] = snake_int()
    sku_id: SnakeColumn[int] = snake_int()
    on_hand: SnakeColumn[int] = snake_int()
    reserved: SnakeColumn[int] = snake_int()
    counted_at: SnakeColumn[SnakeUtc | None] = snake_datetimetz()
    counted_local: SnakeColumn[datetime | None] = snake_datetime()


# The VIEWS, apart from the tables: they are created LAST (they depend on the tables existing) and
# dropped FIRST, and `DROP TABLE` is not what removes one.
INVENTORY_VIEWS = (LowStock, StockLedger)
