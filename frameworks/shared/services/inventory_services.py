"""inventory domain — SERVICES: writes over warehouses, SKUs, stock and movements.

Every framework re-exports them from `apps/inventory/services.py`.

Two writes here are shapes the other domains never needed. `set_stock` is an UPSERT over a COMPOSITE
conflict target: receiving goods must not care whether that (warehouse, sku) pair already existed,
and doing it as read-then-branch is a race with two writers. `receive` and `ship` write the stock row
and its movement TOGETHER, which is the case a transaction exists for — the ORM does not roll back
on its own, so the caller commits once and both land or neither does.

Services do not commit. That is the use case's decision, because it is the one that knows whether the
operation is finished.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from snakeorm import SnakeQuery, SnakeSession

from shared.models import (
    MovementReason,
    Sku,
    SkuKind,
    Stock,
    StockMovement,
    Warehouse,
)
from shared.selectors.inventory_selectors import stock_in_warehouse


def create_warehouse(
    session: SnakeSession,
    *,
    code: str,
    name: str,
    opened_on: object,
    shift_start: object,
    cutoff: object,
) -> Warehouse:
    """Creates a warehouse. `created_at` is put in by the server, so it is not passed."""
    return session.add(
        Warehouse(
            code=code,
            name=name,
            opened_on=opened_on,  # type: ignore[arg-type]
            shift_start=shift_start,  # type: ignore[arg-type]
            cutoff=cutoff,  # type: ignore[arg-type]
        )
    )


def close_warehouse(session: SnakeSession, warehouse: Warehouse) -> Warehouse:
    """Closes a warehouse without deleting it: its movements are the history and stay."""
    warehouse.active = False
    session.update(warehouse)
    return warehouse


def create_sku(
    session: SnakeSession,
    *,
    name: str,
    kind: SkuKind,
    price: Decimal,
    weight_kg: float,
    lead_time: timedelta,
    attrs: dict,
    related_ids: list[int],
    thumbnail: bytes | None = None,
) -> Sku:
    """Creates a SKU. `public_id` is filled in by its `default_factory`, one per instance."""
    return session.add(
        Sku(
            name=name,
            kind=kind,
            price=price,
            weight_kg=weight_kg,
            lead_time=lead_time,
            attrs=attrs,
            related_ids=related_ids,
            thumbnail=thumbnail,
        )
    )


def create_skus(session: SnakeSession, skus: list[Sku]) -> None:
    """Inserts a batch of SKUs in one go. It slices by the engine's placeholder ceiling."""
    session.add_all(skus)


def set_stock(
    session: SnakeSession, *, warehouse_id: int, sku_id: int, on_hand: int
) -> None:
    """Sets the stock of a pair, whether or not the row existed. UPSERT over the COMPOSITE PK.

    The conflict target is BOTH columns, because the pair is the identity. Reading first and then
    deciding between insert and update is the same operation with a window in the middle, and two
    receivings of the same SKU land inside that window.
    """
    session.upsert(
        Stock(
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            on_hand=on_hand,
            counted_at=None,
            counted_local=None,
        ),
        on_conflict=[Stock.warehouse_id, Stock.sku_id],
        update=[Stock.on_hand],
    )


def set_stock_levels(
    session: SnakeSession, *, stock: Stock, on_hand: int, reserved: int
) -> Stock:
    """Writes both levels of an EXISTING pair at once: what the edit form submits.

    Deliberately not `set_stock`, and the two are not variants of one thing. `set_stock` is an upsert
    that does not care whether the row was there, so it can only carry what an insert can carry;
    this one edits a row somebody is looking at, so it writes `reserved` too — and it takes the
    instance rather than the pair because the caller has already loaded it to show it.

    It records no movement, and that is the honest part: a correction after an audit is not a
    reason stock moved, it is somebody saying the number was wrong. `move_stock` is for the other
    case, and conflating them would put fictional purchases in the audit trail.
    """
    stock.on_hand = on_hand
    stock.reserved = reserved
    session.update(stock)
    return stock


def move_stock(
    session: SnakeSession,
    *,
    stock: Stock,
    delta: int,
    reason: MovementReason,
    note: str | None = None,
) -> StockMovement:
    """Applies a delta to a stock row and records WHY, as one unit of work.

    The row and its movement are written together on purpose: a on_hand that changed with no
    movement behind it is stock nobody can explain, and this is the ORM's answer to that — one
    transaction, committed by the caller.
    """
    stock.on_hand = stock.on_hand + delta
    session.update(stock)
    return session.add(
        StockMovement(
            stock_warehouse_id=stock.warehouse_id,
            stock_sku_id=stock.sku_id,
            delta=delta,
            reason=reason,
            note=note,
        )
    )


def hold_units(session: SnakeSession, *, stock: Stock, units: int) -> Stock:
    """Promises `units` of an already-loaded pair to an order. It touches `reserved`, never `on_hand`.

    The two columns are not two ways of saying the same thing. `on_hand` is what is on the shelf and
    only a MOVEMENT changes it, because a change with no movement behind it is stock nobody can
    explain. `reserved` is what is already spoken for, and promising units moves nothing physical —
    the shelf still holds them, the warehouse's own count is still right, and what changed is how
    many of them anybody else may still have.

    No movement is written, and that is the same rule read the other way: nothing moved.
    """
    stock.reserved = stock.reserved + units
    session.update(stock)
    return stock


def release_units(session: SnakeSession, *, stock: Stock, units: int) -> Stock:
    """Un-promises `units`: the hold goes away and the shelf is untouched. The inverse of `hold_units`.

    It is what a cancellation and a failed settlement both need. A release that forgot to happen is
    the most expensive kind of bug in an inventory precisely because it is invisible: `on_hand` stays
    right, the shelf stays full, and the warehouse simply starts refusing orders it could fill.
    """
    stock.reserved = stock.reserved - units
    session.update(stock)
    return stock


def ship_held(session: SnakeSession, *, stock: Stock, units: int) -> StockMovement:
    """Turns a promise into a shipment: BOTH columns drop, and the movement says why.

    This is the write `settle` makes, and it has to be all three things at once. `on_hand` falls
    because the units left the building; `reserved` falls because they are no longer merely promised;
    and the `SALE` movement is written because that is the only reason the count is allowed to change.
    Dropping one column and not the other is the classic half-shipment — either the warehouse count
    stays high for ever, or the same units get promised again tomorrow — and neither half fails on
    its own, which is what makes them one write rather than two.

    The caller commits. Landing the shipment without the movement, or the movement without the
    shipment, are both states no reader can interpret.
    """
    stock.on_hand = stock.on_hand - units
    stock.reserved = stock.reserved - units
    session.update(stock)
    return session.add(
        StockMovement(
            stock_warehouse_id=stock.warehouse_id,
            stock_sku_id=stock.sku_id,
            delta=-units,
            reason=MovementReason.SALE,
            note=None,
        )
    )


def reserve_units(session: SnakeSession, *, warehouse_id: int, units: int) -> int:
    """Reserves `units` across every stock row of a warehouse. ONE statement, no instances.

    A bulk write: it neither loads the rows nor fires signals, and it says so. The arithmetic
    (`col = col + n`) travels to the engine, which is what makes it safe against another writer.

    The WHERE comes from `stock_in_warehouse`, NOT `stock_listing`: a bulk UPDATE rejects a query
    carrying an ORDER BY outright, and `stock_listing` always carries one.
    """
    return session.update_where(
        stock_in_warehouse(warehouse_id),
        [(Stock.reserved, Stock.reserved + units)],
    )


def delete_stock(session: SnakeSession, stock: Stock) -> None:
    """Deletes a stock row by its composite key.

    It only works on a pair with NO movements, and that is the engine holding the line rather than a
    gap here: the movements are the audit trail, and a foreign key that let them be orphaned — or
    cascaded away — would turn "remove this row" into "erase why the numbers ever changed". A pair
    that has moved gets closed, not deleted.
    """
    session.delete(stock)


def sku_by_public_id(session: SnakeSession, public_id: UUID) -> Sku | None:
    """A SKU by the id that travels outside. Proves the UUID goes out and comes back as a UUID."""
    return session.first(SnakeQuery(Sku).filter(Sku.public_id == public_id))
