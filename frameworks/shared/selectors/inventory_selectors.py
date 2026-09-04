"""inventory domain — SELECTORS: reads over warehouses, SKUs and per-warehouse stock.

Every framework re-exports them from `apps/inventory/selectors.py`.

The reads here are the ones the other domains could not make, because they need a COMPOSITE key.
`movements_of` loads a to-many whose foreign key has two columns, which is the case the select-in
divides its placeholder budget by; `stock_of_warehouse` navigates two to-one relationships in the
same statement. Both are ordinary things to want from an inventory, and neither had a path before.

Every read here comes in TWO pieces, and the split is the seam the asynchronous demo stands on. The
FRAGMENT builds a `SnakeQuery` (or, for an aggregate, the projected columns) and does not run it;
the EXECUTOR takes a session and runs it. Only the executor has a colour — `session.all(...)` on one
path, `await session.all(...)` on the other — so the SQL, which is the part that drifts when it is
written twice, is written once and shared by both. See `shared/aio/inventory_usecases.py` for the
other half. An aggregate read (`session.annotate`/`session.select`) single-sources its columns the
same way: the expressions are exposed as their own fragment functions rather than built twice inside
two executors that happen to agree today.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from snakeorm import (
    SNAKE_CURRENT_ROW,
    SnakeCompound,
    SnakeDialect,
    SnakeJoinedQuery,
    SnakeQuery,
    SnakeSession,
    SnakeOrder,
    SnakeValue,
    count,
    rank,
    snake_case,
    snake_coalesce,
    snake_nullif,
    snake_key,
    snake_keys,
    snake_preceding,
    snake_rows,
    sum_,
)

from shared.models import (
    BOOK_SIZE,
    FLOOR_REASONS,
    LowStock,
    MovementReason,
    SHOP_REASONS,
    Sku,
    Stock,
    StockLedger,
    StockMovement,
    Warehouse,
    WarehouseStats,
)

# How many rows of a stream travel from the server at a time. Five hundred and not one, because a
# round trip per row is what makes streaming slower than materialising; and not fifty thousand,
# because the point of the page is that memory stays flat. It is a DEFAULT and not a constant of the
# query: a caller exporting to a socket with its own buffer is entitled to a different number.
EXPORT_CHUNK = 500


def warehouses(*, active_only: bool = False) -> SnakeQuery[Warehouse]:
    """FRAGMENT: warehouses by code, optionally narrowed to the open ones. NOT executed."""
    query = SnakeQuery(Warehouse).order_by(Warehouse.code.asc())
    if active_only:
        query = query.filter(Warehouse.active == True)  # noqa: E712 - a SQL condition
    return query


def list_warehouses(
    session: SnakeSession, *, active_only: bool = False
) -> list[Warehouse]:
    """Warehouses by code. `active_only` uses the partial index."""
    return session.all(warehouses(active_only=active_only))


def warehouse_by_id(warehouse_id: int) -> SnakeQuery[Warehouse]:
    """FRAGMENT: one warehouse by id. NOT executed."""
    return SnakeQuery(Warehouse).filter(Warehouse.id == warehouse_id)


def get_warehouse(session: SnakeSession, warehouse_id: int) -> Warehouse | None:
    """One warehouse by id, or None."""
    return session.first(warehouse_by_id(warehouse_id))


def all_skus() -> SnakeQuery[Sku]:
    """FRAGMENT: every SKU by name. NOT executed."""
    return SnakeQuery(Sku).order_by(Sku.name.asc())


def list_skus(session: SnakeSession) -> list[Sku]:
    """Every SKU by name."""
    return session.all(all_skus())


def sku_by_id(sku_id: int) -> SnakeQuery[Sku]:
    """FRAGMENT: one SKU by id. NOT executed."""
    return SnakeQuery(Sku).filter(Sku.id == sku_id)


def get_sku(session: SnakeSession, sku_id: int) -> Sku | None:
    """One SKU by id, or None."""
    return session.first(sku_by_id(sku_id))


def with_at_least(query: SnakeQuery[Stock], units: int) -> SnakeQuery[Stock]:
    """Fragment: only the rows holding at least `units`. It stacks onto any stock query.

    What an inventory actually wants here is "whatever is free", `quantity > reserved`, and that one
    cannot be written yet: the right-hand side of a comparison is always a VALUE, so a column there
    is bound as a parameter. It does not even raise — the emitter puts a `SnakeExpr` object into
    `params` and the failure surfaces later, inside the driver. Against a literal it is exact, so the
    threshold is passed in until comparing two columns is a thing the query builder can express.
    """
    return query.filter(Stock.on_hand >= units)


def warehouse_stock(warehouse_id: int) -> SnakeQuery[Stock]:
    """FRAGMENT: a warehouse's stock with its SKU loaded, ordered by SKU. NOT executed."""
    return (
        SnakeQuery(Stock)
        .include(Stock.sku)
        .filter(Stock.warehouse_id == warehouse_id)
        .order_by(Stock.sku_id.asc())
    )


def stock_of_warehouse(session: SnakeSession, warehouse_id: int) -> list[Stock]:
    """A warehouse's stock with its SKU loaded: ONE statement, no N+1."""
    return session.all(warehouse_stock(warehouse_id))


def stock_pair(warehouse_id: int, sku_id: int) -> SnakeQuery[Stock]:
    """FRAGMENT: one stock row by its COMPOSITE key, no relations loaded. NOT executed.

    What a write path wants: it needs the row, not the two rows it points at.
    """
    return SnakeQuery(Stock).filter(
        Stock.warehouse_id == warehouse_id, Stock.sku_id == sku_id
    )


def get_stock(session: SnakeSession, warehouse_id: int, sku_id: int) -> Stock | None:
    """One stock row by its COMPOSITE key. Both halves are the identity; neither alone is."""
    return session.first(stock_pair(warehouse_id, sku_id))


def stock_pair_with_relations(warehouse_id: int, sku_id: int) -> SnakeQuery[Stock]:
    """FRAGMENT: one stock row WITH its warehouse and its SKU loaded. NOT executed.

    What a PAGE wants, and the difference from `stock_pair` is a whole class of bug — a detail
    template that prints `stock.sku.name` off the plain row fires a query while it renders, in the
    one layer where nothing counts queries. Doing the two hops here means the page costs the same
    statement whether it shows the SKU's name or not.
    """
    return (
        SnakeQuery(Stock)
        .include(Stock.warehouse, Stock.sku)
        .filter(Stock.warehouse_id == warehouse_id, Stock.sku_id == sku_id)
    )


def get_stock_with_relations(
    session: SnakeSession, warehouse_id: int, sku_id: int
) -> Stock | None:
    """One stock row WITH its warehouse and its SKU already loaded, or None."""
    return session.first(stock_pair_with_relations(warehouse_id, sku_id))


def stock_to_take_from(warehouse_id: int, sku_ids: Sequence[int]) -> SnakeQuery[Stock]:
    """FRAGMENT: the stock rows one order takes its units from, in a FIXED order. NOT executed.

    ONE statement for the whole order and not one per line, which matters twice over. It is the
    difference between a reservation costing one round trip and costing as many as the order has
    lines, and — the half that is not about speed — it is what makes the LOCK below atomic: rows
    locked by one statement are taken together, so there is no window between line two and line three
    for somebody else to slip into.

    The `ORDER BY` is not cosmetic either, and it is the reason this is a fragment of its own rather
    than an `in_` written inline at each call site. Postgres takes the locks in the order the rows
    come back, so two orders wanting the same two SKUs in opposite order would each hold what the
    other is waiting for — a deadlock, resolved by the engine killing one of them at random. Sorting
    by `sku_id` gives every operation in this repo the SAME order, and a global order is exactly what
    a deadlock cannot survive.
    """
    return (
        SnakeQuery(Stock)
        .filter(Stock.warehouse_id == warehouse_id, Stock.sku_id.in_(tuple(sku_ids)))
        .order_by(Stock.sku_id.asc())
    )


def stock_for_pairs(pairs: Sequence[tuple[int, int]]) -> SnakeQuery[Stock]:
    """FRAGMENT: named `(warehouse, sku)` PAIRS, which is not what one `in_` per column asks. NOT executed.

    The fragment above serves one warehouse, so a single `in_` over `sku_id` says exactly what it
    means. A pick list that spans warehouses does not: `warehouse_id.in_(...)` AND `sku_id.in_(...)`
    is the CARTESIAN PRODUCT, and it would return —and, through `lock_stock`, LOCK— every crossing of
    the two lists. Ask for warehouse 1's screws and warehouse 2's bolts and you also get warehouse
    1's bolts, which belong to somebody else's order.

    `snake_keys` is the row constructor, `(warehouse_id, sku_id) IN ((1, 7), (2, 9))`: only the pairs
    named. Postgres, MySQL and SQLite all run it; a dialect that could not gets the equivalent
    `(a = ? AND b = ?) OR (...)` emitted for it, so this fragment is not one engine's query.

    The `ORDER BY` carries the same argument as the fragment above, widened by one column: a global
    order over the WHOLE key is what keeps two overlapping pick lists from deadlocking each other.
    """
    return (
        SnakeQuery(Stock)
        .filter(
            snake_keys(Stock).in_(
                [
                    snake_key(Stock)
                    .set(Stock.warehouse_id, warehouse)
                    .set(Stock.sku_id, sku)
                    for warehouse, sku in pairs
                ]
            )
        )
        .order_by(Stock.warehouse_id.asc(), Stock.sku_id.asc())
    )


def pick_across_warehouses(
    session: SnakeSession, pairs: Sequence[tuple[int, int]]
) -> list[Stock]:
    """The pairs above, read. Empty in, empty out — there is no `IN ()` to emit for nothing."""
    if not pairs:
        return []
    return session.all(stock_for_pairs(pairs))


def lock_stock(
    session: SnakeSession, *, warehouse_id: int, sku_ids: Sequence[int]
) -> list[Stock]:
    """The rows above, LOCKED until the transaction ends where the engine can lock rows.

    This is the read `reserve` and `settle` do before they decide anything, and the lock is the whole
    point: without it two customers read the same availability, both find it sufficient and both
    write — and neither engine nor model can tell afterwards that the same unit was sold twice.
    `SELECT ... FOR UPDATE` makes the second reader WAIT until the first commits, so it decides
    against the number the first one left behind rather than against the one it found.

    The capability is ASKED rather than assumed, and the answer changes the SQL rather than stopping
    the operation, which is the one case where that is honest. `for_update` on SQLite does not
    degrade — it raises at compile time — so a demo that runs on three engines has to ask. And what
    SQLite gives instead is not less: its writers hold the whole FILE, so a write transaction there
    is already alone with the database. There is nothing to reserve because nothing else is running.
    MySQL and Postgres both answer `Full`, so both take the real lock.
    """
    return session.all(
        locking_stock_query(session.dialect, warehouse_id=warehouse_id, sku_ids=sku_ids)
    )


def locking_stock_query(
    dialect: SnakeDialect, *, warehouse_id: int, sku_ids: Sequence[int]
) -> SnakeQuery[Stock]:
    """FRAGMENT: the rows above with the lock ASKED FOR, NOT executed.

    It takes the DIALECT and not the session, and that is what makes it colourless: the question
    `for_update` depends on is about what the engine can do, which both sessions answer the same way
    and neither has to run a statement to answer. So the asynchronous twin of `reserve` locks the
    same rows in the same order with the same SQL, rather than re-deciding it and drifting.
    """
    query = stock_to_take_from(warehouse_id, sku_ids)
    return query.for_update() if dialect.supports_row_locking else query


def stock_listing(warehouse_id: int | None = None) -> SnakeQuery[Stock]:
    """Fragment: the ordered stock query a listing pages through, optionally narrowed to a warehouse.

    It is NOT executed and it carries no `limit`, because it is consumed twice for the same page —
    once counted and once fetched — and those two have to be the same question. Building the filter
    in each of them is how a pager ends up saying "47 rows" over a listing that shows a different
    47.

    The order is the COMPOSITE key, both halves: ordering by `sku_id` alone is stable only inside one
    warehouse, and the unfiltered listing spans all of them. An unstable order under LIMIT/OFFSET
    does not fail, it just shows a row twice and skips another.
    """
    query = SnakeQuery(Stock).order_by(Stock.warehouse_id.asc(), Stock.sku_id.asc())
    if warehouse_id is not None:
        query = query.filter(Stock.warehouse_id == warehouse_id)
    return query


def stock_in_warehouse(warehouse_id: int) -> SnakeQuery[Stock]:
    """FRAGMENT: every stock row of a warehouse, UNORDERED. NOT executed.

    This is the WHERE `reserve_units`' bulk update needs and NOTHING else. It is deliberately not
    `stock_listing`: a bulk UPDATE's `_guard_bulk_write` rejects a query carrying an ORDER BY outright
    (limit/offset/order_by/group_by/having/include are all refused on a bulk write), so the fragment
    the pager counts and fetches with — which always carries one — cannot be reused here the way
    `count_stock_rows` reuses it for a SELECT.
    """
    return SnakeQuery(Stock).filter(Stock.warehouse_id == warehouse_id)


def count_stock_rows(session: SnakeSession, *, warehouse_id: int | None = None) -> int:
    """How many stock rows the listing has, for the pager. `COUNT(*)` over the same filter.

    A pager needs the total, and the total is not `len(rows)`: that is the size of the page. This is
    the second of the listing's two statements and the reason the fragment above exists.
    """
    return session.count(stock_listing(warehouse_id))


def stock_rows_page(
    session: SnakeSession,
    *,
    warehouse_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Stock]:
    """One page of stock rows with the warehouse and the SKU loaded: ONE statement, no N+1.

    The two `include`s are to-one, so they are LEFT JOINs on the same SELECT and the `limit` still
    counts stock rows. That is what makes the page's cost flat: thirty rows and three rows are the
    same statement with a different number in it.
    """
    return session.all(
        stock_listing(warehouse_id)
        .include(Stock.warehouse, Stock.sku)
        .limit(limit)
        .offset(offset)
    )


def stock_movements(warehouse_id: int, sku_id: int) -> SnakeQuery[StockMovement]:
    """FRAGMENT: every movement of ONE stock row, UNORDERED. NOT executed.

    The order belongs to the caller and not to this filter: `movements_of` wants the newest first
    and `count_movements_of` wants no order at all, so folding an `ORDER BY` in here would be
    imposing one caller's preference on the other's `COUNT(*)`.
    """
    return SnakeQuery(StockMovement).filter(
        StockMovement.stock_warehouse_id == warehouse_id,
        StockMovement.stock_sku_id == sku_id,
    )


def count_movements_of(session: SnakeSession, warehouse_id: int, sku_id: int) -> int:
    """How many movements hang off ONE stock row. A COUNT, not a fetch.

    The delete confirmation has to say what would be dragged along, and `len(movements_of(...))` is
    the version that works on the demo seed and drags a year of history into memory on the pair
    somebody would actually want to delete.
    """
    return session.count(stock_movements(warehouse_id, sku_id))


def warehouse_stock_with_movements(warehouse_id: int) -> SnakeQuery[Stock]:
    """FRAGMENT: a warehouse's stock with each row's movements loaded. NOT executed.

    This is the to-many over a COMPOSITE foreign key: the select-in binds TWO placeholders per
    parent, so its batch is half the size of a single-column one. Nothing outside a unit test
    exercised that until this domain existed.
    """
    return (
        SnakeQuery(Stock)
        .include(Stock.movements)
        .filter(Stock.warehouse_id == warehouse_id)
        .order_by(Stock.sku_id.asc())
    )


def stock_with_movements(session: SnakeSession, warehouse_id: int) -> list[Stock]:
    """A warehouse's stock with each row's movements loaded."""
    return session.all(warehouse_stock_with_movements(warehouse_id))


def movements_of(
    session: SnakeSession, warehouse_id: int, sku_id: int
) -> list[StockMovement]:
    """The movements of ONE stock row, most recent first."""
    return session.all(
        stock_movements(warehouse_id, sku_id).order_by(StockMovement.happened_at.desc())
    )


def skus_in_warehouse(warehouse_id: int) -> SnakeQuery[Sku]:
    """The query for the SKUs held by a warehouse, NOT executed.

    It resolves it with a SUBQUERY over the stock and not with two round trips: `as_scalar` projects
    the `sku_id` filtered by warehouse and `Sku.id.in_(...)` consumes it. Pulling the ids into Python
    would make the second statement carry a parameter per SKU, which grows with the data.
    """
    held = (
        SnakeQuery(Stock)
        .filter(Stock.warehouse_id == warehouse_id)
        .as_scalar(Stock.sku_id)
    )
    return SnakeQuery(Sku).filter(Sku.id.in_(held))


def warehouse_sku_count() -> SnakeValue[int]:
    """FRAGMENT: the aggregate `warehouse_stats` annotates as `sku_count`. NOT executed."""
    return Warehouse.stock.count()


def warehouse_total_units() -> SnakeValue[int]:
    """FRAGMENT: the aggregate `warehouse_stats` annotates as `total_units`. NOT executed.

    `SnakeValue[int]` and not `SnakeValue[int | None]`, which is the whole difference: a `SUM` over
    no rows is NULL on every engine, and `WarehouseStats.total_units` is declared `int`. A warehouse
    opened this morning holds zero units, not an unknown number of them.

    The `COALESCE` goes here and not in the executor because a value patched in Python exists only
    AFTER the statement has run: it cannot be ordered by — NULL sorts first on some engines and last
    on others — and it cannot be filtered on, since `total > 0` over NULL is unknown rather than
    false and the row vanishes from a `HAVING` instead of failing it.
    """
    return snake_coalesce(Warehouse.stock.sum_(Stock.on_hand), 0)


def warehouses_by_units_held(session: SnakeSession) -> list[tuple[str, int]]:
    """Every warehouse and what it holds, emptiest first. ONE statement.

    The empty ones come first, and they come first on the THREE engines: that is what the `COALESCE`
    buys. Sorting by an aggregate that can be NULL puts them at whichever end each engine chose, so
    the same code would answer differently depending on the `.env`.

    It goes through `annotate` because the aggregate is a CORRELATED subquery — one per warehouse
    row — and the ORDER BY references the same expression the projection carries.
    """
    rows = session.annotate(
        SnakeQuery(Warehouse).order_by(
            warehouse_total_units().asc(), Warehouse.code.asc()
        ),
        WarehouseStats,
        sku_count=warehouse_sku_count(),
        total_units=warehouse_total_units(),
    )
    return [(row.warehouse.code, row.total_units) for row in rows]


def warehouse_stats(session: SnakeSession) -> list[WarehouseStats]:
    """Every warehouse with how many SKUs it holds and how many units in total.

    Two correlated aggregates in ONE statement, typed into `WarehouseStats`: no dict of `object`,
    and no second query per warehouse. The base query is `warehouses()` unfiltered — the same
    fragment `list_warehouses` executes — and the two aggregates are their own fragments so the
    asynchronous twin annotates with the SAME expressions rather than rebuilding them.
    """
    return session.annotate(
        warehouses(),
        WarehouseStats,
        sku_count=warehouse_sku_count(),
        total_units=warehouse_total_units(),
    )


def warehouses_with_stock() -> SnakeQuery[Warehouse]:
    """FRAGMENT: warehouses with AT LEAST one stock row, a correlated EXISTS. NOT executed."""
    return (
        SnakeQuery(Warehouse)
        .filter(Warehouse.stock.any())
        .order_by(Warehouse.code.asc())
    )


def warehouses_holding_anything(session: SnakeSession) -> list[Warehouse]:
    """Warehouses with AT LEAST one stock row: a correlated EXISTS, it does not multiply rows."""
    return session.all(warehouses_with_stock())


def low_stock_pairs() -> SnakeQuery[LowStock]:
    """FRAGMENT: the pairs running out, straight off the read-only VIEW. NOT executed.

    The threshold lives in the database, not here: the view IS the definition of "running out", so
    every caller on the three demos means the same thing by it. Changing it is a migration, which is
    the honest place for a rule the whole system reads.
    """
    return SnakeQuery(LowStock).order_by(
        LowStock.warehouse_id.asc(), LowStock.sku_id.asc()
    )


def low_stock(session: SnakeSession) -> list[LowStock]:
    """The pairs running out, straight off the read-only VIEW."""
    return session.all(low_stock_pairs())


def movements_to_export(warehouse_id: int | None = None) -> SnakeQuery[StockMovement]:
    """FRAGMENT: every stock movement, oldest first, with the names it will be printed with. NOT run.

    THE SHAPE IS THE POINT, and it is dictated by `iterate()` rather than chosen. Streaming refuses a
    prefetch and a to-many `include` — the select-in needs every root to fire its second query, and
    in streaming the roots do not exist yet — so an export query may only ever grow TO-ONE hops.
    Here there are two of them, both reached THROUGH `stock`: the warehouse and the SKU. They are
    LEFT JOINs on the same SELECT, so a movement arrives already knowing which warehouse it happened
    in and what it moved, and the writer never navigates a relation inside the loop.

    That last part is the whole reason the include is here and not left out. A CSV writer reaching
    for `movement.stock.sku.name` itself would fire a query per row, in the one loop that is by
    definition long, in the one layer where nothing counts queries.

    NO `limit()`, deliberately. A bounded export is a page of results wearing a download's name, and
    it would make every test in `test_exports_stream.py` pass over a query that never had to stream.

    The order is `happened_at` with the id as the tiebreaker: two movements written in the same
    second are ordinary here (a receipt of ten lines), and an unstable order in a file somebody
    diffs against last week's is a file that looks changed when nothing changed.
    """
    query = (
        SnakeQuery(StockMovement)
        .include(StockMovement.stock.warehouse, StockMovement.stock.sku)
        .order_by(StockMovement.happened_at.asc(), StockMovement.id.asc())
    )
    if warehouse_id is not None:
        query = query.filter(StockMovement.stock_warehouse_id == warehouse_id)
    return query


def stream_movements(
    session: SnakeSession,
    *,
    warehouse_id: int | None = None,
    chunk: int = EXPORT_CHUNK,
) -> Iterator[StockMovement]:
    """The movements one at a time, WITHOUT the result ever existing whole in memory.

    `return`, never `yield`. Written as a generator this function would not run a line of its body
    until somebody asked for the first row, and two things would move with it: the guard inside
    `iterate` that rejects an unstreamable query would fire far from the call that caused it, and
    the laziness this module claims would become this function's laziness rather than the ORM's.
    Returning the iterator keeps the guard eager and the execution lazy, which is the pair we want.
    """
    return session.iterate(movements_to_export(warehouse_id), chunk=chunk)


def busy_sku_movements(minimum_moves: int) -> SnakeQuery[StockMovement]:
    """FRAGMENT: movements grouped by SKU name, kept only where the group moved often enough. NOT run.

    `HAVING COUNT(*) >= n` is the aggregate filtered by its OWN aggregate: `WHERE` decides row by row
    and cannot see a count that does not exist until the rows are grouped, so this is the one shape
    that can answer "the SKUs that move".
    """
    return (
        SnakeQuery(StockMovement)
        .group_by(StockMovement.stock.sku.name)
        .having(count() >= minimum_moves)
        .order_by(StockMovement.stock.sku.name.asc())
    )


def busy_sku_columns() -> tuple[SnakeValue[str], SnakeValue[int], SnakeValue[int]]:
    """FRAGMENT: the three projected columns of `busy_skus`, in call order. NOT executed.

    The net delta is `SnakeValue[int]` because the `COALESCE` makes it one. It used to be
    `int | None` on the grounds that "a SUM over zero rows comes back NULL" — true of a `SUM`, and
    not true HERE: this one runs inside a `GROUP BY` filtered by `HAVING count() >= n`, and a group
    that reaches the projection has at least n rows in it by construction. The `None` the executor
    was patching could not arrive.

    So the `COALESCE` is not there to catch that case. It is there to make the type honest at the
    only place that can promise it — the engine — instead of in a comprehension that runs after the
    ordering and the filtering have already happened.
    """
    return (
        StockMovement.stock.sku.name,
        count(),
        snake_coalesce(sum_(StockMovement.delta), 0),
    )


def busy_skus(
    session: SnakeSession, *, minimum_moves: int = 2
) -> list[tuple[str, int, int]]:
    """SKUs that have moved AT LEAST `minimum_moves` times, with how often and by how much. GROUP BY + HAVING.

    The group is the SKU's NAME and not its id, which is what makes the JOIN appear: `stock.sku.name`
    is a two-hop navigation, and the emitter plans both hops as JOINs inside the same statement.
    Grouping by the id and looking the names up afterwards would be the same report with an N+1 in
    it.

    The counter is an `int` and the net delta is an `int`, both rebuilt rather than trusted: a
    projection hands back whatever the engine's aggregate returned, and the engines do not agree.
    Here both columns are integers so the agreement is real, and the rebuild is what makes the
    signature honest instead of hopeful.
    """
    rows = session.select(busy_sku_movements(minimum_moves), *busy_sku_columns())
    return [(name, int(moves), int(net)) for name, moves, net in rows]


# The thresholds the replenishment desk works to. They live here AND, inlined, inside the `LowStock`
# view — a duplication worth naming rather than hiding, because a view takes no parameters: the number
# is part of the object that lives in the database, not of the call.
STOCK_EMPTY = 0
STOCK_LOW = 10


def reserved_percent() -> SnakeValue[int | None]:
    """FRAGMENT: how much of a pair is already promised, in whole per cent. NOT executed.

    `NULLIF(on_hand, 0)` is what keeps a pair holding nothing from dividing by zero, and the engines
    do NOT agree on what that costs — measured against both: SQLite answers NULL in silence,
    PostgreSQL raises `division by zero`. The same rows would give a blank cell on one engine and a
    500 on the other, which is the worst shape a difference can take: whichever engine the developer
    runs is the one that gets tested.

    `NULLIF` and `COALESCE` part company here, on the same domain and in opposite directions: a
    warehouse with no stock holds ZERO units, and a pair with nothing on the shelf has NO percentage
    promised. Zero would say "none of it is promised", which reads as a pair with stock going spare.
    The absence IS the answer.

    THE DECLARED TYPE SAYS `int | None` BECAUSE THE VALUES DO. It used to say `int` while the
    executor below said `int | None`, and the gap was a limit of the ORM written down rather than
    papered over: `snake_nullif` INTRODUCED the NULL without declaring it, and the arithmetic
    operators carried one single `T`, so dividing by something nullable came out `SnakeArith[int]`.
    Both halves are closed — `snake_nullif` returns `SnakeNullIf[T | None]` and the operators
    propagate nullability — so the fragment and its executor finally agree.

    Propagating a `None` is not the numeric promotion that stayed refused, and the difference is
    worth keeping straight: `a + NULL` is NULL on the three engines with no choice in it, so the type
    is describing SQL rather than deciding for anybody. `int * 1.0` decides.

    PER CENT AND NOT A FRACTION, and that one is a decision about the DEMO, not a limit any more.
    `reserved / on_hand` is integer division — forty-five over fifty came back `0`, and on Postgres
    and SQLite alike, which is worse than the division by zero because they AGREE and no run tells
    you. It can now be written as a real division with `snake_cast(x, float)`; per cent stays because
    the truncation is the point of per cent and it is what a replenishment desk reads. Changing it
    would change what the demo TEACHES, which is a call about the demos.
    """
    return Stock.reserved * 100 / snake_nullif(Stock.on_hand, STOCK_EMPTY)


def pairs_by_sku_name() -> SnakeQuery[Stock]:
    """FRAGMENT: every stock pair, by SKU name. NOT executed."""
    return SnakeQuery(Stock).order_by(Stock.sku.name.asc())


def reserved_ratio(session: SnakeSession) -> list[tuple[str, int | None]]:
    """Every pair and the per cent of it already promised. ONE statement.

    The pairs holding nothing are IN the answer, with no percentage. Filtering them out with
    `WHERE on_hand > 0` would remove exactly the rows the replenishment desk needs to see.

    `int | None` is the honest signature even though the fragment above is typed `int`: the engine
    returns NULL for those pairs and this is the layer that can say so.
    """
    rows = session.select(pairs_by_sku_name(), Stock.sku.name, reserved_percent())
    return [(name, None if percent is None else int(percent)) for name, percent in rows]


def stock_status() -> SnakeValue[str]:
    """FRAGMENT: the status of a pair as a `CASE WHEN`, over what is AVAILABLE. NOT executed.

    `on_hand - reserved` and not `on_hand`: a pair holding fifty units of which forty-five are
    promised has five available. A report reading the shelf calls that healthy, and the desk finds out
    when somebody tries to ship. The subtraction could not be WRITTEN until the ORM learned to compare
    a column against a column.

    It is a `SnakeValue[str]`, which is what lets it be both GROUPED BY and PROJECTED with no cast: a
    `CASE` is a value, not a condition.
    """
    available = Stock.on_hand - Stock.reserved
    return snake_case(
        (available <= STOCK_EMPTY, "out"),
        (available < STOCK_LOW, "low"),
        default="ok",
    )


def stock_grouped_by_status() -> SnakeQuery[Stock]:
    """FRAGMENT: stock grouped by that status, ordered so the answer is stable. NOT executed.

    The classification is inside the `GROUP BY` because that is the only place it can be. A bucket
    that exists in Python cannot be grouped by: the alternative is loading every stock row and
    counting them in a loop, which is exactly the promise the inventory report makes about not
    growing with the data.
    """
    return SnakeQuery(Stock).group_by(stock_status()).order_by(stock_status().asc())


def stock_by_status(session: SnakeSession) -> list[tuple[str, int]]:
    """How many pairs are out, low and fine. ONE statement, three rows, whatever the warehouse holds.

    The counter is rebuilt as an `int` rather than trusted: a projection hands back whatever the
    engine's aggregate returned, and the engines do not agree on the type of a `COUNT`.
    """
    rows = session.select(stock_grouped_by_status(), stock_status(), count())
    return [(status, int(how_many)) for status, how_many in rows]


def ranked_stock(limit: int) -> SnakeQuery[Stock]:
    """FRAGMENT: stock ordered by warehouse then by descending quantity, bounded to a page. NOT run.

    The `limit` bounds the PAGE and not the window: SQL computes windows before LIMIT, so the ranks
    the columns below compute are the real ones even though only the first rows are shown.
    """
    return (
        SnakeQuery(Stock)
        .order_by(Stock.warehouse.code.asc(), Stock.on_hand.desc(), Stock.sku_id.asc())
        .limit(limit)
    )


def ranked_stock_columns() -> tuple[
    SnakeValue[str], SnakeValue[str], SnakeValue[int], SnakeValue[int]
]:
    """FRAGMENT: the four projected columns of `stock_ranking`, in call order. NOT executed.

    `RANK() OVER (PARTITION BY warehouse_id ORDER BY quantity DESC)`: the textbook window, `rank()`
    and not `row_number()` because two SKUs holding the same number of units are genuinely tied and a
    ranking that broke the tie by id would be inventing an order the data does not have.
    """
    return (
        Stock.warehouse.code,
        Stock.sku.name,
        Stock.on_hand,
        rank().over(
            partition_by=(Stock.warehouse_id,), order_by=(Stock.on_hand.desc(),)
        ),
    )


def stock_ranking(
    session: SnakeSession, *, limit: int = 50
) -> list[tuple[str, str, int, int]]:
    """Every stock row with WHERE IT RANKS inside its own warehouse. A WINDOW function.

    The ranking key is `quantity`, an INTEGER, and that is not an accident either. `Decimal` ordering
    is DEGRADED on SQLite — the value is stored as text and sorts lexicographically, so `51.11` would
    outrank `26494.27` — and a report whose numbers depend on which engine answered is worse than no
    report. Money gets ranked nowhere in this repository for that reason.
    """
    rows = session.select(ranked_stock(limit), *ranked_stock_columns())
    return [
        (code, name, int(quantity), int(position))
        for code, name, quantity, position in rows
    ]


def moved_stock() -> SnakeJoinedQuery[Stock, StockMovement]:
    """FRAGMENT: stock explicitly JOINed onto its movements, folded back with DISTINCT. NOT run.

    A JOIN onto a to-many MULTIPLIES the parent — a SKU with nine movements comes back nine times —
    and `distinct()` is what folds it back to the thing `skus_that_have_moved` asks for. `include`
    would load the children, which is a different question and a much bigger answer.
    """
    return (
        SnakeQuery(Stock)
        .join(Stock.movements)
        .distinct()
        .order_by(Stock.sku.name.asc())
    )


def moved_sku_columns() -> tuple[SnakeValue[int], SnakeValue[str]]:
    """FRAGMENT: the two projected columns of `skus_that_have_moved`, in call order. NOT executed."""
    return (Stock.sku_id, Stock.sku.name)


def skus_that_have_moved(session: SnakeSession) -> list[tuple[int, str]]:
    """The distinct SKUs with at least one movement: an explicit JOIN, folded back with DISTINCT.

    It is deliberately NOT the same question as `busy_skus` above. This one is a set —what has ever
    moved— and that one is a ranking; a report that shows both says "nine of the ten SKUs have moved,
    and four of them move often", which is the sentence a replenishment meeting actually starts from.

    The alternative shape is `Sku.stock.any()`, an EXISTS, and it is better whenever the child's
    columns are not wanted. Here they are not, so the honest reason to write the JOIN is that a
    demo which never multiplies rows never shows what folding them back is for.
    """
    rows = session.select(moved_stock(), *moved_sku_columns())
    return [(int(sku_id), name) for sku_id, name in rows]


# How many movements back a "lately" figure looks. THREE, so the window is three rows wide counting
# the current one — the shortest span where a moving total can visibly disagree with a running one,
# which is the entire reason both are on the page.
MOVING_WINDOW = 3


def movement_trail(*, limit: int = 20) -> SnakeQuery[StockMovement]:
    """FRAGMENT: the most recent movements, newest last, bounded to a page. NOT executed.

    The `limit` bounds the PAGE and not the windows, exactly as `ranked_stock` explains: SQL computes
    a window before it applies LIMIT, so the totals below are the real ones even when only part of the
    series is shown.

    Ordered by `happened_at` and then by `id`, and the second key is not decoration: several receipts
    of one unit land in the same second, and a series whose order is decided by the engine would
    compute a different running total on two runs of the same query.
    """
    return (
        SnakeQuery(StockMovement)
        .order_by(StockMovement.happened_at.asc(), StockMovement.id.asc())
        .limit(limit)
    )


def _pair_series() -> tuple[tuple[SnakeValue[int], ...], tuple[SnakeOrder, ...]]:
    """The PARTITION and the ORDER every figure in the trail is measured over.

    Written once because the running total and the moving one have to agree on what a series IS.
    Two hand-written copies of a partition is how one of them ends up measuring across SKUs.
    """
    return (
        (StockMovement.stock_warehouse_id, StockMovement.stock_sku_id),
        (StockMovement.happened_at.asc(), StockMovement.id.asc()),
    )


def running_units() -> SnakeValue[int | None]:
    """FRAGMENT: how much this pair had moved in TOTAL by this row. The default frame.

    With an `ORDER BY` and no frame, SQL looks from the start of the partition to the current row,
    which is the accumulated figure. It is one useful answer, and until `snake_rows` existed it was
    the only one the ORM could ask for.
    """
    partition, order = _pair_series()
    return sum_(StockMovement.delta).over(partition_by=partition, order_by=order)


def moving_units() -> SnakeValue[int | None]:
    """FRAGMENT: how much this pair has moved LATELY — the last three movements, this one included.

    THE FRAME IS THE WHOLE DIFFERENCE. `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` is a window that
    travels with the row instead of growing behind it, and on the fourth movement of a series the two
    figures part company for good. Without it the rows had to be brought to Python and added up
    there, which is the trade this layer exists to refuse.

    `ROWS` and not `RANGE`: the span is counted in MOVEMENTS, and two receipts landing in the same
    second are two movements. `RANGE` would fold them into one step and quietly widen the window.
    """
    partition, order = _pair_series()
    return sum_(StockMovement.delta).over(
        partition_by=partition,
        order_by=order,
        frame=snake_rows(snake_preceding(MOVING_WINDOW - 1), SNAKE_CURRENT_ROW),
    )


def movement_trail_columns() -> tuple[
    SnakeValue[str], SnakeValue[int], SnakeValue[int | None], SnakeValue[int | None]
]:
    """FRAGMENT: the four values the trail projects, in ONE statement. NOT executed.

    Both totals travel with the movement they belong to. Asking for them apart would be two passes
    over the same rows to answer two halves of one sentence.

    FOUR AND NOT FIVE, and the missing one is the timestamp. `session.select` is typed by overload up
    to four columns; a fifth falls off the typed path, and in a project whose rule is zero `Any` that
    is not a trade worth making for a date the rows are already ORDERED by. What the page is about is
    the two totals side by side.
    """
    return (
        StockMovement.stock.sku.name,
        StockMovement.delta,
        running_units(),
        moving_units(),
    )


def movement_trail_rows(
    session: SnakeSession, *, limit: int = 20
) -> list[tuple[str, int, int, int]]:
    """The recent movements, each with what the pair had moved in total and what it moved lately."""
    rows = session.select(movement_trail(limit=limit), *movement_trail_columns())
    return [
        (name, int(delta), int(running or 0), int(moving or 0))
        for name, delta, running, moving in rows
    ]


# ---- The movement book: two origins, and a duplicate that is a fact ---------------------------------


def ledger_lines(
    reasons: Sequence[MovementReason], *, size: int
) -> SnakeQuery[StockLedger]:
    """FRAGMENT: the last `size` lines written by ONE origin. NOT executed.

    `defer(StockLedger.id)` is the line that matters. Over `stock_movements` it is refused — a row
    that can be written back keeps its key — and what comes back is unique by construction. Over the
    read-only view there is no key to preserve, so this returns the LINE a book prints: what moved,
    where, how much, why and when.
    """
    return (
        SnakeQuery(StockLedger)
        .filter(StockLedger.reason.in_(reasons))
        .defer(StockLedger.id)
        .order_by(StockLedger.happened_at.desc())
        .limit(size)
    )


def book_branches(
    size: int,
) -> tuple[SnakeQuery[StockLedger], SnakeQuery[StockLedger]]:
    """FRAGMENT: the book's two origins, each bounded on its OWN. NOT executed.

    The separate bounds are what stop this being an `OR`: one `WHERE` with one `LIMIT` over the lot
    would print a busy day's shipments and no delivery at all, and a bound that belongs to a sort is
    not a condition any filter can express.
    """
    return ledger_lines(SHOP_REASONS, size=size), ledger_lines(FLOOR_REASONS, size=size)


def book_compound(size: int) -> SnakeCompound[StockLedger]:
    """FRAGMENT: the two origins as ONE `UNION ALL`, NOT executed.

    `union_all` AND NOT `union`, and it is the opposite call from `order_highlights`. There a
    duplicate is one order matched by both criteria and the answer wants it once. Here a duplicate is
    two units leaving at one instant — two shipments — and folding them loses a unit of stock the
    book can no longer account for. The lines carry no identity, so SQL genuinely would fold them.

    Only emittable where the dialect answers `Full` to `PARENTHESISED_COMPOUND`, because the branches
    keep their own bounds; `movement_book` asks before building it.
    """
    shop, floor = book_branches(size)
    return shop.union_all(floor).order_by(StockLedger.happened_at.desc())


def fold_book(shop: list[StockLedger], floor: list[StockLedger]) -> list[StockLedger]:
    """The SQLite path's second half: the two bounded origins merged as the `UNION ALL` would.

    A CONCATENATION and never a set. `fold_highlights` folds duplicates away because its compound is
    a `UNION`; doing that here would put the deduplication back on the one engine that cannot run the
    compound, and the book would say different things depending on where the demo is pointed.
    """
    return sorted([*shop, *floor], key=lambda line: line.happened_at, reverse=True)


def movement_book(session: SnakeSession, *, size: int = BOOK_SIZE) -> list[StockLedger]:
    """The book: the last `size` lines of each origin, duplicates kept because they are events.

    One statement where the engine takes parentheses around a bounded branch, two and a fold where it
    does not — the same declared, bounded degradation `order_highlights` takes, and for the same
    reason: dropping the branch bounds would make every engine run the query SQLite can run instead
    of the one the question asks.
    """
    if session.dialect.supports_parenthesised_compound:
        return session.all(book_compound(size))
    shop, floor = book_branches(size)
    return fold_book(session.all(shop), session.all(floor))
