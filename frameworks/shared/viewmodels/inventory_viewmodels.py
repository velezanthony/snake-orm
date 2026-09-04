"""inventory view models: the pages of the pilot domain, flat and framework-free.

The count is left out of that first line on purpose. It read "the five pages" while the domain had
grown to eight, which is the same drift the report's own docstring is careful about: a number written
in prose ages exactly like a number written in a table, and neither of them has a test.

`inventory` is the pilot of the page taxonomy and the page entity is `Stock`, which is the whole
point of choosing it. Stock is identified by the PAIR `(warehouse_id, sku_id)`, so the key travels in
the URL in two halves, comes back through a form in two halves, and is what a redirect has to carry
in two halves. Every one of those is a place where a demo can lose one half and still look right —
with a single warehouse in the database, half the key finds the row — so the pilot exercises the
composite key everywhere rather than mentioning it once.

Everything here obeys the same four rules:

- a function takes a `SnakeSession` and plain parameters, and calls `inventory_usecases`. Never a
  selector, never the session directly: the use case is the seam, and a view model that reaches past
  it is a second place where "what this page means" is decided;
- it returns a `TypedDict`, so the template's keys are checked rather than hoped for;
- it hands back a `Failure` UNCHANGED when the use case fails. Mapping `not_found` to a 404 is the
  web layer's job and it differs per framework; deciding it here would put a status code in a module
  that must not know what HTTP is;
- every value is presentation-ready and primitive. Dates and timestamps come out as ISO strings,
  `Decimal` as text with its two decimals, a null as `""`. A template cannot round a number or format
  a date without deciding it — and two templates deciding it separately is exactly the drift this
  layer was added to stop.

THE ONE EXCEPTION TO "A PAGE IS A FLAT DICT" IS THE EXPORT, and it has to be argued rather than
noticed. `CsvExport` carries a GENERATOR of rows, not a list of dicts, because the page type exists
to exercise `session.iterate()` — a read that walks a result without ever holding it whole. A view
model that collected that stream into a list would return the same characters in the same order and
would have thrown away the only thing the page was for; nothing would fail, which is why
`tests/test_exports_stream.py` measures the number of rows the CURSOR consumed rather than the number
that came out. Every cell is still a `str`, so the rule that formatting happens here and not in the
renderer survives the exception: what changes is WHEN the rows exist, not what they are made of.

The one formatting call worth arguing about is money, and the argument is why the DTO next door does
it differently. `shared/dto/inventory_dto.py` emits `str(price)` because JSON is read by a machine
and has to be exact; a page is read by a person and has to be legible, so here it is `.2f`. Same
value, two audiences, two answers — declared in both places instead of guessed in the template.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing_extensions import TypedDict

from snakeorm import SnakeSession

from shared.models import (
    BOOK_SIZE,
    LowStock,
    SHOP_REASONS,
    Sku,
    Stock,
    StockLedger,
    StockMovement,
    Warehouse,
    WarehouseStats,
)
from shared.usecases import inventory_usecases as usecases
from shared.usecases.result import Failure


@dataclass(frozen=True, slots=True)
class CsvExport:
    """A CSV as the web layer needs it: a name, a header, and rows that DO NOT EXIST YET.

    `rows` is typed a `Generator` and not an `Iterator`, and the difference is `close()`. A download
    that the browser abandons half way has to be able to tear the cursor down, and a plain iterator
    has no way to say so — the connection would stay held until the object was collected. The web
    layers of all three demos wrap the response in something that closes it; typing the field as what
    it really is means they can.

    `header` is separate from the rows rather than being the first of them, for two reasons that both
    turned out to matter: a caller can write the header before the first row arrives, which is what
    makes the download start instantly on a big table; and a test can check the columns WITHOUT
    consuming the stream, which is the one thing consuming it would make impossible to check twice.

    `filename` lives here and not in the three demos because a file called `export.csv` in one demo
    and `stock.csv` in another is exactly the drift this layer was added to stop, one storey down.
    """

    filename: str
    header: tuple[str, ...]
    rows: Generator[tuple[str, ...], None, None]


class WarehouseOption(TypedDict):
    """A warehouse as a `<select>` option: the id it posts back and the two words it shows."""

    id: int
    code: str
    name: str


class SkuOption(TypedDict):
    """A SKU as a `<select>` option. The price rides along because a picker that shows it is useful."""

    id: int
    name: str
    kind: str
    price: str


class StockRow(TypedDict):
    """One line of the stock listing, with both to-one hops ALREADY made.

    `warehouse_code`, `warehouse_name`, `sku_name` and `sku_kind` are the flattened relations, and
    they are flattened for the reason this layer exists: reading them off the model in a template is
    a relation load in the renderer. `available` is flattened for a smaller reason that bites just as
    often — `on_hand - reserved` is one subtraction, and two templates write it two ways.

    Both halves of the composite key travel, because the template has to build a link back to this
    row and neither half alone identifies it.
    """

    warehouse_id: int
    sku_id: int
    warehouse_code: str
    warehouse_name: str
    sku_name: str
    sku_kind: str
    on_hand: int
    reserved: int
    available: int
    counted_at: str


class MovementRow(TypedDict):
    """One movement of a stock row: what changed, why, and when.

    `note` is nullable in the model and a `str` here, empty when there is none. That is not tidying:
    `None` in a Jinja or Django template prints the word "None" into the page.
    """

    id: int
    delta: int
    reason: str
    note: str
    happened_at: str


class StockListPage(TypedDict):
    """The listing plus its pager and its filter, which is everything the page needs to redraw itself.

    `warehouse_id` comes back so the template can mark the selected option; `prev_page`/`next_page`
    come back already computed so the template never does arithmetic on a page number.
    """

    rows: list[StockRow]
    warehouses: list[WarehouseOption]
    warehouse_id: int | None
    page: int
    pages: int
    total: int
    has_prev: bool
    has_next: bool
    prev_page: int
    next_page: int


class WarehouseCatalogueRow(TypedDict):
    """One warehouse as a ROW of the catalogue, which is more than it is as an option.

    `WarehouseOption` above is what a `<select>` needs — an id and two words. A row is read rather
    than picked, so it also carries when the warehouse opened and whether it still is one. They are
    two shapes because they answer two questions, and folding them into one would put a date in
    every dropdown that never shows it.

    `active` travels as a boolean rather than as a label because a template wants to branch on it,
    and a boolean is a better thing to branch on than a string somebody might translate.
    """

    id: int
    code: str
    name: str
    active: bool
    opened_on: str


class InventoryCataloguePage(TypedDict):
    """What the inventory is made OF, as against what is IN it.

    Every other page in this domain is about a stock pair. This one is about the two things a pair
    POINTS AT, and it exists because neither could be brought into being from a page: the demo could
    only ever stock what the seeder had made.

    TWO statements, and neither grows with the rows. It deliberately does NOT say how much each
    warehouse holds — that is an aggregate per row, which is the report's job and the report answers
    it in one statement. Asking it here would be the N+1 the reporting page exists to not be.
    """

    warehouses: list[WarehouseCatalogueRow]
    skus: list[SkuOption]


class StockDetailPage(TypedDict):
    """One pair in full: the row, the two to-one singletons it points at, and its to-many.

    The three fields hanging outside `stock` are the values only the detail shows —the SKU's exact
    price and public id, the warehouse's opening date— and they are here rather than in `StockRow`
    because a listing of thirty rows should not carry thirty of each.
    """

    stock: StockRow
    sku_price: str
    sku_public_id: str
    warehouse_opened_on: str
    movements: list[MovementRow]


class StockFormPage(TypedDict):
    """What `create` and `update` both need, which is why it is ONE shape and one function.

    The two pages differ by exactly one thing —whether there is a row already— and `is_update` is
    that thing said out loud. Two shapes would be two templates that have to agree on the option
    lists, which is the duplication this layer exists to stop, one page down.
    """

    warehouses: list[WarehouseOption]
    skus: list[SkuOption]
    stock: StockRow | None
    is_update: bool


class StockDeletePage(TypedDict):
    """The confirmation, and what a delete would take with it.

    `movement_count` is the page's whole reason to exist. The foreign key from the movements is
    RESTRICT, so a pair with history CANNOT be deleted, and a confirmation that does not say so is a
    button that fails after being pressed. This is the FK-restrict-versus-cascade path of the page
    taxonomy, shown to the person about to trip over it.
    """

    stock: StockRow
    movement_count: int


def _warehouse_option(warehouse: Warehouse) -> WarehouseOption:
    """A warehouse flattened into an option."""
    return {"id": warehouse.id, "code": warehouse.code, "name": warehouse.name}


def _sku_option(sku: Sku) -> SkuOption:
    """A SKU flattened into an option, price included and already formatted."""
    return {
        "id": sku.id,
        "name": sku.name,
        "kind": sku.kind.value,
        "price": f"{sku.price:.2f}",
    }


def _stock_row(stock: Stock) -> StockRow:
    """A stock row flattened, doing the two to-one hops the template must not do.

    It REQUIRES the row to arrive with `warehouse` and `sku` loaded, which every use case that feeds
    it does with a single `include`. Reading them off a plain row would work and would cost two
    queries per line — the exact N+1 this layer was put in front of, just moved one file over.
    """
    return {
        "warehouse_id": stock.warehouse_id,
        "sku_id": stock.sku_id,
        "warehouse_code": stock.warehouse.code,
        "warehouse_name": stock.warehouse.name,
        "sku_name": stock.sku.name,
        "sku_kind": stock.sku.kind.value,
        "on_hand": stock.on_hand,
        "reserved": stock.reserved,
        "available": stock.on_hand - stock.reserved,
        "counted_at": stock.counted_at.isoformat() if stock.counted_at else "",
    }


def _movement_row(movement: StockMovement) -> MovementRow:
    """A movement flattened: the enum as its value, the timestamp as ISO, the null note as empty."""
    return {
        "id": movement.id,
        "delta": movement.delta,
        "reason": movement.reason.value,
        "note": movement.note or "",
        "happened_at": movement.happened_at.isoformat(),
    }


def stock_list(
    session: SnakeSession,
    *,
    warehouse_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> StockListPage:
    """The stock listing: a real page of rows, its pager, and the warehouses to filter by.

    THREE statements, always: the count, the page of rows, and the warehouses of the filter. Not one
    of the three depends on how many rows come back, which is what makes this page's cost flat — and
    what the budget test asserts by building the same page at two sizes rather than against a
    literal.

    It never returns a `Failure`. An unknown `warehouse_id` narrows to nothing and the page says
    zero, because a filter that matches nothing is an answer; turning it into a 404 would cost a
    fourth statement on every visit to catch a case only a hand-edited URL produces.
    """
    result = usecases.paginate_stock(
        session, warehouse_id=warehouse_id, page=page, per_page=per_page
    )
    warehouses = usecases.list_warehouses(session)
    return {
        "rows": [_stock_row(stock) for stock in result.rows],
        "warehouses": [_warehouse_option(w) for w in warehouses],
        "warehouse_id": warehouse_id,
        "page": result.page,
        "pages": result.pages,
        "total": result.total,
        "has_prev": result.page > 1,
        "has_next": result.page < result.pages,
        # Clamped rather than `page ± 1`: on the edges the template would otherwise be handed a page
        # number that does not exist and asked to remember not to link it.
        "prev_page": max(1, result.page - 1),
        "next_page": min(result.pages, result.page + 1),
    }


def _warehouse_catalogue_row(warehouse: Warehouse) -> WarehouseCatalogueRow:
    """A warehouse flattened for the catalogue: the date turned into ISO, the rest already primitive."""
    return {
        "id": warehouse.id,
        "code": warehouse.code,
        "name": warehouse.name,
        "active": warehouse.active,
        "opened_on": warehouse.opened_on.isoformat(),
    }


def inventory_catalogue(session: SnakeSession) -> InventoryCataloguePage:
    """The warehouses and the SKUs the inventory is made of. TWO statements.

    It cannot fail. An empty catalogue is a page of zero rows and not a 404, which is the state the
    page matters most in: it is where the first warehouse and the first SKU get made.
    """
    return {
        "warehouses": [
            _warehouse_catalogue_row(warehouse)
            for warehouse in usecases.list_warehouses(session)
        ],
        "skus": [_sku_option(sku) for sku in usecases.list_skus(session)],
    }


def stock_detail(
    session: SnakeSession, warehouse_id: int, sku_id: int
) -> StockDetailPage | Failure:
    """One pair: its row, its two to-one relations and its movements. TWO statements.

    Both halves of the key are required positionally and neither has a default, which is what makes
    the round trip through the URL testable: a caller that lost one half cannot compile a call here.
    """
    stock = usecases.get_stock(session, warehouse_id, sku_id)
    if isinstance(stock, Failure):
        return stock
    movements = usecases.stock_history(session, warehouse_id, sku_id)
    return {
        "stock": _stock_row(stock),
        "sku_price": f"{stock.sku.price:.2f}",
        "sku_public_id": str(stock.sku.public_id),
        "warehouse_opened_on": stock.warehouse.opened_on.isoformat(),
        "movements": [_movement_row(movement) for movement in movements],
    }


def stock_form(
    session: SnakeSession,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
) -> StockFormPage | Failure:
    """The form for `create` and for `update`: same options, with or without a row already in it.

    A pair is an update only when BOTH halves arrive. Half a key identifies nothing, so it falls back
    to creating rather than guessing which row was meant — and that is not a hypothetical: a form
    that posts back one half of a composite key is exactly how this domain breaks, and answering it
    with "here is a blank create form" is a visible failure instead of a silent edit of the wrong
    row.

    When both arrive and the pair is not there, it is a `Failure("not_found")`: somebody is editing a
    row that has been deleted since the link was made.
    """
    stock: Stock | None = None
    is_update = warehouse_id is not None and sku_id is not None
    if is_update:
        assert warehouse_id is not None and sku_id is not None
        found = usecases.get_stock(session, warehouse_id, sku_id)
        if isinstance(found, Failure):
            return found
        stock = found
    return {
        "warehouses": [_warehouse_option(w) for w in usecases.list_warehouses(session)],
        "skus": [_sku_option(sku) for sku in usecases.list_skus(session)],
        "stock": _stock_row(stock) if stock is not None else None,
        "is_update": is_update,
    }


def stock_delete_confirm(
    session: SnakeSession, warehouse_id: int, sku_id: int
) -> StockDeletePage | Failure:
    """The confirmation page: the row about to go, and how much history goes with it.

    TWO statements, and the second is a `COUNT` rather than a fetch on purpose. Loading the movements
    to call `len()` on them works on the demo seed and falls over on a pair with a year of history —
    which is precisely the pair somebody would be trying to delete.
    """
    stock = usecases.get_stock(session, warehouse_id, sku_id)
    if isinstance(stock, Failure):
        return stock
    return {
        "stock": _stock_row(stock),
        "movement_count": usecases.count_movements(session, warehouse_id, sku_id),
    }


# ---- What is running out ---------------------------------------------------------------------------


class LowStockRow(TypedDict):
    """One pair the read-only view flagged, with the two facts a reorder decision needs beside it.

    `available` is `on_hand - reserved`, which is the very predicate the view filters on: showing the
    pair without it would be printing the alert and hiding the reason for it.

    `lead_time_days` is the other half of the decision and the reason this row is not the listing's
    `StockRow` with fewer columns. "What do I need to reorder" is two questions — what is short, and
    how long it takes to come back — and a page that answers only the first leaves the person reading
    it to look every SKU up somewhere else.
    """

    warehouse_id: int
    sku_id: int
    warehouse_code: str
    warehouse_name: str
    sku_name: str
    on_hand: int
    reserved: int
    available: int
    lead_time_days: int


class LowStockAlertsPage(TypedDict):
    """The reorder screen: every pair the database says is running out, named.

    `alert_count` travels rather than being left to `|length` in the two renderers, for the reason
    `moved_count` does on the report below: it is the number the heading and the empty state both
    say, and two templates reaching for it separately is two templates that can end up saying
    different things about one list.

    THERE IS NO THRESHOLD ON THIS PAGE, and its absence is the design. The rule lives in the VIEW —
    `LowStock` inlines it, because a view takes no parameters — so every caller on the three demos
    means the same thing by "running out". Repeating the number here would be a second definition,
    in the layer that cannot enforce it, going stale the day the migration moves it.
    """

    rows: list[LowStockRow]
    alert_count: int


def _low_stock_row(row: LowStock, warehouse: Warehouse, sku: Sku) -> LowStockRow:
    """A row of the view, flattened with the names its two ids stand for.

    The view projects `Stock` whole, so it carries the pair and the levels and NOTHING either half
    points at — a view is a query, not a graph, and there is no `row.warehouse` to hop through. The
    names therefore come from the two catalogues the caller has already read, not from a relation.
    """
    return {
        "warehouse_id": row.warehouse_id,
        "sku_id": row.sku_id,
        "warehouse_code": warehouse.code,
        "warehouse_name": warehouse.name,
        "sku_name": sku.name,
        "on_hand": row.on_hand,
        "reserved": row.reserved,
        "available": row.on_hand - row.reserved,
        "lead_time_days": sku.lead_time.days,
    }


def low_stock_alerts(session: SnakeSession) -> LowStockAlertsPage:
    """The pairs running out, named. THREE statements, and none of them grows with the alerts.

    The two catalogues are read WHOLE and turned into lookups rather than fetched per alert. That is
    the difference between a page that costs three statements and one that costs three plus two per
    row, and it is the only shape available: the view carries ids and no relations, so "fetch the
    warehouse of this alert" is a query with nowhere to be batched.

    Both lookups are indexed directly and a miss is a `KeyError`, on purpose. Every id here came out
    of a view over `Stock`, whose two foreign keys are enforced by the engine, so a missing warehouse
    means the catalogue and the view are reading different databases — which is worth a stack trace
    rather than a row with a blank name in it.

    It cannot fail. A stockroom with nothing running out is the answer everybody wants, not a 404,
    and the page says so in words.
    """
    alerts = usecases.low_stock(session)
    warehouses = {
        warehouse.id: warehouse for warehouse in usecases.list_warehouses(session)
    }
    skus = {sku.id: sku for sku in usecases.list_skus(session)}
    rows = [
        _low_stock_row(alert, warehouses[alert.warehouse_id], skus[alert.sku_id])
        for alert in alerts
    ]
    return {"rows": rows, "alert_count": len(rows)}


# ---- The movement book -----------------------------------------------------------------------------


class MovementBookLine(TypedDict):
    """One line of the book: what moved, where, how much, why, from which origin and when.

    THERE IS NO id, and its absence is the page. The line comes off a keyless view with the one
    column it inherits deferred, so two identical lines are two events and neither can be pointed
    at. A template that keyed its rows would be inventing an identity the answer does not have.
    """

    warehouse_id: int
    sku_id: int
    warehouse_code: str
    sku_name: str
    delta: int
    reason: str
    origin: str
    happened_at: str


class MovementBookPage(TypedDict):
    """The book: the last lines of each origin, and the two facts a reader needs about them.

    `book_size` is the bound PER ORIGIN, said out loud because it is not the length of the list: a
    quiet day shows fewer and a busy one shows exactly this many of each. `one_statement` is the
    same declaration `order_report` makes — the engine either takes parentheses around a bounded
    branch or the page takes the two-statement path, and hiding that would hide the most interesting
    thing on it.
    """

    lines: list[MovementBookLine]
    line_count: int
    book_size: int
    one_statement: bool


def _book_line(line: StockLedger, warehouse: Warehouse, sku: Sku) -> MovementBookLine:
    """A ledger line flattened, with the names its two ids stand for and the origin that wrote it.

    A compound loads no relationships, so the names come from the catalogues the caller has already
    read — the same shape `_low_stock_row` takes, and for the same reason.
    """
    return {
        "warehouse_id": line.stock_warehouse_id,
        "sku_id": line.stock_sku_id,
        "warehouse_code": warehouse.code,
        "sku_name": sku.name,
        "delta": line.delta,
        "reason": line.reason.value,
        "origin": "shop" if line.reason in SHOP_REASONS else "floor",
        "happened_at": line.happened_at.isoformat(),
    }


def movement_book(session: SnakeSession, *, size: int = BOOK_SIZE) -> MovementBookPage:
    """The two origins of the movements in one book, named.

    Two catalogues read WHOLE and turned into lookups, exactly as the reorder screen does: the book
    carries ids and no relations, so a name fetched per line would be an N+1 with nowhere to batch.
    The book itself is one statement or two depending on the engine, and never more.

    It cannot fail. A warehouse that has moved nothing is an answer, and the page says so in words.
    """
    lines = usecases.movement_book(session, size=size)
    warehouses = {
        warehouse.id: warehouse for warehouse in usecases.list_warehouses(session)
    }
    skus = {sku.id: sku for sku in usecases.list_skus(session)}
    rows = [
        _book_line(line, warehouses[line.stock_warehouse_id], skus[line.stock_sku_id])
        for line in lines
    ]
    return {
        "lines": rows,
        "line_count": len(rows),
        "book_size": size,
        "one_statement": session.dialect.supports_parenthesised_compound,
    }


# ---- The warehouse sheet ---------------------------------------------------------------------------


class WarehouseLineRow(TypedDict):
    """One SKU a warehouse holds, with everything that pair has done, in the same row.

    It is NOT a `StockRow` and cannot be: `_stock_row` reads `stock.warehouse` and `stock.sku`, and
    the query behind this page loads neither — it spends its second statement on the TO-MANY instead.
    Calling it here would not be slower, it would RAISE `SnakeRelationshipNotLoaded`, which is this
    ORM shouting rather than firing the query nobody asked for. So the SKU is named from a lookup and
    the warehouse is named once, in the header, because it is the same warehouse on every line.

    `net_delta` is the sum of the movements below it: what the pair has done ON BALANCE, next to what
    it holds now. The two are different questions — a line that received forty and shipped forty is
    busy and unchanged — and both are already in memory, so neither costs a statement.
    """

    sku_id: int
    sku_name: str
    on_hand: int
    reserved: int
    available: int
    counted_at: str
    movement_count: int
    net_delta: int
    movements: list[MovementRow]


class WarehouseSheetPage(TypedDict):
    """One warehouse: what it is, what it holds, and what each of those lines has been doing.

    The header is a `WarehouseCatalogueRow` and not a shape of its own, because it answers the same
    question the catalogue's row does — which warehouse is this, is it still open, since when — and a
    second shape saying that would be a second place to keep the date format.

    `movement_count` at this level is the total across the lines. It is what makes the page's ONE
    claim checkable by looking: every movement of every pair in this warehouse arrived in a single
    extra statement, so a number in the hundreds beside a handful of lines is the prefetch working
    rather than an N+1 hiding.
    """

    warehouse: WarehouseCatalogueRow
    lines: list[WarehouseLineRow]
    line_count: int
    movement_count: int


def _warehouse_line_row(stock: Stock, sku_name: str) -> WarehouseLineRow:
    """A stock row flattened with its movements, doing NO relation hop of its own.

    `stock.movements` is read and `stock.sku` is not, and the asymmetry is the whole page: the first
    was loaded by the query, the second was not.
    """
    movements = list(stock.movements)
    return {
        "sku_id": stock.sku_id,
        "sku_name": sku_name,
        "on_hand": stock.on_hand,
        "reserved": stock.reserved,
        "available": stock.on_hand - stock.reserved,
        "counted_at": stock.counted_at.isoformat() if stock.counted_at else "",
        "movement_count": len(movements),
        "net_delta": sum(movement.delta for movement in movements),
        "movements": [_movement_row(movement) for movement in movements],
    }


def warehouse_sheet(
    session: SnakeSession, warehouse_id: int
) -> WarehouseSheetPage | Failure:
    """What is in this warehouse and what each line has been doing. FIVE statements, and that is all.

    The five are the warehouse, the probe `stock_with_movements` makes before it reads, the stock
    rows, the movements of ALL of them — a select-in over a foreign key two columns wide, which is
    the hardest to-many in the demos and the reason this page exists — and the SKU catalogue the
    names come out of. Not one of them grows with the number of lines or with the length of a
    history, which is the claim `movement_count` above lets a reader check by looking at the page.

    The probe is a repeat of the fetch above it and it is not skipped, for the reason `order_detail`
    gives for its third statement: going THROUGH the use-case seam costs one lookup that going around
    it would save, and the price is fixed rather than per row. Reaching for the selector to shave it
    would put "what this page means" in a second place.

    The movements arrive WHOLE, never sliced. Trimming them here would throw away rows the statement
    has already paid for and would make a sheet of the last five look exactly like a sheet of a pair
    that has only moved five times.
    """
    warehouse = usecases.get_warehouse(session, warehouse_id)
    if isinstance(warehouse, Failure):
        return warehouse
    stock = usecases.stock_with_movements(session, warehouse_id)
    # Refused only if the warehouse went away between the fetch above and the read below, which is a
    # window another request can walk through. It is handled and not asserted away: "that cannot
    # happen between two statements" is how a demo teaches somebody to trust a race.
    if isinstance(stock, Failure):
        return stock
    names = {sku.id: sku.name for sku in usecases.list_skus(session)}
    lines = [_warehouse_line_row(row, names[row.sku_id]) for row in stock]
    return {
        "warehouse": _warehouse_catalogue_row(warehouse),
        "lines": lines,
        "line_count": len(lines),
        "movement_count": sum(line["movement_count"] for line in lines),
    }


# ---- The report -----------------------------------------------------------------------------------


class WarehouseStatsRow(TypedDict):
    """One warehouse with what it holds: the `annotate` row, flattened.

    `sku_count` and `total_units` are two correlated aggregates that came back in the SAME statement
    as the warehouse. A template computing either would be summing a relation in the renderer, which
    is the N+1 this layer exists to make impossible.
    """

    id: int
    code: str
    name: str
    sku_count: int
    total_units: int


class BusySkuRow(TypedDict):
    """One SKU that moves, with how often and by how much. The `GROUP BY` + `HAVING` row.

    `net_delta` is signed and stays an `int`: it is a number of units, not money, and a negative one
    means the SKU has shipped more than it received — which is the interesting row, not an error.
    """

    sku_name: str
    moves: int
    net_delta: int


class RankedStockRow(TypedDict):
    """One stock row with WHERE IT RANKS inside its own warehouse. The window-function row.

    `position` is what no `filter` and no `GROUP BY` could put here: it is a fact about the row's
    NEIGHBOURS, computed without collapsing them. Ties share a position, because `rank()` is what the
    selector asks for and two SKUs holding the same number of units really are tied.
    """

    warehouse_code: str
    sku_name: str
    on_hand: int
    position: int


class MovedSkuRow(TypedDict):
    """One SKU that has ever moved: the row a JOIN multiplied and `DISTINCT` folded back."""

    sku_id: int
    sku_name: str


class TrailRow(TypedDict):
    """One movement with the two figures the frame exists to tell apart.

    `running` is what the pair had moved in total by this row; `moving` is what it moved over the
    last three movements, this one included. They agree until the fourth movement of a series and
    part company for good after it — which is the reason both are on the page and neither would be
    worth showing alone.
    """

    sku: str
    delta: int
    running: int
    moving: int


class StockReportPage(TypedDict):
    """The inventory report: four questions a plain `filter` could not answer, plus the ratio.

    `never_moved` is computed HERE and not left to the template, for the reason `available` is on the
    stock listing: it is one subtraction, and two templates write one subtraction two ways. It is
    also the figure the page is really about — a SKU nobody has touched is either dead stock or a
    catalogue entry that was never stocked, and both are worth a meeting.

    `minimum_moves` comes back so the page can say what threshold it applied. A report that shows a
    filtered list without naming the filter is a report whose numbers cannot be reproduced.
    """

    warehouses: list[WarehouseStatsRow]
    busy_skus: list[BusySkuRow]
    minimum_moves: int
    ranking: list[RankedStockRow]
    moved_skus: list[MovedSkuRow]
    moved_count: int
    total_skus: int
    never_moved: int
    trail: list[TrailRow]


def _warehouse_stats_row(stats: WarehouseStats) -> WarehouseStatsRow:
    """A `@snake_result` flattened: the model's own columns and the two aggregates beside them."""
    return {
        "id": stats.warehouse.id,
        "code": stats.warehouse.code,
        "name": stats.warehouse.name,
        "sku_count": stats.sku_count,
        "total_units": stats.total_units,
    }


def stock_report(
    session: SnakeSession, *, minimum_moves: int = 2, ranking_size: int = 50
) -> StockReportPage:
    """The inventory report. SIX statements, and none of them grows with the number of rows.

    It never returns a `Failure`: every figure on it is an aggregate, and an empty warehouse is an
    answer rather than a missing page.
    """
    report = usecases.stock_report(
        session, minimum_moves=minimum_moves, ranking_size=ranking_size
    )
    return {
        "trail": [
            {"sku": name, "delta": delta, "running": running, "moving": moving}
            for name, delta, running, moving in report.trail
        ],
        "warehouses": [_warehouse_stats_row(stats) for stats in report.warehouses],
        "busy_skus": [
            {"sku_name": name, "moves": moves, "net_delta": net}
            for name, moves, net in report.busy_skus
        ],
        "minimum_moves": minimum_moves,
        "ranking": [
            {
                "warehouse_code": code,
                "sku_name": name,
                "on_hand": on_hand,
                "position": position,
            }
            for code, name, on_hand, position in report.ranking
        ],
        "moved_skus": [
            {"sku_id": sku_id, "sku_name": name} for sku_id, name in report.moved_skus
        ],
        "moved_count": len(report.moved_skus),
        "total_skus": report.total_skus,
        "never_moved": max(0, report.total_skus - len(report.moved_skus)),
    }


# ---- The export ------------------------------------------------------------------------------------


MOVEMENT_EXPORT_HEADER: tuple[str, ...] = (
    "movement_id",
    "warehouse_id",
    "warehouse_code",
    "sku_id",
    "sku_name",
    "delta",
    "reason",
    "note",
    "happened_at",
)
"""The columns of the movements CSV, and BOTH halves of the composite key are in it.

Not decoration: a row of this file identifies a stock pair, and half a key identifies nothing. An
export somebody reconciles against the database has to be joinable back to it, and this domain is the
one where that takes two columns.
"""


def _movement_cells(movement: StockMovement) -> tuple[str, ...]:
    """One movement as CSV text: every relation already hopped, every value already formatted.

    The two hops are the point. `movement.stock.warehouse.code` is read HERE, on a row the query
    already loaded through a to-one `include`, and never inside the streaming loop of a demo — where
    it would be a query per row, in a loop that is by definition long, in the one layer no
    `assert_queries` watches.
    """
    stock = movement.stock
    return (
        str(movement.id),
        str(movement.stock_warehouse_id),
        stock.warehouse.code,
        str(movement.stock_sku_id),
        stock.sku.name,
        str(movement.delta),
        movement.reason.value,
        movement.note or "",
        movement.happened_at.isoformat(),
    )


def stock_movements_export(
    session: SnakeSession, *, warehouse_id: int | None = None
) -> CsvExport:
    """Every stock movement as CSV rows, STREAMED: ONE statement, and memory that does not grow.

    THE GENERATOR EXPRESSION IS THE IMPLEMENTATION AND THAT IS DELIBERATE. Written as a `for` loop
    with a `yield`, this function would become a generator itself, and its first line — the call that
    builds the query and lets `iterate` refuse an unstreamable one — would not run until somebody
    asked for a row. Building the stream eagerly and mapping it lazily is what keeps the refusal next
    to the mistake and the execution next to the consumer.

    Nothing here bounds the result, and nothing should. A `limit()` would make an export that never
    had to stream pass every test that says it streams.
    """
    movements = usecases.stream_movements(session, warehouse_id=warehouse_id)
    return CsvExport(
        filename="stock-movements.csv",
        header=MOVEMENT_EXPORT_HEADER,
        rows=(_movement_cells(movement) for movement in movements),
    )
