"""orders domain — SELECTORS: reads over the orders, their lines and the report they feed.

Every framework re-exports them from `apps/orders/selectors.py`.

FRAGMENTS FIRST, AND THIS TIME FOR A REASON WITH A DATE ON IT. Wherever it is natural, the read is
split in two: a function that BUILDS a `SnakeQuery` and does not run it, and a thin one that runs it.
`blog_selectors.published` is the idiom and `inventory_selectors.stock_listing` is the recent
example; here it is deliberate policy for the whole module.

The reason is phase 5. FastAPI goes async over THIS layer, and the seam the ORM was built on is
colourless: building SQL executes nothing, so a query has no colour and can be handed to whichever
session is at hand. A fragment therefore serves an `AsyncSession` unchanged — `await session.all(q)`
instead of `session.all(q)` — while a selector that runs the statement inside itself can only be
served by copying the domain logic into a second module that will drift from the first. The fragment
costs nothing today and is the whole difference between adding a session and duplicating a domain.

The second reason is the older one, and it already bit: a listing is consumed TWICE for the same page
— once counted and once fetched — and those two have to be the same question. Building the filter in
each of them is how a pager ends up saying "47 rows" over a listing that shows a different 47.

WHERE THE LOCKING READ LIVES, and why it is not here. `reserve` and `settle` lock STOCK rows, and a
stock row belongs to `inventory`: the lock is taken by `inventory_selectors.lock_stock`, which is the
module that owns the table. Putting it here because the orders operations are its only callers would
have made this module write SQL against somebody else's rows, and the next domain that needs to
reserve stock would have found it in the wrong place or written a second one.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from decimal import Decimal

from snakeorm import (
    SnakeCompound,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    SnakeValue,
    count,
    row_number,
    string_agg,
    sum_,
)

from shared.models import CustomerOrders, Order, OrderLine, OrderState, User

# ONE number for both exports, and it is imported rather than declared again. `inventory` owns it
# because its export was written first; what matters is that the two streams cannot end up disagreeing
# about how much of a result travels at a time, which is the sort of difference nobody notices until
# one of the two pages is the slow one.
from shared.selectors.inventory_selectors import EXPORT_CHUNK as EXPORT_CHUNK


def in_state(query: SnakeQuery[Order], state: OrderState) -> SnakeQuery[Order]:
    """FRAGMENT: narrows any order query to one state. Takes a query, returns another one.

    It needs no new machinery: `filter()` already returns `SnakeQuery[Order]`, so fragments stack
    and the parameter of the generic survives the whole chain — which is what lets the caller keep
    ordering, paging and including afterwards without the type turning into `Any`.
    """
    return query.filter(Order.state == state)


def of_customer(query: SnakeQuery[Order], customer_id: int) -> SnakeQuery[Order]:
    """FRAGMENT: narrows any order query to one customer's orders."""
    return query.filter(Order.customer_id == customer_id)


def order_listing(
    *, state: OrderState | None = None, customer_id: int | None = None
) -> SnakeQuery[Order]:
    """FRAGMENT: the ordered order query a listing pages through, optionally narrowed.

    NOT executed and carrying no `limit`, because the page consumes it twice: `count_orders` and
    `orders_page` both start from this one call, so the pager's total and the rows on screen cannot
    be answering different questions.

    Most recent first, and the id as the tiebreaker. `placed_at` alone is not a stable order — the
    seeder can and does place two orders in the same second — and an unstable order under
    LIMIT/OFFSET does not fail, it shows one row twice and skips another.
    """
    query = SnakeQuery(Order).order_by(Order.placed_at.desc(), Order.id.desc())
    if state is not None:
        query = in_state(query, state)
    if customer_id is not None:
        query = of_customer(query, customer_id)
    return query


def with_parties(query: SnakeQuery[Order]) -> SnakeQuery[Order]:
    """FRAGMENT: loads the three cross-domain to-ones an order page always shows.

    Customer (`accounts`), warehouse (`inventory`) and invoice (`billing`), which is the whole point
    of this domain existing. All three are to-one, so they are LEFT JOINs on the SAME statement and
    the page costs one query whether it lists three orders or three hundred.

    It is a fragment and not a fixed part of `order_listing` because the count does not want them:
    `COUNT(*)` over three needless LEFT JOINs is the same number, more slowly.
    """
    return query.include(Order.customer, Order.warehouse, Order.invoice)


def list_orders(
    session: SnakeSession, *, state: OrderState | None = None
) -> list[Order]:
    """Every order with its three parties loaded: ONE statement, no N+1."""
    return session.all(with_parties(order_listing(state=state)))


def count_orders(
    session: SnakeSession,
    *,
    state: OrderState | None = None,
    customer_id: int | None = None,
) -> int:
    """How many orders the listing has, for the pager. `COUNT(*)` over the SAME fragment.

    The total is not `len(rows)`: that is the size of the page. This is the second of the listing's
    two statements and the reason the fragment above is not executed where it is built.
    """
    return session.count(order_listing(state=state, customer_id=customer_id))


def orders_page(
    session: SnakeSession,
    *,
    state: OrderState | None = None,
    customer_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Order]:
    """One page of orders with the three parties loaded: ONE statement, whatever the page size."""
    return session.all(
        with_parties(order_listing(state=state, customer_id=customer_id))
        .limit(limit)
        .offset(offset)
    )


def order_by_id(order_id: int) -> SnakeQuery[Order]:
    """FRAGMENT: one order by id, bare, NOT executed. What a WRITE path wants."""
    return SnakeQuery(Order).filter(Order.id == order_id)


def get_order(session: SnakeSession, order_id: int) -> Order | None:
    """One order by id, bare. What a WRITE path wants: the row, not the rows it points at."""
    return session.first(order_by_id(order_id))


def order_with_parties_by_id(order_id: int) -> SnakeQuery[Order]:
    """FRAGMENT: one order with its three parties loaded, NOT executed. What a PAGE wants."""
    return with_parties(SnakeQuery(Order)).filter(Order.id == order_id)


def get_order_with_parties(session: SnakeSession, order_id: int) -> Order | None:
    """One order WITH its customer, warehouse and invoice already loaded, or None.

    The bare `get_order` above is for writes. This one is what a PAGE wants, and the difference is a
    whole class of bug: a template printing `order.customer.username` off the bare row fires a query
    while it renders, in the one layer where nothing counts queries.
    """
    return session.first(order_with_parties_by_id(order_id))


def order_by_reference(reference: str) -> SnakeQuery[Order]:
    """FRAGMENT: one order by the reference a human quotes, NOT executed. Unique, so it is a seek."""
    return SnakeQuery(Order).filter(Order.reference == reference)


def get_order_by_reference(session: SnakeSession, reference: str) -> Order | None:
    """One order by the reference a human quotes. Unique, so it is a seek, and it is how the
    duplicate is caught before the insert turns it into a driver error."""
    return session.first(order_by_reference(reference))


def orders_with_lines_query(customer_id: int) -> SnakeQuery[Order]:
    """FRAGMENT: a customer's orders with each order's lines included, NOT executed."""
    return order_listing(customer_id=customer_id).include(Order.lines)


def orders_with_lines(session: SnakeSession, customer_id: int) -> list[Order]:
    """A customer's orders with each order's lines loaded: ONE extra statement, not one per order.

    The select-in over `Order.lines` binds one placeholder per parent here, unlike the inventory's
    to-many: the foreign key of a LINE is single-column (`order_id`) even though the line's own
    identity is a pair. Which is the useful half of the lesson — a composite PRIMARY key does not
    make every relationship that touches the table composite.
    """
    return session.all(orders_with_lines_query(customer_id))


def lines_of(order_id: int) -> SnakeQuery[OrderLine]:
    """FRAGMENT: an order's lines, ordered, NOT executed.

    Ordered by `sku_id`, which is the half of the composite key that varies inside one order. The
    other half is fixed by the filter, so ordering by it would sort nothing.
    """
    return (
        SnakeQuery(OrderLine)
        .filter(OrderLine.order_id == order_id)
        .order_by(OrderLine.sku_id.asc())
    )


def lines_of_order(session: SnakeSession, order_id: int) -> list[OrderLine]:
    """An order's lines with the SKU loaded: ONE statement, so a template can print names for free."""
    return session.all(lines_of(order_id).include(OrderLine.sku))


def bare_lines_of_order(session: SnakeSession, order_id: int) -> list[OrderLine]:
    """An order's lines WITHOUT the SKU loaded: what an OPERATION walks, as opposed to a page.

    The sibling above includes `OrderLine.sku` because a template prints names. An operation prints
    nothing: `reserve` and `settle` want the pair `(sku_id, quantity)` and would pay a second
    statement for a catalogue they never read. Same fragment underneath, so the ORDER is the same
    one — which matters more than it looks, because that order is what the row locks are taken in.
    """
    return session.all(lines_of(order_id))


def line_by_key(order_id: int, sku_id: int) -> SnakeQuery[OrderLine]:
    """FRAGMENT: one line by its COMPOSITE key, NOT executed. Both halves are the identity."""
    return SnakeQuery(OrderLine).filter(
        OrderLine.order_id == order_id, OrderLine.sku_id == sku_id
    )


def get_line(session: SnakeSession, order_id: int, sku_id: int) -> OrderLine | None:
    """One line by its COMPOSITE key. Both halves are the identity; neither alone is.

    Neither argument has a default, and that is not ceremony: with one order in the database a
    look-up that quietly dropped `order_id` finds the right row, and it only breaks once there is a
    second customer — which is to say, in front of somebody.
    """
    return session.first(line_by_key(order_id, sku_id))


def count_lines_of(session: SnakeSession, order_id: int) -> int:
    """How many lines hang off an order. A COUNT, not a fetch.

    The delete confirmation has to say what would be dragged along, and `len(lines_of_order(...))`
    is the version that works on the demo seed and loads every line of the order somebody would
    actually want to delete.
    """
    return session.count(lines_count_query(order_id))


def lines_count_query(order_id: int) -> SnakeQuery[OrderLine]:
    """FRAGMENT: the lines of an order with no ordering, NOT executed. What a COUNT walks."""
    return SnakeQuery(OrderLine).filter(OrderLine.order_id == order_id)


def orders_per_state(session: SnakeSession) -> list[tuple[OrderState, int, Decimal]]:
    """One row per state with how many orders and how much money: `GROUP BY` + COUNT + SUM.

    It is NOT a `@snake_result`, and that is a limit of the shape rather than an oversight: a
    `@snake_result` is a row of a MODEL plus its scalars, and there is no state table to be the row.
    What is grouped by here is a VALUE, so the answer is tuples.

    Which is why the money is rebuilt by hand below, and the reason is worth writing down because it
    was measured rather than assumed. A summed `Decimal` does NOT come back as a `Decimal` on SQLite,
    and not through either path: SQLite stores a `Decimal` as TEXT, its `SUM` therefore hands back a
    float, and the coercion deliberately refuses to build a `Decimal` out of a float — going through
    binary floating point is the precise thing a `Decimal` exists to avoid, so passing the float
    through untouched is the honest failure instead of a silent corruption. `customer_orders` right
    underneath declares `ordered_total: Decimal` on a `@snake_result` and gets the same float on this
    engine. On Postgres both are exact: `SUM(NUMERIC)` is `NUMERIC` and the driver returns a
    `Decimal`.

    So this rebuild is not a workaround for the tuple shape, it is this module refusing to hand out
    a money value whose type depends on which engine answered. `Decimal(str(...))` and not
    `Decimal(...)` on the float, for the same reason the converter refuses: building one straight
    from a float carries the binary error into the exact type and hides it behind seventeen digits.
    """
    state_col, orders_col, total_col = per_state_columns()
    return to_state_totals(
        session.select(per_state_query(), state_col, orders_col, total_col)
    )


def per_state_query() -> SnakeQuery[Order]:
    """FRAGMENT: the orders grouped by state, ordered, NOT executed."""
    return SnakeQuery(Order).group_by(Order.state).order_by(Order.state.asc())


def per_state_columns() -> tuple[
    SnakeValue[OrderState], SnakeValue[int], SnakeValue[Decimal | None]
]:
    """FRAGMENT: the three columns `orders_per_state` projects (state, count, sum)."""
    return (Order.state, count(), sum_(Order.total))


def to_state_totals(
    rows: Sequence[tuple[OrderState, int, Decimal | None]],
) -> list[tuple[OrderState, int, Decimal]]:
    """The engine's answer turned into the module's: the money rebuilt EXACTLY, once.

    Shared by both colours rather than written twice, and that is not tidiness. What this does is the
    `Decimal(str(...))` rebuild `orders_per_state` spends a paragraph justifying — a rule about the
    TYPE of money that one of the two copies would eventually be written without, and the difference
    would be a float on one demo and a `Decimal` on the other, out of the same database.
    """
    return [
        (state, int(orders), Decimal("0") if total is None else Decimal(str(total)))
        for state, orders, total in rows
    ]


def customer_orders(session: SnakeSession) -> list[CustomerOrders]:
    """Every customer with how many orders they placed and for how much, typed, in ONE statement.

    Two correlated aggregates over the inverse side, projected into `CustomerOrders`: no dict of
    `object` and no second query per customer.

    `ordered_total` is declared `Decimal` and arrives as one on Postgres. On SQLite it arrives as a
    float, for the reason spelled out in `orders_per_state` above — that is the type being DEGRADED
    by the engine, which the dialect already warns about when the session opens, not the declaration
    being wrong. The value is exact either way; what varies is whether the engine has the type.
    """
    return session.annotate(
        customer_orders_query(), CustomerOrders, **customer_orders_aggregates()
    )


def customer_orders_query() -> SnakeQuery[User]:
    """FRAGMENT: the customers `customer_orders` annotates, in a stable order, NOT executed."""
    return SnakeQuery(User).order_by(User.id.asc())


def customer_orders_aggregates() -> dict[
    str, SnakeValue[int] | SnakeValue[Decimal | None]
]:
    """FRAGMENT: the two correlated aggregates `customer_orders` projects onto `CustomerOrders`."""
    return {
        "order_count": User.orders.count(),
        "ordered_total": User.orders.sum_(Order.total),
    }


def customers_with_orders(session: SnakeSession) -> list[User]:
    """Users who have ordered AT LEAST once: a correlated EXISTS, it does not multiply rows.

    The join version returns one row per order and needs a `DISTINCT` to undo the damage; the EXISTS
    stops at the first match and never multiplies anything to begin with.
    """
    return session.all(
        SnakeQuery(User).filter(User.orders.any()).order_by(User.id.asc())
    )


def skus_ordered_from(warehouse_id: int) -> SnakeQuery[OrderLine]:
    """FRAGMENT: every line of every order shipping from one warehouse, NOT executed.

    It resolves the two hops with a SUBQUERY and not with two round trips: `as_scalar` projects the
    ids of that warehouse's orders and `OrderLine.order_id.in_(...)` consumes them. Pulling the ids
    into Python would make the second statement carry one parameter per order, which grows with the
    data until it hits the engine's placeholder ceiling.

    This is what phase 3's reservation walks: the lines to take units out of, before anything locks.
    """
    placed = (
        SnakeQuery(Order).filter(Order.warehouse_id == warehouse_id).as_scalar(Order.id)
    )
    return SnakeQuery(OrderLine).filter(OrderLine.order_id.in_(placed))


def lines_to_export(state: OrderState | None = None) -> SnakeQuery[OrderLine]:
    """FRAGMENT: every order line, in order-and-SKU order, carrying the names it prints. NOT run.

    The biggest table this domain has, which is why it is the one that gets exported: an export page
    written over a table that fits in memory proves nothing about streaming.

    THREE to-one hops and no others, because `iterate()` allows nothing else. Two of the three are
    reached THROUGH the order (`order.customer`, `order.warehouse`), which is a two-step to-one path
    and still costs nothing extra — every one of them is a LEFT JOIN on the same SELECT. The order in
    which they are asked for does not matter; that they are all to-one does.

    The order is the composite key of the line, both halves: `order_id` groups an order's lines
    together in the file, and `sku_id` is the half that varies inside one order. Ordering by the
    order alone would leave the lines of one order in whatever order the engine felt like, which is
    exactly the instability that makes two exports of unchanged data look different.
    """
    query = (
        SnakeQuery(OrderLine)
        .include(OrderLine.order.customer, OrderLine.order.warehouse, OrderLine.sku)
        .order_by(OrderLine.order_id.asc(), OrderLine.sku_id.asc())
    )
    if state is not None:
        # The state lives on the ORDER, so narrowing the LINES by it is a navigation the emitter
        # turns into a condition on the joined order. Filtering in the writer would pull every line
        # of every state out of the database to throw most of them away.
        query = query.filter(OrderLine.order.state == state)
    return query


def stream_order_lines(
    session: SnakeSession,
    *,
    state: OrderState | None = None,
    chunk: int = EXPORT_CHUNK,
) -> Iterator[OrderLine]:
    """The lines one at a time, without the result ever existing whole. `return`, never `yield`.

    Same reason as `inventory_selectors.stream_movements`, and it is worth repeating rather than
    cross-referencing because it is the one line of this module a future rewrite could get wrong
    without noticing: written as a generator, the body would not run until the first row was asked
    for, and `iterate`'s refusal of an unstreamable query would surface far from the call that built
    it.
    """
    return session.iterate(lines_to_export(state), chunk=chunk)


def repeat_customers(
    session: SnakeSession, *, minimum_orders: int = 2
) -> list[tuple[str, int, Decimal]]:
    """Customers who have ordered AT LEAST `minimum_orders` times, with the count and the money. GROUP BY + HAVING.

    The aggregate filtered by its own aggregate. `WHERE` cannot express this at all: how many orders
    a customer has placed does not exist until the orders are grouped, so there is nothing for a
    row-by-row condition to look at. `HAVING COUNT(*) >= n` is the only way to ask it, and it is one
    statement over one JOIN.

    THE THRESHOLD IS ON THE COUNT AND NOT ON THE MONEY, and that is a portability decision with a
    measurement behind it. `Order.total` is a `NUMERIC` on Postgres and a TEXT on SQLite, so
    `HAVING SUM(total) >= 100` compares a float against a bound on one engine and text against text
    on the other — and the SQLite answer is not merely different, it is silently empty. A count is an
    integer everywhere, so the same page answers the same question on all three engines.

    The money still travels, it is just not what filters. It is rebuilt through `Decimal(str(...))`
    for the reason `orders_per_state` sets out at length: a summed `Decimal` comes back as a float on
    SQLite, and building a `Decimal` straight from a float carries the binary error into the exact
    type instead of stopping at it.
    """
    name_col, placed_col, spent_col = repeat_customers_columns()
    return to_customer_totals(
        session.select(
            repeat_customers_query(minimum_orders=minimum_orders),
            name_col,
            placed_col,
            spent_col,
        )
    )


def repeat_customers_query(*, minimum_orders: int = 2) -> SnakeQuery[Order]:
    """FRAGMENT: the orders grouped by customer and filtered by their own COUNT, NOT executed."""
    return (
        SnakeQuery(Order)
        .group_by(Order.customer.username)
        .having(count() >= minimum_orders)
        .order_by(Order.customer.username.asc())
    )


def repeat_customers_columns() -> tuple[
    SnakeValue[str], SnakeValue[int], SnakeValue[Decimal | None]
]:
    """FRAGMENT: the three columns `repeat_customers` projects (username, count, sum)."""
    return (Order.customer.username, count(), sum_(Order.total))


def to_customer_totals(
    rows: Sequence[tuple[str, int, Decimal | None]],
) -> list[tuple[str, int, Decimal]]:
    """The same money rebuild as `to_state_totals`, over the rows keyed by a name instead of a state."""
    return [
        (username, int(placed), Decimal("0") if spent is None else Decimal(str(spent)))
        for username, placed, spent in rows
    ]


def order_sequence(
    session: SnakeSession, *, limit: int = 20
) -> list[tuple[str, str, SnakeUtc, int]]:
    """The most recent orders, each saying WHICH of that customer's orders it is. A WINDOW function.

    `ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY placed_at)` turns a listing into something
    a listing cannot be: every row keeps its own identity AND carries a fact about its neighbours.
    "This is Ana's first order" and "this is Ana's ninth" are the difference between a new customer
    and a regular, and neither a `GROUP BY` (which would collapse Ana into one row) nor a `filter`
    (which cannot see other rows) can put that number on the line.

    `row_number()` and not `rank()` here, and the choice is the opposite of the one `stock_ranking`
    makes: there are no ties to respect, because a customer's orders are strictly ordered in time
    and two of them landing in the same second is a tie that has to be broken anyway. The id breaks
    it, which makes the sequence stable across runs.

    The `limit` bounds what is SHOWN. The window is computed before it, so an order that is the
    ninth of its customer says nine even when the other eight are not on the page.
    """
    reference_col, username_col, placed_col, position_col = order_sequence_columns()
    return to_order_sequence(
        session.select(
            order_sequence_query(limit=limit),
            reference_col,
            username_col,
            placed_col,
            position_col,
        )
    )


def order_sequence_query(*, limit: int = 20) -> SnakeQuery[Order]:
    """FRAGMENT: the most recent orders, bounded, NOT executed. The window is computed before this cut."""
    return (
        SnakeQuery(Order).order_by(Order.placed_at.desc(), Order.id.desc()).limit(limit)
    )


def order_sequence_columns() -> tuple[
    SnakeValue[str], SnakeValue[str], SnakeValue[SnakeUtc], SnakeValue[int]
]:
    """FRAGMENT: the four columns `order_sequence` projects, the last one a WINDOW function."""
    return (
        Order.reference,
        Order.customer.username,
        Order.placed_at,
        row_number().over(
            partition_by=(Order.customer_id,),
            order_by=(Order.placed_at.asc(), Order.id.asc()),
        ),
    )


def to_order_sequence(
    rows: Sequence[tuple[str, str, SnakeUtc, int]],
) -> list[tuple[str, str, SnakeUtc, int]]:
    """The window's position as an `int`. Engines disagree on the type a `ROW_NUMBER()` comes back as."""
    return [
        (reference, username, placed_at, int(position))
        for reference, username, placed_at, position in rows
    ]


def highlight_branches(size: int) -> tuple[SnakeQuery[Order], SnakeQuery[Order]]:
    """FRAGMENTS: the `size` biggest orders and the `size` most recent ones, separately. NOT run.

    They are handed out as a pair because the two ways of asking them —one `UNION`, or two round
    trips— have to be asking the SAME two questions. `order_highlights` below picks the way; this
    picks the questions, once.
    """
    biggest = (
        SnakeQuery(Order).order_by(Order.total.desc(), Order.id.desc()).limit(size)
    )
    newest = (
        SnakeQuery(Order).order_by(Order.placed_at.desc(), Order.id.desc()).limit(size)
    )
    return biggest, newest


def order_highlights(session: SnakeSession, *, size: int = 5) -> list[Order]:
    """The orders worth looking at: the biggest ones and the newest ones, as ONE deduplicated list.

    THIS IS WHY THE COMPOUND IS NOT A BOX TICKED. Almost every `UNION` over one table is really an
    `OR` in disguise — two filters on the same rows fold into one `WHERE` and the set operator buys
    nothing. This one does not fold, and the reason is the `LIMIT` inside each branch: "the five
    biggest" and "the five newest" are two different orderings, each cut at five, and no single
    `WHERE` can express a bound that belongs to a sort. The deduplication is the other half — an
    order that is both the biggest and the newest is ONE row of the answer, and `UNION` (not
    `UNION ALL`) is what makes it one.

    AND THIS IS WHERE THE ENGINES DISAGREE, so the capability is ASKED rather than assumed — the same
    bargain `inventory_selectors.lock_stock` strikes for row locking, and for the same reason. A
    branch keeps its own `LIMIT` only inside PARENTHESES, and SQLite rejects parentheses around the
    branches of a compound: it answers `Cap.PARENTHESISED_COMPOUND` with `Nope`, and the emitter
    raises rather than emitting a bound that would quietly become the whole set's. Postgres and MySQL
    both answer `Full`.

    So on two engines out of three this page is ONE statement, and on SQLite it is two and a fold in
    Python. What is NOT allowed is the third option — dropping the branch limits so the compound
    emits everywhere — because that would make every engine run the query SQLite can run rather than
    the one the question wants. The degradation is declared, bounded and visible in the query count;
    it is not smuggled into the SQL.

    A compound loads no relationships (`has_includes` is false by construction and an `include` on a
    branch is rejected at build time), so these orders arrive BARE. The report's row shape is built
    for that, and it is why the highlights show a reference and a total rather than a customer name.
    """
    if session.dialect.supports_parenthesised_compound:
        return session.all(highlights_compound(size))
    biggest, newest = highlight_branches(size)
    return fold_highlights(session.all(newest), session.all(biggest))


def highlights_compound(size: int) -> SnakeCompound[Order]:
    """FRAGMENT: the two branches as ONE deduplicated `UNION`, NOT executed.

    Only emittable where the dialect answers `Full` to `PARENTHESISED_COMPOUND`; `order_highlights`
    and its asynchronous twin both ask before building it, which is why the question lives at the
    call site and not in here.
    """
    biggest, newest = highlight_branches(size)
    return biggest.union(newest).order_by(Order.placed_at.desc(), Order.id.desc())


def fold_highlights(newest: list[Order], biggest: list[Order]) -> list[Order]:
    """The SQLite path's second half: two bounded branches merged in Python as the `UNION` would.

    Shared by both colours because it is the shape of the ANSWER, not a way of getting it. Written
    twice, the day one of them changed the sort would be the day the two demos showed different
    lists out of one database on the one engine that already takes the slower path.
    """
    seen: set[int] = set()
    folded: list[Order] = []
    for order in (*newest, *biggest):
        if order.id in seen:
            continue
        seen.add(order.id)
        folded.append(order)
    # Sorted by the SAME keys the compound sorts by, so the page does not change shape with the
    # engine. Without this the two halves would arrive concatenated rather than merged, and the
    # SQLite demo would show a list nobody else sees.
    folded.sort(key=lambda order: (order.placed_at, order.id), reverse=True)
    return folded


# What separates one SKU name from the next inside a basket cell. A constant rather than a literal at
# the call site: the separator is part of what the page LOOKS like, and a page that used ", " in one
# table and "," in another would be two decisions where there is one.
BASKET_SEPARATOR = ", "


def baskets_query() -> SnakeQuery[OrderLine]:
    """FRAGMENT: the lines of every order, folded to one row per order. NOT executed.

    Grouped on the order's REFERENCE rather than its id, and the two are not interchangeable here:
    the reference is what the page shows and what a person quotes on the phone. Grouping by the id
    and then fetching the reference would be a second read of the same rows.

    The navigation does the JOINs: `OrderLine.order.reference` and `OrderLine.sku.name` are two hops
    the planner resolves into the same statement, which is what keeps this one query rather than one
    per order.
    """
    return (
        SnakeQuery(OrderLine)
        .group_by(OrderLine.order.reference)
        .order_by(OrderLine.order.reference.asc())
    )


def baskets_columns() -> tuple[
    SnakeValue[str], SnakeValue[int], SnakeValue[str | None]
]:
    """FRAGMENT: an order's reference, how many lines it has and WHICH SKUs. NOT executed.

    THE `order_by` INSIDE THE AGGREGATE IS THE HALF THAT IS EASY TO FORGET and impossible to notice
    afterwards. Without it the engine concatenates the names in whatever order it happened to read
    the rows, so the same order can read `Gamma, Alpha, Beta` on one run and something else on the
    next — a value that changes without the data changing, which is worse than a wrong one because
    nothing looks broken.

    `string_agg` is spelled three ways by the three engines and the separator does not even travel
    the same way in them — a parameter on PostgreSQL and SQLite, the `SEPARATOR` keyword on MySQL,
    which rejects a placeholder there. That is the dialect's problem, and it is why this reads as one
    call.
    """
    return (
        OrderLine.order.reference,
        count(),
        string_agg(
            OrderLine.sku.name,
            BASKET_SEPARATOR,
            order_by=[OrderLine.sku.name.asc()],
        ),
    )


def order_baskets(session: SnakeSession) -> list[tuple[str, int, str]]:
    """Every order with its line count and its SKUs in ONE cell, from ONE statement.

    The alternative this replaces is the one worth naming: a second query for the lines plus a
    grouping pass in Python, or walking `order.lines` in a template — the N+1 that does not look like
    one because it looks like reading an attribute.
    """
    return [
        (reference, int(lines), skus or "")
        for reference, lines, skus in session.select(
            baskets_query(), *baskets_columns()
        )
    ]
