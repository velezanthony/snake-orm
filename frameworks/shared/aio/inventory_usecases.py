"""inventory domain (warehouses, SKUs, stock and its movements), asked of an `AsyncSession`.

The twin of `shared/usecases/inventory_usecases.py`. Same names, same parameters, same answers —
including the same `Failure` reasons — because a reason is what the user reads and two wordings of
one refusal is the drift this package's nets exist to catch. What differs is one keyword per
statement.

The queries are NOT rebuilt here: every read goes through the fragments in
`shared/selectors/inventory_selectors.py`, unchanged, because a `SnakeQuery` has no colour. That
matters more in this domain than in `accounts`/`taxonomy`: the COMPOSITE key means a stock row's
identity is `(warehouse_id, sku_id)`, both halves, and a WHERE that quietly dropped one of them on
one side and not the other would return the right row today and the wrong one the day a warehouse
gets a second SKU. Sharing the fragment is what makes that impossible rather than merely unlikely.

`StockPage` and `StockReport` are imported from the synchronous module rather than redefined: they
are plain dataclasses, not queries, so there is nothing colour-specific about them and a second
definition would be a second place for the two to drift apart.

`stream_movements` is the one function here that is `async def` for a reason OTHER than awaiting
something of its own. `AsyncSession.iterate()` is not itself a coroutine — it returns the async
iterator immediately, the same way the synchronous `iterate()` returns a plain iterator — so this
function's body has nothing to await. It is still declared `async def` because
`test_async_mirror.py` demands every function in this package be a coroutine, and rightly so: a
plain `def` here would be indistinguishable from an accident until somebody forgot to notice this
one export never blocks. The cost lands on the caller, who now writes `async for m in await
stream_movements(session):` instead of the synchronous `for m in stream_movements(session):` — an
`await` that exists to satisfy the net rather than to wait on anything.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, time, timedelta
from decimal import Decimal

from snakeorm import AsyncSession

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
from shared.usecases.inventory_usecases import StockPage, StockReport
from shared.usecases.result import Failure


async def list_warehouses(
    session: AsyncSession, *, active_only: bool = False
) -> list[Warehouse]:
    """Every warehouse, or only the open ones."""
    return await session.all(selectors.warehouses(active_only=active_only))


async def get_warehouse(
    session: AsyncSession, warehouse_id: int
) -> Warehouse | Failure:
    """One warehouse; `not_found` if it does not exist."""
    warehouse = await session.first(selectors.warehouse_by_id(warehouse_id))
    return warehouse if warehouse is not None else Failure("not_found")


async def list_skus(session: AsyncSession) -> list[Sku]:
    """Every SKU."""
    return await session.all(selectors.all_skus())


async def warehouse_stats(session: AsyncSession) -> list[WarehouseStats]:
    """Every warehouse with its aggregates, in one statement."""
    return await session.annotate(
        selectors.warehouses(),
        WarehouseStats,
        sku_count=selectors.warehouse_sku_count(),
        total_units=selectors.warehouse_total_units(),
    )


async def paginate_stock(
    session: AsyncSession,
    *,
    warehouse_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> StockPage:
    """A page of stock, optionally narrowed to one warehouse. TWO statements, whatever the size.

    Both statements filter through `stock_listing`, the same fragment the synchronous pager counts
    and fetches with: a pager that filtered the two differently would say "47 rows" over a listing
    that shows a different 47, which is exactly the bug the shared fragment rules out.
    """
    per_page = max(1, per_page)
    total = await session.count(selectors.stock_listing(warehouse_id))
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = await session.all(
        selectors.stock_listing(warehouse_id)
        .include(Stock.warehouse, Stock.sku)
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    return StockPage(rows=rows, total=total, page=page, pages=pages)


async def get_stock(
    session: AsyncSession, warehouse_id: int, sku_id: int
) -> Stock | Failure:
    """One stock pair with its warehouse and its SKU loaded; `not_found` if the pair holds nothing."""
    stock = await session.first(
        selectors.stock_pair_with_relations(warehouse_id, sku_id)
    )
    return stock if stock is not None else Failure("not_found")


async def count_movements(session: AsyncSession, warehouse_id: int, sku_id: int) -> int:
    """How many movements hang off a pair. No `Failure`: a pair with no history has none, and so
    has a pair that does not exist."""
    return await session.count(selectors.stock_movements(warehouse_id, sku_id))


async def stock_history(
    session: AsyncSession, warehouse_id: int, sku_id: int
) -> list[StockMovement]:
    """The movements of a pair, most recent first, WITHOUT checking that the pair exists."""
    return await session.all(
        selectors.stock_movements(warehouse_id, sku_id).order_by(
            StockMovement.happened_at.desc()
        )
    )


async def update_stock(
    session: AsyncSession,
    *,
    warehouse_id: int,
    sku_id: int,
    on_hand: int,
    reserved: int,
) -> Stock | Failure:
    """Corrects the levels of an EXISTING pair. `not_found` if it is not there, and it is not created."""
    if on_hand < 0 or reserved < 0:
        return Failure("missing_fields")
    stock = await session.first(selectors.stock_pair(warehouse_id, sku_id))
    if stock is None:
        return Failure("not_found")
    stock.on_hand = on_hand
    stock.reserved = reserved
    await session.update(stock)
    await session.commit()
    return stock


async def remove_stock(
    session: AsyncSession, *, warehouse_id: int, sku_id: int
) -> None | Failure:
    """Deletes a stock pair. `not_found` if it is not there, `conflict` if its history would be orphaned."""
    stock = await session.first(selectors.stock_pair(warehouse_id, sku_id))
    if stock is None:
        return Failure("not_found")
    if await session.count(selectors.stock_movements(warehouse_id, sku_id)) > 0:
        return Failure("conflict")
    await session.delete(stock)
    await session.commit()
    return None


async def stock_of_warehouse(
    session: AsyncSession, warehouse_id: int
) -> list[Stock] | Failure:
    """A warehouse's stock with the SKU loaded; `not_found` if the warehouse does not exist."""
    if await session.first(selectors.warehouse_by_id(warehouse_id)) is None:
        return Failure("not_found")
    return await session.all(selectors.warehouse_stock(warehouse_id))


async def stock_with_movements(
    session: AsyncSession, warehouse_id: int
) -> list[Stock] | Failure:
    """A warehouse's stock with each row's movements: the to-many over a COMPOSITE key."""
    if await session.first(selectors.warehouse_by_id(warehouse_id)) is None:
        return Failure("not_found")
    return await session.all(selectors.warehouse_stock_with_movements(warehouse_id))


async def movements_of(
    session: AsyncSession, warehouse_id: int, sku_id: int
) -> list[StockMovement] | Failure:
    """The movements of one stock row; `not_found` if that pair holds nothing."""
    if await session.first(selectors.stock_pair(warehouse_id, sku_id)) is None:
        return Failure("not_found")
    return await session.all(
        selectors.stock_movements(warehouse_id, sku_id).order_by(
            StockMovement.happened_at.desc()
        )
    )


async def create_warehouse(
    session: AsyncSession,
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
    warehouse = await session.add(
        Warehouse(
            code=code,
            name=name,
            opened_on=opened_on,
            shift_start=shift_start,
            cutoff=cutoff,
        )
    )
    await session.commit()
    return warehouse


async def create_sku(
    session: AsyncSession,
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
    sku = await session.add(
        Sku(
            name=name,
            kind=kind,
            price=price,
            weight_kg=weight_kg,
            lead_time=lead_time,
            attrs=attrs or {},
            related_ids=related_ids or [],
            thumbnail=thumbnail,
        )
    )
    await session.commit()
    return sku


async def receive(
    session: AsyncSession, *, warehouse_id: int, sku_id: int, units: int
) -> Stock | Failure:
    """Receives goods into a pair, creating the stock row if it was not there.

    `missing_fields` if the amount is not positive: receiving zero is not an operation, and a
    negative one is a shipment written the wrong way round.
    """
    if units <= 0:
        return Failure("missing_fields")
    if await session.first(selectors.warehouse_by_id(warehouse_id)) is None:
        return Failure("not_found")
    if await session.first(selectors.sku_by_id(sku_id)) is None:
        return Failure("not_found")

    stock = await session.first(selectors.stock_pair(warehouse_id, sku_id))
    if stock is None:
        await session.upsert(
            Stock(
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                on_hand=0,
                counted_at=None,
                counted_local=None,
            ),
            on_conflict=[Stock.warehouse_id, Stock.sku_id],
            update=[Stock.on_hand],
        )
        await session.commit()
        stock = await session.first(selectors.stock_pair(warehouse_id, sku_id))
        assert stock is not None
    stock.on_hand = stock.on_hand + units
    await session.update(stock)
    await session.add(
        StockMovement(
            stock_warehouse_id=stock.warehouse_id,
            stock_sku_id=stock.sku_id,
            delta=units,
            reason=MovementReason.PURCHASE,
            note=None,
        )
    )
    await session.commit()
    return stock


async def ship(
    session: AsyncSession, *, warehouse_id: int, sku_id: int, units: int
) -> Stock | Failure:
    """Ships goods out of a pair. `conflict` if there are not that many.

    The rule is checked HERE and also lives in the database as a CHECK. That is not a duplicate: the
    CHECK is what holds under two concurrent writers, and this is what can tell the caller how many
    there actually were. Refusing before writing means there is nothing to undo.
    """
    if units <= 0:
        return Failure("missing_fields")
    stock = await session.first(selectors.stock_pair(warehouse_id, sku_id))
    if stock is None:
        return Failure("not_found")
    if stock.on_hand < units:
        return Failure("conflict")
    stock.on_hand = stock.on_hand - units
    await session.update(stock)
    await session.add(
        StockMovement(
            stock_warehouse_id=stock.warehouse_id,
            stock_sku_id=stock.sku_id,
            delta=-units,
            reason=MovementReason.SALE,
            note=None,
        )
    )
    await session.commit()
    return stock


async def count_stock(
    session: AsyncSession, *, warehouse_id: int, sku_id: int, on_hand: int
) -> None | Failure:
    """Sets the stock of a pair after a physical count. UPSERT: it does not care if the row existed."""
    if on_hand < 0:
        return Failure("missing_fields")
    await session.upsert(
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
    await session.commit()
    return None


async def reserve(
    session: AsyncSession, *, warehouse_id: int, units: int
) -> int | Failure:
    """Reserves units across a warehouse's whole stock in ONE statement. Returns the rows touched."""
    if units <= 0:
        return Failure("missing_fields")
    touched = await session.update_where(
        selectors.stock_in_warehouse(warehouse_id),
        [(Stock.reserved, Stock.reserved + units)],
    )
    await session.commit()
    return touched


async def low_stock(session: AsyncSession) -> list[LowStock]:
    """The pairs running out, from the read-only view. No `Failure`: an empty warehouse is an answer."""
    return await session.all(selectors.low_stock_pairs())


async def movement_book(
    session: AsyncSession, *, size: int = BOOK_SIZE
) -> list[StockLedger]:
    """The movement book: the last `size` lines of EACH origin, from the read-only ledger.

    The capability question is asked on THIS side too, and not delegated: the branches keep their own
    bounds, so the compound is only emittable where the engine takes parentheses around them.
    """
    if session.dialect.supports_parenthesised_compound:
        return await session.all(selectors.book_compound(size))
    shop, floor = selectors.book_branches(size)
    return selectors.fold_book(await session.all(shop), await session.all(floor))


async def stock_report(
    session: AsyncSession, *, minimum_moves: int = 2, ranking_size: int = 50
) -> StockReport:
    """The whole inventory report: SIX statements, and not one of them depends on the row count.

    The six `await`s below run in the SAME order as the synchronous `StockReport(...)` call: Python
    evaluates a dataclass's keyword arguments left to right, so the order the fields are WRITTEN in
    `shared/usecases/inventory_usecases.py` is the order the statements fire in, and
    `test_both_colours_emit_the_same_sql` compares them position by position. Building the five
    answers as local variables first and handing them to `StockReport(...)` afterwards would still
    run every statement, but in whatever order this function happened to compute them — invisible to
    the reader and exactly the kind of drift the shared fragments elsewhere in this module exist to
    rule out.
    """
    warehouses = await session.annotate(
        selectors.warehouses(),
        WarehouseStats,
        sku_count=selectors.warehouse_sku_count(),
        total_units=selectors.warehouse_total_units(),
    )
    busy_rows = await session.select(
        selectors.busy_sku_movements(minimum_moves), *selectors.busy_sku_columns()
    )
    ranking_rows = await session.select(
        selectors.ranked_stock(ranking_size), *selectors.ranked_stock_columns()
    )
    moved_rows = await session.select(
        selectors.moved_stock(), *selectors.moved_sku_columns()
    )
    total_skus = await session.count(selectors.all_skus())
    trail_rows = await session.select(
        selectors.movement_trail(), *selectors.movement_trail_columns()
    )
    return StockReport(
        warehouses=warehouses,
        busy_skus=[(name, int(moves), int(net or 0)) for name, moves, net in busy_rows],
        ranking=[
            (code, name, int(on_hand), int(position))
            for code, name, on_hand, position in ranking_rows
        ],
        moved_skus=[(int(sku_id), name) for sku_id, name in moved_rows],
        total_skus=total_skus,
        trail=[
            (name, int(delta), int(running or 0), int(moving or 0))
            for name, delta, running, moving in trail_rows
        ],
    )


async def stream_movements(
    session: AsyncSession, *, warehouse_id: int | None = None
) -> AsyncIterator[StockMovement]:
    """The movements as a STREAM, for the export.

    `async def` for the net, not for a `await` this body needs: `AsyncSession.iterate()` hands back
    the async iterator immediately, exactly as the synchronous `iterate()` hands back a plain one. See
    the module docstring for why the signature is still a coroutine and what that costs the caller.
    """
    return session.iterate(
        selectors.movements_to_export(warehouse_id), chunk=selectors.EXPORT_CHUNK
    )
