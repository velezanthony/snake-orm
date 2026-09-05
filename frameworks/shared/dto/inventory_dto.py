"""DTOs for the inventory domain. Flat and JSON-able.

This is where the domain's types stop being Python and become a payload, and it is the only place
that has to decide how. A `Decimal` goes out as a STRING and not as a float: the price is exact in
the database and in Python, and `json.dumps` on a float is precisely where the cent goes missing. A
`UUID`, a `date`, a `time` and a `timedelta` go out in their textual form for the same reason —
readable, sortable, and identical on the three engines.

`bytes` never travels: what goes out is its SIZE. A thumbnail inside a JSON listing is a payload
nobody asked for, and base64 in a list endpoint is how a page ends up weighing megabytes.

A STOCK ROW HAS TWO SHAPES AND THEY ARE TWO FUNCTIONS, the same split `shared/dto/orders_dto.py`
makes for an order and its parties. `stock_dict` serialises the ids, which every row carries because
they ARE its key; `stock_with_relations_dict` also names the warehouse and the SKU, and only a read
that asked for them — `get_stock`, `paginate_stock` — can be handed to it. Folding the two together
would mean reaching for `stock.sku.name` on a row that never loaded it, and `SnakeRelationshipNotLoaded`
raised while a response is being rendered is the worst place to learn which read fed it: the status
line has gone, the transaction is over, and what the client sees is a 500 for a row that exists.
"""

from __future__ import annotations

from shared.models import (
    LowStock,
    Sku,
    Stock,
    StockLedger,
    StockMovement,
    Warehouse,
    WarehouseStats,
)
from shared.usecases.inventory_usecases import StockPage, StockReport


def warehouse_dict(warehouse: Warehouse) -> dict[str, object]:
    """A warehouse as a dict."""
    return {
        "id": warehouse.id,
        "code": warehouse.code,
        "name": warehouse.name,
        "active": warehouse.active,
        "opened_on": warehouse.opened_on.isoformat(),
        "shift_start": warehouse.shift_start.isoformat(),
        # `isoformat()` on a tz-aware time keeps the offset; on the naive one there is
        # nothing to keep, and that difference IS the information.
        "cutoff": warehouse.cutoff.isoformat(),
    }


def sku_dict(sku: Sku) -> dict[str, object]:
    """A SKU as a dict, with the price EXACT and the thumbnail reduced to its size."""
    return {
        "id": sku.id,
        "public_id": str(sku.public_id),
        "name": sku.name,
        "kind": sku.kind.value,
        "price": str(sku.price),
        "weight_kg": sku.weight_kg,
        "lead_time_seconds": sku.lead_time.total_seconds(),
        "thumbnail_bytes": len(sku.thumbnail) if sku.thumbnail else 0,
        "attrs": sku.attrs,
        "related_ids": sku.related_ids,
    }


def stock_dict(stock: Stock) -> dict[str, object]:
    """A stock row as a dict. Its identity is the PAIR, so both halves go out."""
    return {
        "warehouse_id": stock.warehouse_id,
        "sku_id": stock.sku_id,
        "on_hand": stock.on_hand,
        "reserved": stock.reserved,
        "available": stock.on_hand - stock.reserved,
        "counted_at": stock.counted_at.isoformat() if stock.counted_at else None,
        "counted_local": (
            stock.counted_local.isoformat() if stock.counted_local else None
        ),
    }


def stock_with_relations_dict(stock: Stock) -> dict[str, object]:
    """A stock row plus the CODE of its warehouse and the NAME of its SKU. Both must be loaded.

    The ids in `stock_dict` say which pair this is; these two say what it is, and a client that only
    got the ids has to spend two more requests to find out. That is the whole reason the read loads
    them in the same statement.
    """
    return {
        **stock_dict(stock),
        "warehouse": stock.warehouse.code,
        "sku": stock.sku.name,
    }


def movement_dict(movement: StockMovement) -> dict[str, object]:
    """A movement as a dict, carrying the composite key of the stock it moved."""
    return {
        "id": movement.id,
        "warehouse_id": movement.stock_warehouse_id,
        "sku_id": movement.stock_sku_id,
        "delta": movement.delta,
        "reason": movement.reason.value,
        "note": movement.note,
        "happened_at": movement.happened_at.isoformat(),
    }


def warehouse_stats_dict(stats: WarehouseStats) -> dict[str, object]:
    """A warehouse with its aggregates, as a dict."""
    return {
        "warehouse": warehouse_dict(stats.warehouse),
        "sku_count": stats.sku_count,
        "total_units": stats.total_units,
    }


def low_stock_dict(row: LowStock) -> dict[str, object]:
    """A row of the low-stock view. It carries the composite key: the pair is still the identity."""
    return {
        "warehouse_id": row.warehouse_id,
        "sku_id": row.sku_id,
        "on_hand": row.on_hand,
        "reserved": row.reserved,
    }


def ledger_line_dict(line: StockLedger) -> dict[str, object]:
    """A line of the movement book, and it carries NO id ON PURPOSE.

    The ledger view has no primary key and the read defers the one column it inherits, so there is
    nothing here to identify a line by. That is what a book line is: two identical ones are two
    events, and a client that keyed them would have to invent the key.
    """
    return {
        "warehouse_id": line.stock_warehouse_id,
        "sku_id": line.stock_sku_id,
        "delta": line.delta,
        "reason": line.reason.value,
        "note": line.note,
        "happened_at": line.happened_at.isoformat(),
    }


def stock_page_dict(page: StockPage) -> dict[str, object]:
    """A page of stock WITH what the pager needs, travelling with the rows rather than beside them.

    The four go out together because they are ONE answer: a client that asks for the total separately
    is the client that filters the two questions differently, and then draws a pager saying 47 over a
    listing showing a different 47.

    The rows go through `stock_with_relations_dict` because `paginate_stock` loads both hops in the
    same statement. Serialising them bare would throw away the half the extra JOIN was paid for.
    """
    return {
        "rows": [stock_with_relations_dict(row) for row in page.rows],
        "total": page.total,
        "page": page.page,
        "pages": page.pages,
    }


def busy_sku_dict(row: tuple[str, int, int]) -> dict[str, object]:
    """One `GROUP BY ... HAVING COUNT(*) >= n` row: a SKU that moves, how often and by how much.

    `net_delta` is signed and stays signed: a negative one means the SKU has shipped more than it
    received, which is the row worth reading rather than an error to clamp away.
    """
    sku_name, moves, net_delta = row
    return {"sku_name": sku_name, "moves": moves, "net_delta": net_delta}


def ranked_stock_dict(row: tuple[str, str, int, int]) -> dict[str, object]:
    """One window-function row: where a pair ranks inside its OWN warehouse.

    `position` is the figure no `filter` and no `GROUP BY` could put here — it is a fact about the
    row's neighbours, computed without collapsing them — so it travels as its own key rather than
    being left for the client to derive from the order it happened to receive.
    """
    warehouse_code, sku_name, on_hand, position = row
    return {
        "warehouse_code": warehouse_code,
        "sku_name": sku_name,
        "on_hand": on_hand,
        "position": position,
    }


def moved_sku_dict(row: tuple[int, str]) -> dict[str, object]:
    """One SKU that has ever moved: the row a JOIN multiplied and `DISTINCT` folded back."""
    sku_id, sku_name = row
    return {"sku_id": sku_id, "sku_name": sku_name}


def movement_trail_dict(row: tuple[str, int, int, int]) -> dict[str, object]:
    """One recent movement with the two totals that only mean something side by side.

    `running` is what the pair had moved in TOTAL by this row and `moving` what it moved LATELY.
    The accumulated figure only ever rises, so the moving one is the only half that can show a pair
    which has gone quiet — dropping either would leave a number nobody can read.
    """
    sku_name, delta, running, moving = row
    return {
        "sku_name": sku_name,
        "delta": delta,
        "running": running,
        "moving": moving,
    }


def stock_report_dict(report: StockReport) -> dict[str, object]:
    """The whole inventory report as one payload: SIX reads, six keys, and the count is the check.

    Six and six is asserted next door rather than trusted, because the failure mode here is silent.
    `order_report_dict` in `shared/dto/orders_dto.py` shipped five of `OrderReport`'s six fields and
    dropped `baskets` — the payload was well-formed, every key in it was right, and the only way to
    notice was to hold the dataclass against the dict. A field added to `StockReport` and forgotten
    here would read exactly the same way: an answer that is complete except for the part nobody
    asked about. That one is fixed, and `test_a_report_payload_carries_every_figure.py` makes the
    count over every report DTO here so that noticing stops depending on somebody looking.

    `total_skus` is here and not derived from `len(moved_skus)` for the reason the use case gives:
    how many SKUs have NEVER moved is the ratio a replenishment meeting starts from, and the moved
    list alone cannot answer it.
    """
    return {
        "warehouses": [warehouse_stats_dict(row) for row in report.warehouses],
        "busy_skus": [busy_sku_dict(row) for row in report.busy_skus],
        "ranking": [ranked_stock_dict(row) for row in report.ranking],
        "moved_skus": [moved_sku_dict(row) for row in report.moved_skus],
        "total_skus": report.total_skus,
        "trail": [movement_trail_dict(row) for row in report.trail],
    }
