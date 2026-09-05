"""The demos' selectors and services, ALL of them executed.

Of the sixty-odd functions in `shared/selectors/` and `shared/services/`, only twenty-three were ever
run. Twelve of the fifteen modules that existed then had ZERO coverage: their endpoints exist and are
wired up in the three demos, but no suite hits them, and the three framework suites are 100% HTTP
over a handful of routes. Those figures are the state on the day this file was written, and both the
functions and the modules have grown since — the live numbers are the ones `_public_functions()`
walks, never these.

That turns 850 lines —which are the showcase of how this ORM is used— into code nobody has ever run.
That it compiles says nothing: `catalog.recent_comments` compiled perfectly and had never returned a
single row.

Two pieces, and the second one is what matters in the long run:

1. One invocation per function, against the seeded database.
2. A net that enumerates the functions FROM THE MODULES and demands that each one is invoked here. It
   is the same pattern as `test_emitter_dialect_matrix`, and for the same reason: a hand-written
   table falls short the day someone adds a function, and then coverage drops again without anybody
   noticing.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Sequence
from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from snakeorm import SnakeQuery, SnakeSession, SnakeUtc, count

from shared.models import (
    CustomerOrders,
    Delivery,
    MovementReason,
    Order,
    OrderLine,
    OrderState,
    PlanStats,
    Post,
    SkuKind,
    Stock,
    UserStats,
    WarehouseStats,
)
from shared.selectors import (
    accounts_selectors,
    inventory_selectors,
    orders_selectors,
    auth_selectors,
    billing_selectors,
    blog_selectors,
    catalog,
    content_selectors,
    engagement_selectors,
    logistics_selectors,
    taxonomy_selectors,
)
from shared.services import (
    accounts_services,
    inventory_services,
    orders_services,
    auth_services,
    billing_services,
    blog_services,
    content_services,
    engagement_services,
    logistics_services,
    taxonomy_services,
)


def _primer_id(rows: Sequence[object]) -> int:
    """The id of the first row, to chain calls over data that actually exists.

    The tests use REAL ids from the seed and not a bare `1`: a selector filtering on a nonexistent
    key returns an empty list and passes the test without having queried anything.
    """
    assert rows, "the seeding left no rows: the test would be measuring the void"
    return int(rows[0].id)  # type: ignore[attr-defined]


def _a_stock(session: SnakeSession) -> Stock:
    """The first seeded stock row. Its identity is a PAIR, so it cannot be fetched by a bare id."""
    rows = session.all(SnakeQuery(Stock).order_by(Stock.warehouse_id.asc()))
    assert rows, (
        "the seeding left no stock: the composite-key invocations would measure the void"
    )
    return rows[0]


def _untouched_stock(session: SnakeSession) -> Stock:
    """A stock row with no movements behind it: the only kind that can legitimately be deleted.

    The pair has to be NEW but both halves REAL — the seeder gives each warehouse half the catalogue,
    so an unpaired SKU exists — because `Stock` has a foreign key to each of them. An invented id
    fails on the insert instead of on the delete, which would be testing the wrong refusal.
    """
    warehouse_id = _a_stock(session).warehouse_id
    taken = {
        row.sku_id
        for row in session.all(
            SnakeQuery(Stock).filter(Stock.warehouse_id == warehouse_id)
        )
    }
    free = [
        sku.id for sku in inventory_selectors.list_skus(session) if sku.id not in taken
    ]
    assert free, (
        "every SKU is already in this warehouse: there is no unpaired one to delete"
    )
    fresh = session.add(
        Stock(
            warehouse_id=warehouse_id,
            sku_id=free[0],
            on_hand=0,
            counted_at=None,
            counted_local=None,
        )
    )
    session.commit()
    return fresh


def _an_order(session: SnakeSession) -> Order:
    """The first seeded order. Its lines are the second composite key in the repo, so it is the row
    every orders invocation below hangs off."""
    rows = session.all(SnakeQuery(Order).order_by(Order.id.asc()))
    assert rows, (
        "the seeding left no orders: the orders invocations would measure the void"
    )
    return rows[0]


def _a_line(session: SnakeSession) -> OrderLine:
    """A line of the first seeded order. Like `Stock`, its identity is a PAIR, so it cannot be
    fetched by a bare id and the invocations have to carry both halves."""
    rows = session.all(
        SnakeQuery(OrderLine)
        .filter(OrderLine.order_id == _an_order(session).id)
        .order_by(OrderLine.sku_id.asc())
    )
    assert rows, (
        "the first seeded order has no lines: the pair invocations would measure the void"
    )
    return rows[0]


def _a_post(session: SnakeSession) -> Post:
    """The first seeded post, for the one service that takes a model rather than an id.

    `is_owner` is a pure rule over a row that is already in hand, so it is the only entry in the
    table below that is not a query: it needs something to ask about, and asking the database for it
    keeps the invocation running against real data like every other one here.
    """
    post = session.first(blog_selectors.posts_query())
    assert post is not None
    return post


def _a_delivery(session: SnakeSession) -> Delivery:
    """The first seeded delivery, which every logistics invocation measures FROM.

    Its coordinates are what the distance fragments take, and that is why this exists rather than a
    bare pair of numbers: a point invented here would rank the depots around nowhere, come back with
    three rows and prove that the SQL parses. Measuring from a row the seeder actually wrote is what
    makes the invocation an exercise instead of a syntax check.
    """
    rows = session.all(SnakeQuery(Delivery).order_by(Delivery.id.asc()).limit(1))
    assert rows, (
        "the seeding left no deliveries: the logistics invocations would measure the void"
    )
    return rows[0]


def _an_empty_order(session: SnakeSession) -> Order:
    """An order with NO lines: the only kind that can legitimately be deleted.

    Every seeded order has lines —that is what an order is— and the foreign key refuses to orphan
    them. Making a fresh one here means the delete is testing the delete and not the refusal, which
    has its own test.
    """
    order = orders_services.create_order(
        session,
        reference="ORD-EMPTY",
        customer_id=_an_order(session).customer_id,
        warehouse_id=_an_order(session).warehouse_id,
        total=Decimal("0"),
    )
    session.commit()
    return order


# One invocation per public function. The key is `module.function`, the same name the net below
# enumerates, so the two cannot fall out of sync.
# A cutoff far enough ahead that every seeded invoice is behind it, so the ageing fragments come
# back with rows to prove they RAN. A cutoff of `now()` would make this file's coverage depend on
# what the seeder happened to date things, which is how a passing invocation stops proving
# anything.
_AGEING_CUTOFF = SnakeUtc(2100, 1, 1, 0, 0)


_INVOCATIONS: dict[str, Callable[[SnakeSession], object]] = {
    # --- selectors: accounts -------------------------------------------------------------------
    "accounts_selectors.list_roles": lambda s: accounts_selectors.list_roles(s),
    "accounts_selectors.get_role": lambda s: accounts_selectors.get_role(
        s, _primer_id(accounts_selectors.list_roles(s))
    ),
    "accounts_selectors.roles_of": lambda s: s.all(accounts_selectors.roles_of(1)),
    "accounts_selectors.roles_of_user": lambda s: accounts_selectors.roles_of_user(
        s, 1
    ),
    # --- selectors: auth -----------------------------------------------------------------------
    "auth_selectors.tokens_of_user": lambda s: auth_selectors.tokens_of_user(s, 1),
    "auth_selectors.active_of": lambda s: s.all(auth_selectors.active_of(1)),
    "auth_selectors.active_tokens": lambda s: auth_selectors.active_tokens(s, 1),
    "auth_selectors.sessions_of_user": lambda s: auth_selectors.sessions_of_user(s, 1),
    # --- selectors: billing --------------------------------------------------------------------
    "billing_selectors.list_plans": lambda s: billing_selectors.list_plans(s),
    "billing_selectors.subscriptions_of_user": lambda s: (
        billing_selectors.subscriptions_of_user(s, 1)
    ),
    "billing_selectors.customer_invoices": lambda s: (
        billing_selectors.customer_invoices(s, 1)
    ),
    "billing_selectors.invoices_of_customer": lambda s: s.all(
        billing_selectors.invoices_of_customer(1)
    ),
    "billing_selectors.invoices_of_subscription": lambda s: (
        billing_selectors.invoices_of_subscription(s, 1)
    ),
    "billing_selectors.get_invoice": lambda s: billing_selectors.get_invoice(
        s,
        _primer_id(
            billing_selectors.invoices_of_subscription(
                s, _primer_id(billing_selectors.subscriptions_of_user(s, 1))
            )
        ),
    ),
    "billing_selectors.get_subscription": lambda s: billing_selectors.get_subscription(
        s, _primer_id(billing_selectors.subscriptions_of_user(s, 1))
    ),
    "billing_selectors.unpaid_invoices": lambda s: billing_selectors.unpaid_invoices(s),
    "billing_selectors.invoice_listing": lambda s: s.all(
        billing_selectors.invoice_listing(paid=False)
    ),
    "billing_selectors.with_parties": lambda s: s.all(
        billing_selectors.with_parties(billing_selectors.invoice_listing()).limit(3)
    ),
    "billing_selectors.count_invoices": lambda s: billing_selectors.count_invoices(s),
    "billing_selectors.invoices_page": lambda s: billing_selectors.invoices_page(
        s, limit=3
    ),
    "billing_selectors.get_invoice_with_parties": lambda s: (
        billing_selectors.get_invoice_with_parties(
            s,
            _primer_id(
                billing_selectors.invoices_of_subscription(
                    s, _primer_id(billing_selectors.subscriptions_of_user(s, 1))
                )
            ),
        )
    ),
    "billing_selectors.payments_of": lambda s: billing_selectors.payments_of(
        s,
        _primer_id(
            billing_selectors.invoices_of_subscription(
                s, _primer_id(billing_selectors.subscriptions_of_user(s, 1))
            )
        ),
    ),
    "billing_selectors.plan_stats": lambda s: billing_selectors.plan_stats(s),
    "billing_selectors.revenue_by_plan": lambda s: billing_selectors.revenue_by_plan(s),
    "billing_selectors.unpaid_total": lambda s: billing_selectors.unpaid_total(s),
    # The ageing fragments. `due_date` and `collected_fraction` are VALUES rather than queries, so
    # they are exercised the only way a value can be: projected. Running them through `select` is
    # also the only thing that proves the engine accepts them — a fragment that merely builds is a
    # fragment nobody has asked a database about.
    "billing_selectors.due_date": lambda s: s.select(
        billing_selectors.overdue_query(_AGEING_CUTOFF), billing_selectors.due_date()
    ),
    "billing_selectors.collected_fraction": lambda s: s.select(
        billing_selectors.overdue_query(_AGEING_CUTOFF),
        billing_selectors.collected_fraction(),
    ),
    "billing_selectors.overdue_query": lambda s: s.all(
        billing_selectors.overdue_query(_AGEING_CUTOFF)
    ),
    "billing_selectors.overdue_columns": lambda s: s.select(
        billing_selectors.overdue_query(_AGEING_CUTOFF),
        *billing_selectors.overdue_columns(),
    ),
    "billing_selectors.overdue_ageing": lambda s: billing_selectors.overdue_ageing(
        s, _AGEING_CUTOFF
    ),
    # --- selectors: blog -----------------------------------------------------------------------
    "blog_selectors.list_posts": lambda s: blog_selectors.list_posts(s),
    "blog_selectors.list_user_posts": lambda s: blog_selectors.list_user_posts(s, 1),
    "blog_selectors.get_post": lambda s: blog_selectors.get_post(
        s, _primer_id(blog_selectors.list_posts(s))
    ),
    # The FRAGMENT is tested by stacking it, which is what it exists for: it takes a query, returns
    # another, and whoever runs it decides the ordering.
    "blog_selectors.published": lambda s: s.all(
        blog_selectors.published(SnakeQuery(Post)).order_by(Post.id.asc())
    ),
    "blog_selectors.published_posts": lambda s: blog_selectors.published_posts(s),
    "blog_selectors.get_user": lambda s: blog_selectors.get_user(s, 1),
    "blog_selectors.get_user_by_username": lambda s: (
        blog_selectors.get_user_by_username(s, "u1")
    ),
    "blog_selectors.user_stats": lambda s: blog_selectors.user_stats(s),
    # --- selectors: catalog --------------------------------------------------------------------
    "catalog.get_user": lambda s: catalog.get_user(s, 1),
    "catalog.list_posts_with_author": lambda s: catalog.list_posts_with_author(s),
    "catalog.published_posts": lambda s: catalog.published_posts(s),
    "catalog.active_tokens": lambda s: catalog.active_tokens(s, 1),
    "catalog.paginate_visits": lambda s: catalog.paginate_visits(s),
    "catalog.count_posts": lambda s: catalog.count_posts(s),
    "catalog.count_visits": lambda s: catalog.count_visits(s),
    "catalog.user_engagement": lambda s: catalog.user_engagement(s),
    "catalog.blog_overview": lambda s: catalog.blog_overview(s),
    "catalog.plan_adoption": lambda s: catalog.plan_adoption(s),
    "catalog.visits_per_post": lambda s: catalog.visits_per_post(s),
    "catalog.plan_for_visits_of_a_post": lambda s: catalog.plan_for_visits_of_a_post(
        s, 1
    ),
    "catalog.revenue_per_plan": lambda s: catalog.revenue_per_plan(s),
    "catalog.blogs_with_published_posts": lambda s: catalog.blogs_with_published_posts(
        s
    ),
    "catalog.recent_comments": lambda s: catalog.recent_comments(s),
    "catalog.users_without_subscription": lambda s: catalog.users_without_subscription(
        s
    ),
    "catalog.posts_for_tag": lambda s: catalog.posts_for_tag(
        s, _primer_id(taxonomy_selectors.list_tags(s))
    ),
    # --- selectors: scalar functions, computed IN the engine -------------------------------------
    #
    # `movements_by_date_part` comes back as a pair on purpose: two of the three engines have no
    # `EXTRACT`, so the refusal travels as DATA instead of as an exception. Calling it here checks
    # the whole return, refusal included, on whichever engine the suite is pointed at.
    "catalog.sku_name_case": lambda s: catalog.sku_name_case(s),
    "catalog.sku_name_edits": lambda s: catalog.sku_name_edits(s),
    "catalog.sku_magnitudes": lambda s: catalog.sku_magnitudes(s),
    "catalog.sku_attributes": lambda s: catalog.sku_attributes(s),
    "catalog.skus_matching_any_case": lambda s: catalog.skus_matching_any_case(s, "a"),
    "catalog.movements_by_date_part": lambda s: catalog.movements_by_date_part(s),
    # --- selectors: content --------------------------------------------------------------------
    "content_selectors.revisions_of_post": lambda s: (
        content_selectors.revisions_of_post(s, 1)
    ),
    "content_selectors.attachments_of_post": lambda s: (
        content_selectors.attachments_of_post(s, 1)
    ),
    # --- selectors: engagement -----------------------------------------------------------------
    "engagement_selectors.comments_of_post": lambda s: (
        engagement_selectors.comments_of_post(s, 1)
    ),
    "engagement_selectors.reactions_of_post": lambda s: (
        engagement_selectors.reactions_of_post(s, 1)
    ),
    "engagement_selectors.visits_of_post": lambda s: (
        engagement_selectors.visits_of_post(s, 1)
    ),
    # --- selectors: taxonomy -------------------------------------------------------------------
    "taxonomy_selectors.list_groups": lambda s: taxonomy_selectors.list_groups(s),
    "taxonomy_selectors.list_tags": lambda s: taxonomy_selectors.list_tags(s),
    "taxonomy_selectors.tags_of": lambda s: s.all(taxonomy_selectors.tags_of(1)),
    "taxonomy_selectors.tags_of_post": lambda s: taxonomy_selectors.tags_of_post(s, 1),
    # --- services: accounts --------------------------------------------------------------------
    "accounts_services.create_role": lambda s: accounts_services.create_role(
        s, "nuevo"
    ),
    "accounts_services.assign_role": lambda s: accounts_services.assign_role(
        s, 1, _primer_id(accounts_selectors.list_roles(s))
    ),
    "accounts_services.revoke_role": lambda s: accounts_services.revoke_role(
        s, 1, _primer_id(accounts_selectors.list_roles(s))
    ),
    # --- services: auth ------------------------------------------------------------------------
    "auth_services.issue_token": lambda s: auth_services.issue_token(
        s, 1, "tok-nuevo", SnakeUtc.now() + timedelta(days=1)
    ),
    "auth_services.revoke_token": lambda s: auth_services.revoke_token(
        s, _primer_id(auth_selectors.tokens_of_user(s, 1))
    ),
    "auth_services.open_login_session": lambda s: auth_services.open_login_session(
        s, 1, "10.0.0.1"
    ),
    # --- services: billing ---------------------------------------------------------------------
    "billing_services.subscribe": lambda s: billing_services.subscribe(
        s, 1, _primer_id(billing_selectors.list_plans(s))
    ),
    "billing_services.cancel_subscription": lambda s: (
        billing_services.cancel_subscription(
            s, _primer_id(billing_selectors.subscriptions_of_user(s, 1))
        )
    ),
    "billing_services.issue_invoice": lambda s: billing_services.issue_invoice(
        s, _primer_id(billing_selectors.subscriptions_of_user(s, 1)), 999
    ),
    "billing_services.pay_invoice": lambda s: billing_services.pay_invoice(
        s,
        _primer_id(
            billing_selectors.invoices_of_subscription(
                s, _primer_id(billing_selectors.subscriptions_of_user(s, 1))
            )
        ),
        "card",
    ),
    # --- services: blog ------------------------------------------------------------------------
    "blog_services.register_user": lambda s: blog_services.register_user(
        s, "nuevo", "nuevo@x.com", "secreto"
    ),
    "blog_services.authenticate": lambda s: blog_services.authenticate(
        s, "u1", "not-the-right-one"
    ),
    "blog_services.create_post": lambda s: blog_services.create_post(
        s, 1, 1, "titulo", "cuerpo"
    ),
    "blog_services.update_post": lambda s: blog_services.update_post(
        s, _primer_id(blog_selectors.list_posts(s)), 1, title="other"
    ),
    "blog_services.delete_post": lambda s: blog_services.delete_post(
        s, _primer_id(blog_selectors.list_posts(s)), 1
    ),
    # --- services: content ---------------------------------------------------------------------
    "content_services.add_revision": lambda s: content_services.add_revision(
        s, _primer_id(blog_selectors.list_posts(s)), "cuerpo revisado"
    ),
    "content_services.attach_file": lambda s: content_services.attach_file(
        s, _primer_id(blog_selectors.list_posts(s)), "f.pdf", "http://x/f.pdf", 10
    ),
    "content_services.remove_attachment": lambda s: content_services.remove_attachment(
        s,
        content_services.attach_file(
            s, _primer_id(blog_selectors.list_posts(s)), "g.pdf", "http://x/g", 1
        ).id,
    ),
    # --- services: engagement ------------------------------------------------------------------
    "engagement_services.add_comment": lambda s: engagement_services.add_comment(
        s, _primer_id(blog_selectors.list_posts(s)), 1, "un comentario"
    ),
    "engagement_services.add_reaction": lambda s: engagement_services.add_reaction(
        s, _primer_id(blog_selectors.list_posts(s)), 1, "like"
    ),
    "engagement_services.record_visit": lambda s: engagement_services.record_visit(
        s, _primer_id(blog_selectors.list_posts(s)), "10.0.0.2"
    ),
    # --- services: taxonomy --------------------------------------------------------------------
    "taxonomy_services.create_tag": lambda s: taxonomy_services.create_tag(
        s, "tag", _primer_id(taxonomy_selectors.list_groups(s))
    ),
    "taxonomy_services.tag_post": lambda s: taxonomy_services.tag_post(
        s,
        _primer_id(blog_selectors.list_posts(s)),
        _primer_id(taxonomy_selectors.list_tags(s)),
    ),
    "taxonomy_services.untag_post": lambda s: taxonomy_services.untag_post(
        s,
        _primer_id(blog_selectors.list_posts(s)),
        _primer_id(taxonomy_selectors.list_tags(s)),
    ),
    # --- selectors: inventory (the domain with a COMPOSITE key) --------------------------------
    "inventory_selectors.list_warehouses": lambda s: (
        inventory_selectors.list_warehouses(s, active_only=True)
    ),
    "inventory_selectors.get_warehouse": lambda s: inventory_selectors.get_warehouse(
        s, _a_stock(s).warehouse_id
    ),
    "inventory_selectors.list_skus": lambda s: inventory_selectors.list_skus(s),
    "inventory_selectors.get_sku": lambda s: inventory_selectors.get_sku(
        s, _a_stock(s).sku_id
    ),
    "inventory_selectors.with_at_least": lambda s: s.all(
        inventory_selectors.with_at_least(SnakeQuery(Stock), 1)
    ),
    "inventory_selectors.stock_of_warehouse": lambda s: (
        inventory_selectors.stock_of_warehouse(s, _a_stock(s).warehouse_id)
    ),
    "inventory_selectors.get_stock": lambda s: inventory_selectors.get_stock(
        s, _a_stock(s).warehouse_id, _a_stock(s).sku_id
    ),
    "inventory_selectors.get_stock_with_relations": lambda s: (
        inventory_selectors.get_stock_with_relations(
            s, _a_stock(s).warehouse_id, _a_stock(s).sku_id
        )
    ),
    # The FRAGMENT of the listing: it takes no session, so it is executed by stacking a limit onto
    # it, which is what the paginated page does with it.
    "inventory_selectors.stock_listing": lambda s: s.all(
        inventory_selectors.stock_listing(_a_stock(s).warehouse_id).limit(5)
    ),
    "inventory_selectors.count_stock_rows": lambda s: (
        inventory_selectors.count_stock_rows(s, warehouse_id=_a_stock(s).warehouse_id)
    ),
    "inventory_selectors.stock_rows_page": lambda s: (
        inventory_selectors.stock_rows_page(
            s, warehouse_id=_a_stock(s).warehouse_id, limit=5, offset=0
        )
    ),
    "inventory_selectors.count_movements_of": lambda s: (
        inventory_selectors.count_movements_of(
            s, _a_stock(s).warehouse_id, _a_stock(s).sku_id
        )
    ),
    "inventory_selectors.stock_with_movements": lambda s: (
        inventory_selectors.stock_with_movements(s, _a_stock(s).warehouse_id)
    ),
    "inventory_selectors.movements_of": lambda s: inventory_selectors.movements_of(
        s, _a_stock(s).warehouse_id, _a_stock(s).sku_id
    ),
    "inventory_selectors.skus_in_warehouse": lambda s: s.all(
        inventory_selectors.skus_in_warehouse(_a_stock(s).warehouse_id)
    ),
    "inventory_selectors.low_stock": lambda s: inventory_selectors.low_stock(s),
    "inventory_selectors.movement_book": lambda s: inventory_selectors.movement_book(s),
    # The book's four fragments, run one by one. `book_compound` is built and NOT executed on this
    # suite's SQLite: the branches keep their own bounds, which needs parentheses the engine refuses,
    # and building it is what this net is here to exercise.
    "inventory_selectors.ledger_lines": lambda s: s.all(
        inventory_selectors.ledger_lines(inventory_selectors.SHOP_REASONS, size=5)
    ),
    "inventory_selectors.book_branches": lambda s: [
        s.all(branch) for branch in inventory_selectors.book_branches(5)
    ],
    "inventory_selectors.book_compound": lambda s: inventory_selectors.book_compound(5),
    "inventory_selectors.fold_book": lambda s: inventory_selectors.fold_book(
        *(s.all(branch) for branch in inventory_selectors.book_branches(5))
    ),
    # The two the operations of `orders` read stock through. The fragment is executed here because
    # the point of a fragment is that it does NOT execute where it is built, so the only way to
    # exercise it is to run it — and `lock_stock` is the one that asks the engine whether it can lock
    # at all, which on the SQLite of this suite is the `Nope` branch.
    "inventory_selectors.stock_to_take_from": lambda s: s.all(
        inventory_selectors.stock_to_take_from(
            _a_stock(s).warehouse_id, [_a_stock(s).sku_id]
        )
    ),
    # The multi-warehouse pick, which is the read `stock_to_take_from` cannot express: one `in_` per
    # column would ask for every crossing of the two lists instead of the pairs named.
    "inventory_selectors.stock_for_pairs": lambda s: s.all(
        inventory_selectors.stock_for_pairs(
            [(_a_stock(s).warehouse_id, _a_stock(s).sku_id)]
        )
    ),
    "inventory_selectors.pick_across_warehouses": lambda s: (
        inventory_selectors.pick_across_warehouses(
            s, [(_a_stock(s).warehouse_id, _a_stock(s).sku_id)]
        )
    ),
    "inventory_selectors.locking_stock_query": lambda s: s.all(
        inventory_selectors.locking_stock_query(
            s.dialect,
            warehouse_id=_a_stock(s).warehouse_id,
            sku_ids=[_a_stock(s).sku_id],
        )
    ),
    "inventory_selectors.lock_stock": lambda s: inventory_selectors.lock_stock(
        s, warehouse_id=_a_stock(s).warehouse_id, sku_ids=[_a_stock(s).sku_id]
    ),
    "inventory_selectors.warehouse_stats": lambda s: (
        inventory_selectors.warehouse_stats(s)
    ),
    "inventory_selectors.movements_to_export": lambda s: s.all(
        inventory_selectors.movements_to_export()
    ),
    # `list(...)` and not a bare call: the stream executes nothing until it is walked, so an
    # invocation that only built it would tick the box over a query that never ran.
    "inventory_selectors.stream_movements": lambda s: list(
        inventory_selectors.stream_movements(s)
    ),
    "inventory_selectors.busy_skus": lambda s: inventory_selectors.busy_skus(s),
    "inventory_selectors.stock_ranking": lambda s: inventory_selectors.stock_ranking(s),
    "inventory_selectors.skus_that_have_moved": lambda s: (
        inventory_selectors.skus_that_have_moved(s)
    ),
    "inventory_selectors.warehouses_holding_anything": lambda s: (
        inventory_selectors.warehouses_holding_anything(s)
    ),
    # --- services: inventory -------------------------------------------------------------------
    "inventory_services.create_warehouse": lambda s: (
        inventory_services.create_warehouse(
            s,
            code="ZZZ",
            name="New",
            opened_on=date(2024, 1, 1),
            shift_start=time(8, 0),
            cutoff=time(18, 0),
        )
    ),
    "inventory_services.close_warehouse": lambda s: inventory_services.close_warehouse(
        s, inventory_selectors.list_warehouses(s)[0]
    ),
    "inventory_services.create_sku": lambda s: inventory_services.create_sku(
        s,
        name="New SKU",
        kind=SkuKind.DIGITAL,
        price=Decimal("1.50"),
        weight_kg=0.1,
        lead_time=timedelta(days=1),
        attrs={},
        related_ids=[],
    ),
    "inventory_services.create_skus": lambda s: inventory_services.create_skus(s, []),
    # Hold, release and ship: the three writes a reservation is made of. `ship_held` takes a pair
    # that has something held, because taking units off a hold that is not there is what the engine's
    # CHECK is for and not what this invocation is measuring.
    "inventory_services.hold_units": lambda s: inventory_services.hold_units(
        s, stock=_a_stock(s), units=1
    ),
    "inventory_services.release_units": lambda s: inventory_services.release_units(
        s, stock=inventory_services.hold_units(s, stock=_a_stock(s), units=1), units=1
    ),
    "inventory_services.ship_held": lambda s: inventory_services.ship_held(
        s, stock=inventory_services.hold_units(s, stock=_a_stock(s), units=1), units=1
    ),
    "inventory_services.sku_by_public_id": lambda s: (
        inventory_services.sku_by_public_id(
            s, inventory_selectors.list_skus(s)[0].public_id
        )
    ),
    "inventory_services.set_stock": lambda s: inventory_services.set_stock(
        s, warehouse_id=_a_stock(s).warehouse_id, sku_id=_a_stock(s).sku_id, on_hand=3
    ),
    "inventory_services.move_stock": lambda s: inventory_services.move_stock(
        s, stock=_a_stock(s), delta=1, reason=MovementReason.ADJUSTMENT
    ),
    "inventory_services.set_stock_levels": lambda s: (
        inventory_services.set_stock_levels(s, stock=_a_stock(s), on_hand=7, reserved=2)
    ),
    "inventory_services.reserve_units": lambda s: inventory_services.reserve_units(
        s, warehouse_id=_a_stock(s).warehouse_id, units=1
    ),
    # A pair with NO movements: the seeded ones all have history, and the engine refuses to orphan
    # it. That refusal is the point, so the invocation makes a row that never moved.
    "inventory_services.delete_stock": lambda s: inventory_services.delete_stock(
        s, _untouched_stock(s)
    ),
    # --- selectors: orders (the domain that joins inventory and billing) -----------------------
    # The FRAGMENTS take no session: they are executed by stacking onto them, which is what the page
    # does with them and what phase 5 will do with an AsyncSession instead.
    "orders_selectors.in_state": lambda s: s.all(
        orders_selectors.in_state(SnakeQuery(Order), OrderState.DRAFT)
    ),
    "orders_selectors.of_customer": lambda s: s.all(
        orders_selectors.of_customer(SnakeQuery(Order), _an_order(s).customer_id)
    ),
    "orders_selectors.order_listing": lambda s: s.all(
        orders_selectors.order_listing(state=OrderState.DRAFT).limit(5)
    ),
    "orders_selectors.with_parties": lambda s: s.all(
        orders_selectors.with_parties(SnakeQuery(Order)).limit(5)
    ),
    "orders_selectors.list_orders": lambda s: orders_selectors.list_orders(s),
    "orders_selectors.count_orders": lambda s: orders_selectors.count_orders(
        s, state=OrderState.DRAFT
    ),
    "orders_selectors.orders_page": lambda s: orders_selectors.orders_page(
        s, limit=5, offset=0
    ),
    "orders_selectors.get_order": lambda s: orders_selectors.get_order(
        s, _an_order(s).id
    ),
    "orders_selectors.get_order_with_parties": lambda s: (
        orders_selectors.get_order_with_parties(s, _an_order(s).id)
    ),
    "orders_selectors.get_order_by_reference": lambda s: (
        orders_selectors.get_order_by_reference(s, _an_order(s).reference)
    ),
    "orders_selectors.orders_with_lines": lambda s: orders_selectors.orders_with_lines(
        s, _an_order(s).customer_id
    ),
    "orders_selectors.lines_of": lambda s: s.all(
        orders_selectors.lines_of(_an_order(s).id)
    ),
    "orders_selectors.lines_of_order": lambda s: orders_selectors.lines_of_order(
        s, _an_order(s).id
    ),
    "orders_selectors.bare_lines_of_order": lambda s: (
        orders_selectors.bare_lines_of_order(s, _an_order(s).id)
    ),
    "orders_selectors.get_line": lambda s: orders_selectors.get_line(
        s, _an_order(s).id, _a_line(s).sku_id
    ),
    "orders_selectors.count_lines_of": lambda s: orders_selectors.count_lines_of(
        s, _an_order(s).id
    ),
    # The FRAGMENTS the two colours share. Each one is here because it is the only definition of a
    # query the asynchronous twin also runs: a fragment nothing exercises is a query that ships in
    # one demo and in no test.
    "orders_selectors.order_by_id": lambda s: s.all(
        orders_selectors.order_by_id(_an_order(s).id)
    ),
    "orders_selectors.order_with_parties_by_id": lambda s: s.all(
        orders_selectors.order_with_parties_by_id(_an_order(s).id)
    ),
    "orders_selectors.order_by_reference": lambda s: s.all(
        orders_selectors.order_by_reference(_an_order(s).reference)
    ),
    "orders_selectors.orders_with_lines_query": lambda s: s.all(
        orders_selectors.orders_with_lines_query(_an_order(s).customer_id)
    ),
    "orders_selectors.line_by_key": lambda s: s.all(
        orders_selectors.line_by_key(_a_line(s).order_id, _a_line(s).sku_id)
    ),
    "orders_selectors.lines_count_query": lambda s: s.count(
        orders_selectors.lines_count_query(_an_order(s).id)
    ),
    # Through `select` and not `all`: a grouped query is not a plain SELECT, and the ORM refuses it
    # rather than dropping the `GROUP BY` and answering a different question in silence.
    "orders_selectors.per_state_query": lambda s: s.select(
        orders_selectors.per_state_query(), Order.state
    ),
    "orders_selectors.per_state_columns": lambda s: s.select(
        orders_selectors.per_state_query(), *orders_selectors.per_state_columns()
    ),
    "orders_selectors.to_state_totals": lambda s: orders_selectors.to_state_totals(
        s.select(
            orders_selectors.per_state_query(), *orders_selectors.per_state_columns()
        )
    ),
    "orders_selectors.customer_orders_query": lambda s: s.all(
        orders_selectors.customer_orders_query().limit(5)
    ),
    "orders_selectors.customer_orders_aggregates": lambda s: s.annotate(
        orders_selectors.customer_orders_query(),
        CustomerOrders,
        **orders_selectors.customer_orders_aggregates(),
    ),
    "orders_selectors.repeat_customers_query": lambda s: s.select(
        orders_selectors.repeat_customers_query(minimum_orders=2),
        Order.customer.username,
    ),
    "orders_selectors.repeat_customers_columns": lambda s: s.select(
        orders_selectors.repeat_customers_query(minimum_orders=2),
        *orders_selectors.repeat_customers_columns(),
    ),
    "orders_selectors.to_customer_totals": lambda s: (
        orders_selectors.to_customer_totals(
            s.select(
                orders_selectors.repeat_customers_query(minimum_orders=2),
                *orders_selectors.repeat_customers_columns(),
            )
        )
    ),
    "orders_selectors.order_sequence_query": lambda s: s.all(
        orders_selectors.order_sequence_query(limit=5)
    ),
    "orders_selectors.order_sequence_columns": lambda s: s.select(
        orders_selectors.order_sequence_query(limit=5),
        *orders_selectors.order_sequence_columns(),
    ),
    "orders_selectors.to_order_sequence": lambda s: orders_selectors.to_order_sequence(
        s.select(
            orders_selectors.order_sequence_query(limit=5),
            *orders_selectors.order_sequence_columns(),
        )
    ),
    # The compound and its fallback, BOTH, whatever the engine under the test can do: the branch is
    # what varies between the three, so exercising only the one this run happens to take would leave
    # the other path covered nowhere.
    "orders_selectors.highlights_compound": lambda s: (
        s.all(orders_selectors.highlights_compound(5))
        if s.dialect.supports_parenthesised_compound
        else orders_selectors.highlights_compound(5)
    ),
    "orders_selectors.fold_highlights": lambda s: orders_selectors.fold_highlights(
        s.all(orders_selectors.highlight_branches(5)[1]),
        s.all(orders_selectors.highlight_branches(5)[0]),
    ),
    "orders_selectors.orders_per_state": lambda s: orders_selectors.orders_per_state(s),
    "orders_selectors.customer_orders": lambda s: orders_selectors.customer_orders(s),
    "orders_selectors.customers_with_orders": lambda s: (
        orders_selectors.customers_with_orders(s)
    ),
    "orders_selectors.skus_ordered_from": lambda s: s.all(
        orders_selectors.skus_ordered_from(_an_order(s).warehouse_id).limit(5)
    ),
    "orders_selectors.lines_to_export": lambda s: s.all(
        orders_selectors.lines_to_export()
    ),
    "orders_selectors.stream_order_lines": lambda s: list(
        orders_selectors.stream_order_lines(s)
    ),
    "orders_selectors.repeat_customers": lambda s: orders_selectors.repeat_customers(s),
    "orders_selectors.order_sequence": lambda s: orders_selectors.order_sequence(s),
    "orders_selectors.highlight_branches": lambda s: s.all(
        orders_selectors.highlight_branches(3)[0]
    ),
    "orders_selectors.order_highlights": lambda s: orders_selectors.order_highlights(s),
    # --- services: orders ----------------------------------------------------------------------
    # The baskets. Projected rather than merely built: an aggregate the engine has never been asked
    # about is an aggregate nobody has proved it spells the same way.
    # Projected and not `all`ed: the fragment carries a `group_by`, and a plain SELECT refuses it
    # rather than dropping it — which is the ORM answering the question that was asked or none.
    "orders_selectors.baskets_query": lambda s: s.select(
        orders_selectors.baskets_query(), orders_selectors.baskets_columns()[0]
    ),
    "orders_selectors.baskets_columns": lambda s: s.select(
        orders_selectors.baskets_query(), *orders_selectors.baskets_columns()
    ),
    "orders_selectors.order_baskets": lambda s: orders_selectors.order_baskets(s),
    "orders_services.create_order": lambda s: orders_services.create_order(
        s,
        reference="ORD-NEW",
        customer_id=_an_order(s).customer_id,
        warehouse_id=_an_order(s).warehouse_id,
        total=Decimal("10.00"),
    ),
    "orders_services.set_line": lambda s: orders_services.set_line(
        s,
        order_id=_an_order(s).id,
        sku_id=_a_line(s).sku_id,
        quantity=3,
        unit_price=Decimal("2.50"),
    ),
    "orders_services.add_lines": lambda s: orders_services.add_lines(s, []),
    "orders_services.delete_line": lambda s: orders_services.delete_line(s, _a_line(s)),
    "orders_services.retotal": lambda s: orders_services.retotal(
        s, order=_an_order(s), lines=orders_selectors.lines_of_order(s, _an_order(s).id)
    ),
    "orders_services.set_state": lambda s: orders_services.set_state(
        s, order=_an_order(s), state=OrderState.CANCELLED
    ),
    "orders_services.attach_invoice": lambda s: orders_services.attach_invoice(
        s,
        order=_an_order(s),
        invoice_id=_primer_id(
            billing_selectors.invoices_of_subscription(
                s, _primer_id(billing_selectors.subscriptions_of_user(s, 1))
            )
        ),
    ),
    # A fresh order with NO lines: the seeded ones all have some, and the engine refuses to orphan
    # them. That refusal is the point, so the invocation makes a row that never had any.
    "orders_services.delete_order": lambda s: orders_services.delete_order(
        s, _an_empty_order(s)
    ),
    # ---- The FRAGMENTS ----------------------------------------------------------------------
    # Phase 5 split every read in two: a FRAGMENT that builds a `SnakeQuery` and does not run it,
    # and an EXECUTOR that runs it. Only the executor has a colour, which is what lets the
    # asynchronous FastAPI demo and the two synchronous ones share one query instead of two that
    # merely look alike.
    #
    # They are invoked HERE, executed, and not exempted — because a fragment that nobody runs is
    # exactly the thing this file's docstring was written about: `catalog.recent_comments` compiled
    # perfectly and had never returned a row. A fragment compiles even better than a function: it
    # never touches a database at all until somebody runs it, which is the whole point of it and
    # also the whole risk.
    "accounts_selectors.all_roles": lambda s: s.all(accounts_selectors.all_roles()),
    "accounts_selectors.role_by_id": lambda s: s.first(
        accounts_selectors.role_by_id(1)
    ),
    "accounts_selectors.assignment": lambda s: s.first(
        accounts_selectors.assignment(1, 1)
    ),
    "auth_selectors.tokens_of": lambda s: s.all(auth_selectors.tokens_of(1)),
    "auth_selectors.token_by_id": lambda s: s.first(auth_selectors.token_by_id(1)),
    "auth_selectors.login_sessions_of": lambda s: s.all(
        auth_selectors.login_sessions_of(1)
    ),
    "billing_selectors.plans_query": lambda s: s.all(billing_selectors.plans_query()),
    "billing_selectors.subscriptions_of": lambda s: s.all(
        billing_selectors.subscriptions_of(1)
    ),
    "billing_selectors.subscription_by_id": lambda s: s.first(
        billing_selectors.subscription_by_id(1)
    ),
    "billing_selectors.invoices_of": lambda s: s.all(billing_selectors.invoices_of(1)),
    "billing_selectors.invoice_by_id": lambda s: s.first(
        billing_selectors.invoice_by_id(1)
    ),
    "billing_selectors.invoice_with_parties_by_id": lambda s: s.first(
        billing_selectors.invoice_with_parties_by_id(1)
    ),
    "billing_selectors.payments_of_invoice": lambda s: s.all(
        billing_selectors.payments_of_invoice(1)
    ),
    "billing_selectors.unpaid_invoices_query": lambda s: s.all(
        billing_selectors.unpaid_invoices_query()
    ),
    "billing_selectors.open_invoices_query": lambda s: s.select(
        billing_selectors.open_invoices_query(),
        *billing_selectors.unpaid_total_columns(),
    ),
    "billing_selectors.unpaid_total_columns": lambda s: s.select(
        billing_selectors.open_invoices_query(),
        *billing_selectors.unpaid_total_columns(),
    ),
    "billing_selectors.plan_stats_query": lambda s: s.annotate(
        billing_selectors.plan_stats_query(),
        PlanStats,
        **billing_selectors.plan_stats_aggregates(),
    ),
    "billing_selectors.plan_stats_aggregates": lambda s: s.annotate(
        billing_selectors.plan_stats_query(),
        PlanStats,
        **billing_selectors.plan_stats_aggregates(),
    ),
    "billing_selectors.revenue_by_plan_query": lambda s: s.select(
        billing_selectors.revenue_by_plan_query(),
        *billing_selectors.revenue_by_plan_columns(),
    ),
    "billing_selectors.revenue_by_plan_columns": lambda s: s.select(
        billing_selectors.revenue_by_plan_query(),
        *billing_selectors.revenue_by_plan_columns(),
    ),
    "blog_selectors.posts_query": lambda s: s.all(blog_selectors.posts_query()),
    "blog_selectors.post_by_id": lambda s: s.first(blog_selectors.post_by_id(1)),
    "blog_selectors.user_by_id": lambda s: s.first(blog_selectors.user_by_id(1)),
    "blog_selectors.user_by_username": lambda s: s.first(
        blog_selectors.user_by_username("demo1")
    ),
    "blog_selectors.user_posts_query": lambda s: s.all(
        blog_selectors.user_posts_query(1)
    ),
    "blog_selectors.user_stats_query": lambda s: s.annotate(
        blog_selectors.user_stats_query(),
        UserStats,
        **blog_selectors.user_stats_aggregates(),
    ),
    "blog_selectors.user_stats_aggregates": lambda s: s.annotate(
        blog_selectors.user_stats_query(),
        UserStats,
        **blog_selectors.user_stats_aggregates(),
    ),
    "blog_services.is_owner": lambda s: blog_services.is_owner(
        _a_post(s), _a_post(s).author_id
    ),
    "content_selectors.revisions_of": lambda s: s.all(
        content_selectors.revisions_of(1)
    ),
    "content_selectors.attachments_of": lambda s: s.all(
        content_selectors.attachments_of(1)
    ),
    "content_selectors.attachment_by_id": lambda s: s.first(
        content_selectors.attachment_by_id(1)
    ),
    # The NARROWED reads, and they are invoked here rather than only compiled: the SQL of an
    # `only()`/`defer()` was always right, and what was broken was the hydration behind it — a
    # fragment that is built and never run would have proved nothing about either one.
    "content_selectors.revision_timeline_of": lambda s: s.all(
        content_selectors.revision_timeline_of(1)
    ),
    "content_selectors.revision_timeline": lambda s: (
        content_selectors.revision_timeline(s, 1)
    ),
    "engagement_selectors.visits_to_export": lambda s: s.all(
        engagement_selectors.visits_to_export(1)
    ),
    "engagement_selectors.stream_visits": lambda s: list(
        engagement_selectors.stream_visits(s, post_id=1)
    ),
    "engagement_selectors.visited_post": lambda s: s.first(
        engagement_selectors.visited_post(1)
    ),
    "engagement_selectors.comments_of": lambda s: s.all(
        engagement_selectors.comments_of(1)
    ),
    "engagement_selectors.reactions_of": lambda s: s.all(
        engagement_selectors.reactions_of(1)
    ),
    "engagement_selectors.visits_of": lambda s: s.all(
        engagement_selectors.visits_of(1)
    ),
    "inventory_selectors.warehouses": lambda s: s.all(inventory_selectors.warehouses()),
    "inventory_selectors.warehouse_by_id": lambda s: s.first(
        inventory_selectors.warehouse_by_id(1)
    ),
    "inventory_selectors.all_skus": lambda s: s.all(inventory_selectors.all_skus()),
    "inventory_selectors.sku_by_id": lambda s: s.first(
        inventory_selectors.sku_by_id(1)
    ),
    "inventory_selectors.warehouse_stock": lambda s: s.all(
        inventory_selectors.warehouse_stock(1)
    ),
    "inventory_selectors.stock_in_warehouse": lambda s: s.all(
        inventory_selectors.stock_in_warehouse(1)
    ),
    "inventory_selectors.stock_pair": lambda s: s.first(
        inventory_selectors.stock_pair(1, 1)
    ),
    "inventory_selectors.stock_pair_with_relations": lambda s: s.first(
        inventory_selectors.stock_pair_with_relations(1, 1)
    ),
    "inventory_selectors.stock_movements": lambda s: s.all(
        inventory_selectors.stock_movements(1, 1)
    ),
    "inventory_selectors.warehouse_stock_with_movements": lambda s: s.all(
        inventory_selectors.warehouse_stock_with_movements(1)
    ),
    "inventory_selectors.low_stock_pairs": lambda s: s.all(
        inventory_selectors.low_stock_pairs()
    ),
    "inventory_selectors.warehouses_with_stock": lambda s: s.annotate(
        inventory_selectors.warehouses_with_stock(),
        WarehouseStats,
        sku_count=inventory_selectors.warehouse_sku_count(),
        total_units=inventory_selectors.warehouse_total_units(),
    ),
    "inventory_selectors.warehouse_sku_count": lambda s: s.annotate(
        inventory_selectors.warehouses_with_stock(),
        WarehouseStats,
        sku_count=inventory_selectors.warehouse_sku_count(),
        total_units=inventory_selectors.warehouse_total_units(),
    ),
    "inventory_selectors.warehouse_total_units": lambda s: s.annotate(
        inventory_selectors.warehouses_with_stock(),
        WarehouseStats,
        sku_count=inventory_selectors.warehouse_sku_count(),
        total_units=inventory_selectors.warehouse_total_units(),
    ),
    "inventory_selectors.busy_sku_movements": lambda s: s.select(
        inventory_selectors.busy_sku_movements(1),
        *inventory_selectors.busy_sku_columns(),
    ),
    "inventory_selectors.busy_sku_columns": lambda s: s.select(
        inventory_selectors.busy_sku_movements(1),
        *inventory_selectors.busy_sku_columns(),
    ),
    "inventory_selectors.reserved_ratio": lambda s: inventory_selectors.reserved_ratio(
        s
    ),
    "inventory_selectors.reserved_percent": lambda s: s.select(
        inventory_selectors.pairs_by_sku_name(),
        inventory_selectors.reserved_percent(),
    ),
    "inventory_selectors.pairs_by_sku_name": lambda s: s.all(
        inventory_selectors.pairs_by_sku_name()
    ),
    "inventory_selectors.warehouses_by_units_held": lambda s: (
        inventory_selectors.warehouses_by_units_held(s)
    ),
    "inventory_selectors.stock_by_status": lambda s: (
        inventory_selectors.stock_by_status(s)
    ),
    "inventory_selectors.stock_grouped_by_status": lambda s: s.select(
        inventory_selectors.stock_grouped_by_status(),
        inventory_selectors.stock_status(),
        count(),
    ),
    "inventory_selectors.stock_status": lambda s: s.select(
        inventory_selectors.stock_grouped_by_status(),
        inventory_selectors.stock_status(),
        count(),
    ),
    "inventory_selectors.ranked_stock": lambda s: s.select(
        inventory_selectors.ranked_stock(10),
        *inventory_selectors.ranked_stock_columns(),
    ),
    "inventory_selectors.ranked_stock_columns": lambda s: s.select(
        inventory_selectors.ranked_stock(10),
        *inventory_selectors.ranked_stock_columns(),
    ),
    "inventory_selectors.moved_stock": lambda s: s.select(
        inventory_selectors.moved_stock(), *inventory_selectors.moved_sku_columns()
    ),
    "inventory_selectors.moved_sku_columns": lambda s: s.select(
        inventory_selectors.moved_stock(), *inventory_selectors.moved_sku_columns()
    ),
    # The trail's two windows. Projected rather than merely built, because a window the engine has
    # never been asked about is a window nobody has proved it accepts — and the FRAME is the half
    # that is new here.
    "inventory_selectors.movement_trail": lambda s: s.all(
        inventory_selectors.movement_trail()
    ),
    "inventory_selectors.running_units": lambda s: s.select(
        inventory_selectors.movement_trail(), inventory_selectors.running_units()
    ),
    "inventory_selectors.moving_units": lambda s: s.select(
        inventory_selectors.movement_trail(), inventory_selectors.moving_units()
    ),
    "inventory_selectors.movement_trail_columns": lambda s: s.select(
        inventory_selectors.movement_trail(),
        *inventory_selectors.movement_trail_columns(),
    ),
    "inventory_selectors.movement_trail_rows": lambda s: (
        inventory_selectors.movement_trail_rows(s)
    ),
    "taxonomy_selectors.all_groups": lambda s: s.all(taxonomy_selectors.all_groups()),
    "taxonomy_selectors.all_tags": lambda s: s.all(taxonomy_selectors.all_tags()),
    "taxonomy_selectors.tagging": lambda s: s.first(taxonomy_selectors.tagging(1, 1)),
    "taxonomy_selectors.posts_for": lambda s: s.all(taxonomy_selectors.posts_for(1)),
    # TWO tag ids and not one: with a single branch there is no INTERSECT to compile, so the
    # invocation would run the fragment without ever emitting the SQL it exists to emit.
    "taxonomy_selectors.posts_with_every_tag": lambda s: s.all(
        taxonomy_selectors.posts_with_every_tag((1, 2))
    ),
    "taxonomy_selectors.posts_with_tag_but_not": lambda s: s.all(
        taxonomy_selectors.posts_with_tag_but_not(1, 2)
    ),
    # The two directions of the SAME recursion, and both are here because the pair of columns is
    # the only thing that tells them apart: swapped by accident, a breadcrumb silently becomes a
    # subtree and both still return rows.
    "taxonomy_selectors.subtree_of": lambda s: s.all(taxonomy_selectors.subtree_of(1)),
    "taxonomy_selectors.ancestry_of": lambda s: s.all(
        taxonomy_selectors.ancestry_of(1)
    ),
    "taxonomy_selectors.subtree": lambda s: taxonomy_selectors.subtree(s, 1),
    "taxonomy_selectors.ancestry": lambda s: taxonomy_selectors.ancestry(s, 1),
    "taxonomy_selectors.order_ancestry": lambda s: taxonomy_selectors.order_ancestry(
        taxonomy_selectors.ancestry(s, 1), 1
    ),
    # --- selectors: logistics (the domain that MEASURES) ----------------------------------------
    # Every fragment here is invoked with the point or the row it was written for, never a bare `1`.
    # `_a_delivery` is what makes that true for the coordinates: a distance measured from a delivery
    # that is not in the seed is a distance from nowhere, and it would come back with rows and prove
    # nothing.
    "logistics_selectors.depots": lambda s: s.all(logistics_selectors.depots()),
    "logistics_selectors.depot_columns": lambda s: s.select(
        logistics_selectors.depots(), *logistics_selectors.depot_columns()
    ),
    "logistics_selectors.depot_rows": lambda s: logistics_selectors.depot_rows(s),
    "logistics_selectors.distance_to": lambda s: s.select(
        logistics_selectors.depots(),
        logistics_selectors.distance_to(
            _a_delivery(s).latitude, _a_delivery(s).longitude
        ),
    ),
    "logistics_selectors.depots_by_distance": lambda s: s.all(
        logistics_selectors.depots_by_distance(
            _a_delivery(s).latitude, _a_delivery(s).longitude
        )
    ),
    "logistics_selectors.nearest_depots": lambda s: logistics_selectors.nearest_depots(
        s, _a_delivery(s).latitude, _a_delivery(s).longitude
    ),
    "logistics_selectors.delivery": lambda s: s.first(
        logistics_selectors.delivery(_a_delivery(s).id)
    ),
    "logistics_selectors.find_delivery": lambda s: logistics_selectors.find_delivery(
        s, _a_delivery(s).id
    ),
    "logistics_selectors.boxes_needed": lambda s: s.select(
        logistics_selectors.delivery(_a_delivery(s).id),
        logistics_selectors.boxes_needed(),
    ),
    "logistics_selectors.full_boxes": lambda s: s.select(
        logistics_selectors.delivery(_a_delivery(s).id),
        logistics_selectors.full_boxes(),
    ),
    "logistics_selectors.packing_columns": lambda s: s.select(
        logistics_selectors.delivery(_a_delivery(s).id),
        *logistics_selectors.packing_columns(),
    ),
    "logistics_selectors.packing_slip": lambda s: logistics_selectors.packing_slip(
        s, _a_delivery(s).id
    ),
    "logistics_selectors.latest_dispatch": lambda s: s.select(
        logistics_selectors.dispatch_query(), logistics_selectors.latest_dispatch()
    ),
    "logistics_selectors.dispatch_query": lambda s: s.all(
        logistics_selectors.dispatch_query()
    ),
    "logistics_selectors.dispatch_columns": lambda s: s.select(
        logistics_selectors.dispatch_query(), *logistics_selectors.dispatch_columns()
    ),
    "logistics_selectors.dispatch_rows": lambda s: logistics_selectors.dispatch_rows(s),
    "logistics_selectors.day_of": lambda s: logistics_selectors.day_of(
        _a_delivery(s).promised_at
    ),
    "logistics_selectors.band_units": lambda s: s.select(
        logistics_selectors.slot_load_query(), logistics_selectors.band_units()
    ),
    "logistics_selectors.slot_load_query": lambda s: s.all(
        logistics_selectors.slot_load_query()
    ),
    "logistics_selectors.slot_load_columns": lambda s: s.select(
        logistics_selectors.slot_load_query(), *logistics_selectors.slot_load_columns()
    ),
    "logistics_selectors.slot_load_rows": lambda s: logistics_selectors.slot_load_rows(
        s
    ),
    # --- services: logistics --------------------------------------------------------------------
    "logistics_services.route_to": lambda s: logistics_services.route_to(
        s, _a_delivery(s), _a_delivery(s).depot_id
    ),
}


def _public_functions() -> set[str]:
    """The public functions of `shared.selectors` and `shared.services`, read FROM THE MODULES.

    Walked with `pkgutil.iter_modules`, so a module added tomorrow is read on the next run. How many
    there are is deliberately not written down: this line used to say "the fifteen modules" while the
    walk returned twenty-one, which is a sentence boasting about reading from the module and quoting
    a figure the module contradicts.
    """
    names: set[str] = set()
    for package in ("shared.selectors", "shared.services"):
        pkg = importlib.import_module(package)
        for info in pkgutil.iter_modules(pkg.__path__):
            module = importlib.import_module(f"{package}.{info.name}")
            names.update(
                f"{info.name}.{name}"
                for name, function in vars(module).items()
                if not name.startswith("_")
                and inspect.isfunction(function)
                and function.__module__ == module.__name__
            )
    return names


def test_every_selector_and_service_is_exercised() -> None:
    """Every public function of the selector and service modules has an invocation here.

    This is the half that makes the rest useful. With a hand-written table, the function someone adds
    tomorrow is run by nobody —which is exactly how it got down to 35%— and the suite stays green.
    """
    missing = _public_functions() - set(_INVOCATIONS)

    assert missing == set(), (
        f"functions with no invocation in this file: {sorted(missing)}"
    )


def test_the_invocation_table_has_no_leftovers() -> None:
    """And the other way around: no invocation points at a function that no longer exists.

    Without this half, deleting a function would leave a dead entry here and the count would keep
    adding up by chance.
    """
    extra = set(_INVOCATIONS) - _public_functions()

    assert extra == set(), f"invocations with no function behind them: {sorted(extra)}"


@pytest.mark.parametrize("name", sorted(_INVOCATIONS))
def test_it_runs_against_a_seeded_database(name: str, seeded: SnakeSession) -> None:
    """Every function is EXECUTED against the seeded database, one per test.

    One per test and not all in a loop: with the loop, the first one that blows up hides every one
    that follows, and what one wants to know is how many are broken, not that some are.
    """
    _INVOCATIONS[name](seeded)
