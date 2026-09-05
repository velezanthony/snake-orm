"""inventory domain use cases (warehouses, SKUs, stock and its movements), written once.

The three frameworks re-export these; none of them holds a line of this logic. What lives here is
the part that is the same everywhere: validate the input, call the services, decide when it is
finished and commit ONCE.

`ship` is the one that earns the layer. Shipping is a read, a rule and two writes, and the rule is
that stock does not go negative. The engine holds that too —there is a CHECK— but the CHECK gives
back a driver error, and what a caller needs is to be told there were only four left. The ORM does
not roll back on its own, so if the rule does not hold nothing is written and there is nothing to
undo.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal

from snakeorm import SnakeQuery, SnakeSession

from shared.models import (
    BOOK_SIZE,
    LowStock,
    MovementReason,
    Sku,
    SkuKind,
    Stock,
    StockLedger,
    StockMovement,
    Warehouse,
    WarehouseStats,
)
from shared.selectors import inventory_selectors as selectors
from shared.services import inventory_services as services
from shared.usecases.result import Failure


def list_warehouses(
    session: SnakeSession, *, active_only: bool = False
) -> list[Warehouse]:
    """Every warehouse, or only the open ones."""
    return selectors.list_warehouses(session, active_only=active_only)


def get_warehouse(session: SnakeSession, warehouse_id: int) -> Warehouse | Failure:
    """One warehouse; `not_found` if it does not exist."""
    warehouse = selectors.get_warehouse(session, warehouse_id)
    return warehouse if warehouse is not None else Failure("not_found")


def list_skus(session: SnakeSession) -> list[Sku]:
    """Every SKU."""
    return selectors.list_skus(session)


def warehouse_stats(session: SnakeSession) -> list[WarehouseStats]:
    """Every warehouse with its aggregates, in one statement."""
    return selectors.warehouse_stats(session)


@dataclass(frozen=True, slots=True)
class StockPage:
    """One page of stock rows together with everything the pager needs to draw itself.

    The four travel together because they are ONE answer. Handing back only the rows makes the caller
    ask for the total separately, and the caller that asks separately is the one that filters the two
    questions differently — a pager reading "47 rows" over a listing that shows a different 47.

    `page` is the CLAMPED page and not the one that was asked for, which is the whole reason it comes
    back at all: the number arrives from a URL, so it is whatever somebody typed there, and the
    caller has to be able to tell the template which page it is really looking at.
    """

    rows: list[Stock]
    total: int
    page: int
    pages: int


def paginate_stock(
    session: SnakeSession,
    *,
    warehouse_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> StockPage:
    """A page of stock, optionally narrowed to one warehouse. TWO statements, whatever the size.

    The arithmetic lives here and not in the presentation layer, because it is not presentation: how
    many pages there are depends on how many rows there are, and only this layer knows that. Both
    numbers get clamped —`per_page` to at least one, `page` into the range that exists— since both
    arrive from a URL: `per_page=0` is a division by zero and `page=99` is a stale bookmark, and
    neither should be a stack trace.

    An unknown `warehouse_id` gives an EMPTY page rather than `Failure("not_found")`, on purpose. A
    filter is a filter: answering "nothing matches" is correct, and probing that the warehouse exists
    would add a third statement to every listing to catch a case only a hand-edited URL produces.
    """
    per_page = max(1, per_page)
    total = selectors.count_stock_rows(session, warehouse_id=warehouse_id)
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = selectors.stock_rows_page(
        session,
        warehouse_id=warehouse_id,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return StockPage(rows=rows, total=total, page=page, pages=pages)


def get_stock(session: SnakeSession, warehouse_id: int, sku_id: int) -> Stock | Failure:
    """One stock pair with its warehouse and its SKU loaded; `not_found` if the pair holds nothing.

    Both halves of the key are required and neither has a default. That is not ceremony: with one
    warehouse in the database a lookup that quietly dropped `warehouse_id` returns the right row, and
    the demo only breaks once there are two — which is to say, in front of somebody.
    """
    stock = selectors.get_stock_with_relations(session, warehouse_id, sku_id)
    return stock if stock is not None else Failure("not_found")


def count_movements(session: SnakeSession, warehouse_id: int, sku_id: int) -> int:
    """How many movements hang off a pair. No `Failure`: a pair with no history has none, and so
    has a pair that does not exist.

    The caller that needs the difference —the delete confirmation— has already asked for the row and
    already got its `not_found`. Asking again here would be a second statement to learn something
    the caller knows.
    """
    return selectors.count_movements_of(session, warehouse_id, sku_id)


def stock_history(
    session: SnakeSession, warehouse_id: int, sku_id: int
) -> list[StockMovement]:
    """The movements of a pair, most recent first, WITHOUT checking that the pair exists.

    The sibling `movements_of` below does check, and both are wanted. An endpoint asked for a pair by
    URL and has to answer 404; a detail page has already fetched the row —that is what it is showing—
    so repeating the lookup here would be a third statement on every visit to learn what the caller
    already knows. Same query, different question about who has already asked.
    """
    return selectors.movements_of(session, warehouse_id, sku_id)


def update_stock(
    session: SnakeSession,
    *,
    warehouse_id: int,
    sku_id: int,
    on_hand: int,
    reserved: int,
) -> Stock | Failure:
    """Corrects the levels of an EXISTING pair. `not_found` if it is not there, and it is not created.

    The difference from `count_stock` further down is deliberate: that one is an upsert, so it means
    "this pair now holds N whether or not it existed". This one edits a row somebody opened, and a
    pair that vanished between the form being drawn and being submitted is a 404, not a silent
    insert of a row nobody asked to create.

    Negative levels are refused HERE as well as by the engine's CHECK. The CHECK is what holds under
    two writers; this is what can answer the form with something other than a driver error.
    """
    if on_hand < 0 or reserved < 0:
        return Failure("missing_fields")
    stock = selectors.get_stock(session, warehouse_id, sku_id)
    if stock is None:
        return Failure("not_found")
    services.set_stock_levels(session, stock=stock, on_hand=on_hand, reserved=reserved)
    session.commit()
    return stock


def remove_stock(
    session: SnakeSession, *, warehouse_id: int, sku_id: int
) -> None | Failure:
    """Deletes a stock pair. `not_found` if it is not there, `conflict` if its history would be orphaned.

    The refusal is the interesting half. The movements are the audit trail and the foreign key is
    RESTRICT, so the engine would refuse anyway — with a driver error, from inside a commit, three
    layers below the page that asked. Checking first turns that into a `conflict` the delete page can
    explain, and it is exactly the FK-restrict-versus-cascade path the page taxonomy exists to
    exercise: a pair that has moved gets closed, not deleted.
    """
    stock = selectors.get_stock(session, warehouse_id, sku_id)
    if stock is None:
        return Failure("not_found")
    if selectors.count_movements_of(session, warehouse_id, sku_id) > 0:
        return Failure("conflict")
    services.delete_stock(session, stock)
    session.commit()
    return None


def stock_of_warehouse(
    session: SnakeSession, warehouse_id: int
) -> list[Stock] | Failure:
    """A warehouse's stock with the SKU loaded; `not_found` if the warehouse does not exist."""
    if selectors.get_warehouse(session, warehouse_id) is None:
        return Failure("not_found")
    return selectors.stock_of_warehouse(session, warehouse_id)


def stock_with_movements(
    session: SnakeSession, warehouse_id: int
) -> list[Stock] | Failure:
    """A warehouse's stock with each row's movements: the to-many over a COMPOSITE key."""
    if selectors.get_warehouse(session, warehouse_id) is None:
        return Failure("not_found")
    return selectors.stock_with_movements(session, warehouse_id)


def movements_of(
    session: SnakeSession, warehouse_id: int, sku_id: int
) -> list[StockMovement] | Failure:
    """The movements of one stock row; `not_found` if that pair holds nothing."""
    if selectors.get_stock(session, warehouse_id, sku_id) is None:
        return Failure("not_found")
    return selectors.movements_of(session, warehouse_id, sku_id)


def create_warehouse(
    session: SnakeSession,
    *,
    code: str,
    name: str,
    opened_on: date,
    shift_start: time,
    cutoff: time,
) -> Warehouse | Failure:
    """Creates a warehouse; `missing_fields` if the code or the name come in empty."""
    if not code or not name:
        return Failure("missing_fields")
    warehouse = services.create_warehouse(
        session,
        code=code,
        name=name,
        opened_on=opened_on,
        shift_start=shift_start,
        cutoff=cutoff,
    )
    session.commit()
    return warehouse


def create_sku(
    session: SnakeSession,
    *,
    name: str,
    kind: SkuKind,
    price: Decimal,
    weight_kg: float,
    lead_time: timedelta,
    attrs: dict | None = None,
    related_ids: list[int] | None = None,
    thumbnail: bytes | None = None,
) -> Sku | Failure:
    """Creates a SKU; `missing_fields` if the name is empty or the price is not positive."""
    if not name or price <= Decimal("0"):
        return Failure("missing_fields")
    sku = services.create_sku(
        session,
        name=name,
        kind=kind,
        price=price,
        weight_kg=weight_kg,
        lead_time=lead_time,
        attrs=attrs or {},
        related_ids=related_ids or [],
        thumbnail=thumbnail,
    )
    session.commit()
    return sku


def receive(
    session: SnakeSession, *, warehouse_id: int, sku_id: int, units: int
) -> Stock | Failure:
    """Receives goods into a pair, creating the stock row if it was not there.

    `missing_fields` if the amount is not positive: receiving zero is not an operation, and a
    negative one is a shipment written the wrong way round.
    """
    if units <= 0:
        return Failure("missing_fields")
    if selectors.get_warehouse(session, warehouse_id) is None:
        return Failure("not_found")
    if selectors.get_sku(session, sku_id) is None:
        return Failure("not_found")

    stock = selectors.get_stock(session, warehouse_id, sku_id)
    if stock is None:
        services.set_stock(session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=0)
        session.commit()
        stock = selectors.get_stock(session, warehouse_id, sku_id)
        assert stock is not None
    services.move_stock(
        session, stock=stock, delta=units, reason=MovementReason.PURCHASE
    )
    session.commit()
    return stock


def ship(
    session: SnakeSession, *, warehouse_id: int, sku_id: int, units: int
) -> Stock | Failure:
    """Ships goods out of a pair. `conflict` if there are not that many.

    The rule is checked HERE and also lives in the database as a CHECK. That is not a duplicate: the
    CHECK is what holds under two concurrent writers, and this is what can tell the caller how many
    there actually were. Refusing before writing means there is nothing to undo.
    """
    if units <= 0:
        return Failure("missing_fields")
    stock = selectors.get_stock(session, warehouse_id, sku_id)
    if stock is None:
        return Failure("not_found")
    if stock.on_hand < units:
        return Failure("conflict")
    services.move_stock(session, stock=stock, delta=-units, reason=MovementReason.SALE)
    session.commit()
    return stock


def count_stock(
    session: SnakeSession, *, warehouse_id: int, sku_id: int, on_hand: int
) -> None | Failure:
    """Sets the stock of a pair after a physical count. UPSERT: it does not care if the row existed."""
    if on_hand < 0:
        return Failure("missing_fields")
    services.set_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=on_hand
    )
    session.commit()
    return None


def reserve(session: SnakeSession, *, warehouse_id: int, units: int) -> int | Failure:
    """Reserves units across a warehouse's whole stock in ONE statement. Returns the rows touched."""
    if units <= 0:
        return Failure("missing_fields")
    touched = services.reserve_units(session, warehouse_id=warehouse_id, units=units)
    session.commit()
    return touched


def low_stock(session: SnakeSession) -> list[LowStock]:
    """The pairs running out, from the read-only view. No `Failure`: an empty warehouse is an answer."""
    return selectors.low_stock(session)


def movement_book(session: SnakeSession, *, size: int = BOOK_SIZE) -> list[StockLedger]:
    """The movement book: the last `size` lines of EACH origin, from the read-only ledger.

    No `Failure`: a warehouse that has moved nothing is an answer, and an empty book says so.
    """
    return selectors.movement_book(session, size=size)


@dataclass(frozen=True, slots=True)
class StockReport:
    """The four answers the inventory report is made of, gathered into one value.

    They travel together because they are read together: "nine of the ten SKUs have moved, four of
    them often, and here is where each sits in its warehouse" is one sentence, and a caller that
    fetched the four halves separately is a caller that can fetch three of them and forget the
    fourth. It is a frozen dataclass and not a dict because the view model above it has to be able to
    fail to compile when a figure is added or renamed.

    Each field is one statement and each uses a different part of the ORM, which is the report's
    other job: `warehouses` is `annotate`, `busy_skus` is `GROUP BY` + `HAVING`, `ranking` is a
    window function, and `moved_skus` is an explicit JOIN folded back with `DISTINCT`.
    """

    warehouses: list[WarehouseStats]
    busy_skus: list[tuple[str, int, int]]
    ranking: list[tuple[str, str, int, int]]
    moved_skus: list[tuple[int, str]]
    total_skus: int
    # The recent movements, each carrying what its pair had moved in TOTAL and what it moved
    # LATELY. Two figures from one statement, and they are on the page together because apart
    # neither of them says anything: the accumulated number always rises, so only the moving one
    # can show a pair that has gone quiet.
    trail: list[tuple[str, int, int, int]]


def stock_report(
    session: SnakeSession, *, minimum_moves: int = 2, ranking_size: int = 50
) -> StockReport:
    """The whole inventory report: SIX statements, and not one of them depends on the row count.

    Five is the number the budget test pins, and every one of them is named in `StockReport` above
    except the last: `total_skus` is a `COUNT` and it is here rather than derived from `moved_skus`
    because the interesting figure is the ratio — how many SKUs have NEVER moved is the question a
    replenishment meeting starts from, and `len(moved_skus)` alone cannot answer it.

    `minimum_moves` and `ranking_size` are parameters and not constants, because both are the sort of
    number a page ends up wanting from a query string, and a threshold buried in a selector is a
    threshold that gets copied into the second demo with a different value.
    """
    return StockReport(
        warehouses=selectors.warehouse_stats(session),
        busy_skus=selectors.busy_skus(session, minimum_moves=minimum_moves),
        ranking=selectors.stock_ranking(session, limit=ranking_size),
        moved_skus=selectors.skus_that_have_moved(session),
        total_skus=session.count(SnakeQuery(Sku)),
        trail=selectors.movement_trail_rows(session),
    )


def stream_movements(
    session: SnakeSession, *, warehouse_id: int | None = None
) -> Iterator[StockMovement]:
    """The movements as a STREAM, for the export. `return`, never `yield`, all the way down.

    The whole layer stack from here to the driver has to keep that discipline, and this is the level
    where it is easiest to break: a use case is where somebody would naturally add a `for` loop to
    filter or count something, and the first `yield` written here turns the export back into
    something that runs lazily as a whole rather than streaming a row at a time. If a rule ever has
    to be applied per row, it belongs in the query.

    No `Failure` and no existence check on the warehouse. A filter that matches nothing is an answer
    — an empty CSV — and probing that the warehouse exists would be a statement spent on a case only
    a hand-edited URL produces, which is the same call `paginate_stock` makes above.
    """
    return selectors.stream_movements(session, warehouse_id=warehouse_id)
