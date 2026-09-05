"""The same question asked of both sessions gives the same answer AND the same SQL.

This is the net under the whole asynchronous demo, and it is worth saying what it is a net AGAINST,
because it is not "async might be broken". `SnakeSession` and `AsyncSession` share the planner, the
compiler and the dialect; what they do not share is the code in `frameworks/` that CALLS them.
`shared/usecases/` and `shared/aio/` are two orchestrations of the same operations, and the moment
there are two of anything in this repository the question stops being whether each works and becomes
whether they still AGREE.

The design keeps that surface as small as it can be. The SQL is not duplicated at all: every read is
a colourless `SnakeQuery` fragment in `shared/selectors/`, and both colours execute the same one, so
there is nothing to drift. What remains duplicated is the CONTROL FLOW of a use case — the two or
three lines that validate, decide and commit — because `await` is syntax and Python will not let one
function body serve both colours. Those lines are what this file watches.

WHAT IS COMPARED, AND WHY IT IS THREE THINGS AND NOT ONE:

- **the answer**, so a rule that changed on one side and not the other shows up;
- **the SQL and its parameters**, statement by statement, so a fragment that stopped being shared
  shows up even when both sides still return the same rows;
- **the MESSAGE the ORM emits about that SQL** — `DebugReport.warnings`, which is where an N+1
  complaint lands. This third one is not belt-and-braces. This repository has already paid for
  leaving it out: the two sessions drifted into explaining the same complaint with two different
  wordings, and the test that compared only the SQL let it through for months. In an ORM whose
  doctrine is to SHOUT, the message is the product. The `file:line` the warning ends in is the one
  part exempted, because it names the CALLER and the two callers are two different files by
  construction; it is blanked like a minted value, and its PRESENCE on both sides is still asserted.

The substrate is a file-backed SQLite, not the in-memory one the rest of this suite uses, and not
Postgres. A file because the two colours are two CONNECTIONS and `:memory:` gives a private database
to each; SQLite rather than Postgres because what is under test is whether both colours run the same
fragment, and that is a question about the emitter, which is colourless and identical either way.
Needing docker to answer it would only mean fewer people ever run it.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, time, timedelta
from decimal import Decimal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from snakeorm import (
    AsyncSession,
    AsyncSQLiteDriver,
    SnakeSession,
    SnakeUtc,
    SQLiteDialect,
    SQLiteDriver,
    snake_table,
)
from snakeorm.debug import (
    AsyncCaptureDriver,
    CaptureDriver,
    DebugCollector,
    capture_queries,
)
from snakeorm.migration import emit_create_table, emit_create_view

from shared import aio
from shared.data import Scale, seed
from shared.models import MODELS, VIEWS, OrderLine, SkuKind, StockMovement
from shared.usecases import (
    accounts_usecases,
    auth_usecases,
    billing_usecases,
    blog_usecases,
    content_usecases,
    engagement_usecases,
    inventory_usecases,
    logistics_usecases,
    orders_usecases,
    taxonomy_usecases,
)
from shared.usecases.result import Failure


@dataclass(frozen=True)
class Recording:
    """What one colour did while it answered: the statements, and what the ORM said about them."""

    statements: tuple[tuple[str, tuple[object, ...]], ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Question:
    """One question, asked twice: once of each colour.

    `ask` and `ask_async` must be the SAME operation, which is exactly what is being tested. The
    pair is written by hand, and the last test in this file is what stops the table from becoming a
    sample of the mirror instead of the whole of it.
    """

    name: str
    ask: Callable[[SnakeSession], object]
    ask_async: Callable[[AsyncSession], Awaitable[object]]
    generates: str = ""
    """WHY a value in this comparison was MINTED rather than fixed, empty when none is.

    Two sources, and both are the system working rather than drifting.

    The operation can mint: `issue_token` calls `secrets.token_urlsafe`, `register` hashes with a
    fresh salt, `create_sku` builds a `uuid4`, and every write that stamps `datetime.now()` does the
    same with the clock. Asked twice, those two runs CANNOT bind the same parameters.

    And the SEEDER can mint, which is the half that surprises: the two colours get one database
    FILE each, built independently, so a seeded password hash and a seeded `created_at` already
    differ before either question is asked. A read that returns those columns inherits it.

    So a row that fills this in has its generated values BLANKED before the comparison, in the
    answer and in the parameters alike, and everything else still compares exactly: the statements,
    their order, every other parameter, the warnings. What is given up is one value per statement;
    what would be given up by leaving the row out of the table altogether is the whole operation,
    and `test_the_table_covers_every_asynchronous_use_case` exists to make that impossible.

    The reason is a sentence and not a boolean because the next person has to be able to tell a
    genuine mint from an excuse, and a `True` explains nothing.
    """


# The ageing section of the billing report takes a cutoff, and it is PINNED here rather than read
# off the clock. The whole point of this file is asking both colours the identical question, and
# `SnakeUtc.now()` evaluated twice is two questions a millisecond apart — which would show up as a
# difference in the answer and blame the wrong thing.
_PARITY_CUTOFF = SnakeUtc(2030, 1, 1, 0, 0)


# The questions, one row per operation the FastAPI demo answers asynchronously. Reads and writes
# alike: a write is where the control flow lives, so it is where the drift would be. Several
# operations appear twice, once down the happy path and once down the rule that refuses — a `Failure`
# is an answer like any other, and it is the answer a user reads.
QUESTIONS: tuple[Question, ...] = (
    Question(
        "accounts.list_roles",
        lambda s: accounts_usecases.list_roles(s),
        lambda s: aio.accounts_usecases.list_roles(s),
    ),
    Question(
        "accounts.roles_of_user",
        lambda s: accounts_usecases.roles_of_user(s, 1),
        lambda s: aio.accounts_usecases.roles_of_user(s, 1),
    ),
    Question(
        "accounts.create_role",
        lambda s: accounts_usecases.create_role(s, "auditor"),
        lambda s: aio.accounts_usecases.create_role(s, "auditor"),
    ),
    Question(
        # The rule, not the happy path: an empty name is refused BEFORE anything is written, and
        # both colours have to refuse it with the same word.
        "accounts.create_role.refused",
        lambda s: accounts_usecases.create_role(s, ""),
        lambda s: aio.accounts_usecases.create_role(s, ""),
    ),
    Question(
        "accounts.assign_role",
        lambda s: accounts_usecases.assign_role(s, 1, 1),
        lambda s: aio.accounts_usecases.assign_role(s, 1, 1),
    ),
    Question(
        "accounts.assign_role.refused",
        lambda s: accounts_usecases.assign_role(s, 1, 9999),
        lambda s: aio.accounts_usecases.assign_role(s, 1, 9999),
    ),
    Question(
        "accounts.revoke_role.refused",
        lambda s: accounts_usecases.revoke_role(s, 1, 9999),
        lambda s: aio.accounts_usecases.revoke_role(s, 1, 9999),
    ),
    Question(
        "taxonomy.list_groups",
        lambda s: taxonomy_usecases.list_groups(s),
        lambda s: aio.taxonomy_usecases.list_groups(s),
    ),
    Question(
        "taxonomy.list_tags",
        lambda s: taxonomy_usecases.list_tags(s),
        lambda s: aio.taxonomy_usecases.list_tags(s),
    ),
    Question(
        "taxonomy.tags_of_post",
        lambda s: taxonomy_usecases.tags_of_post(s, 1),
        lambda s: aio.taxonomy_usecases.tags_of_post(s, 1),
    ),
    Question(
        "taxonomy.create_tag",
        lambda s: taxonomy_usecases.create_tag(s, "asyncio", 1),
        lambda s: aio.taxonomy_usecases.create_tag(s, "asyncio", 1),
    ),
    Question(
        "taxonomy.create_tag.refused",
        lambda s: taxonomy_usecases.create_tag(s, "", 1),
        lambda s: aio.taxonomy_usecases.create_tag(s, "", 1),
    ),
    Question(
        "taxonomy.tag_post",
        lambda s: taxonomy_usecases.tag_post(s, 1, 2),
        lambda s: aio.taxonomy_usecases.tag_post(s, 1, 2),
    ),
    Question(
        "taxonomy.untag_post.refused",
        lambda s: taxonomy_usecases.untag_post(s, 1, 9999),
        lambda s: aio.taxonomy_usecases.untag_post(s, 1, 9999),
    ),
    Question(
        "taxonomy.posts_with_every_tag",
        lambda s: taxonomy_usecases.posts_with_every_tag(s, (1, 2)),
        lambda s: aio.taxonomy_usecases.posts_with_every_tag(s, (1, 2)),
    ),
    # The refusal too: it is the branch that does NOT reach the compound, so a twin that forgot the
    # check would agree on every row above and disagree only here.
    Question(
        "taxonomy.posts_with_every_tag.refused",
        lambda s: taxonomy_usecases.posts_with_every_tag(s, (1,)),
        lambda s: aio.taxonomy_usecases.posts_with_every_tag(s, (1,)),
    ),
    Question(
        "taxonomy.posts_with_tag_but_not",
        lambda s: taxonomy_usecases.posts_with_tag_but_not(s, 1, 2),
        lambda s: aio.taxonomy_usecases.posts_with_tag_but_not(s, 1, 2),
    ),
    # The two directions of the recursion, and both are here because the ORDER is decided in Python
    # on one side of the pair: the CTE answers with a set and the chain is walked from the rows'
    # `parent_id` links. A colour that walked it differently would return the same tags in a
    # different order and every other assertion in this file would still pass.
    Question(
        "taxonomy.tag_breadcrumb",
        lambda s: taxonomy_usecases.tag_breadcrumb(s, 3),
        lambda s: aio.taxonomy_usecases.tag_breadcrumb(s, 3),
    ),
    Question(
        "taxonomy.tag_breadcrumb.refused",
        lambda s: taxonomy_usecases.tag_breadcrumb(s, 9999),
        lambda s: aio.taxonomy_usecases.tag_breadcrumb(s, 9999),
    ),
    Question(
        "taxonomy.tag_descendants",
        lambda s: taxonomy_usecases.tag_descendants(s, 1),
        lambda s: aio.taxonomy_usecases.tag_descendants(s, 1),
    ),
    # ---- auth ---------------------------------------------------------------------------------
    Question(
        "auth.tokens_of_user",
        lambda s: auth_usecases.tokens_of_user(s, 1),
        lambda s: aio.auth_usecases.tokens_of_user(s, 1),
        generates="the seeded tokens are random strings and carry a seeded `created_at`",
    ),
    Question(
        "auth.active_tokens",
        lambda s: auth_usecases.active_tokens(s, 1),
        lambda s: aio.auth_usecases.active_tokens(s, 1),
        generates="the rows carry a column stamped by the SERVER at insert time, and the two database files are seeded one after the other",
    ),
    Question(
        "auth.sessions_of_user",
        lambda s: auth_usecases.sessions_of_user(s, 1),
        lambda s: aio.auth_usecases.sessions_of_user(s, 1),
        generates="the rows carry a column stamped by the SERVER at insert time, and the two database files are seeded one after the other",
    ),
    Question(
        "auth.issue_token",
        lambda s: auth_usecases.issue_token(s, 1, "ci"),
        lambda s: aio.auth_usecases.issue_token(s, 1, "ci"),
        generates="the secret is `secrets.token_urlsafe(32)` and the expiry is `now` plus thirty "
        "days, so two runs a millisecond apart bind two different tokens and two different dates",
    ),
    Question(
        "auth.revoke_token.refused",
        lambda s: auth_usecases.revoke_token(s, 999_999),
        lambda s: aio.auth_usecases.revoke_token(s, 999_999),
    ),
    # ---- content ------------------------------------------------------------------------------
    Question(
        "content.revisions_of_post",
        lambda s: content_usecases.revisions_of_post(s, 1),
        lambda s: aio.content_usecases.revisions_of_post(s, 1),
    ),
    Question(
        "content.attachments_of_post",
        lambda s: content_usecases.attachments_of_post(s, 1),
        lambda s: aio.content_usecases.attachments_of_post(s, 1),
    ),
    Question(
        "content.add_revision",
        lambda s: content_usecases.add_revision(s, 1, "a newer body"),
        lambda s: aio.content_usecases.add_revision(s, 1, "a newer body"),
        generates="`edited_at` is stamped with the clock at the moment of the call",
    ),
    Question(
        "content.add_revision.refused",
        lambda s: content_usecases.add_revision(s, 1, ""),
        lambda s: aio.content_usecases.add_revision(s, 1, ""),
    ),
    Question(
        "content.attach_file",
        lambda s: content_usecases.attach_file(s, 1, "a.pdf", "/files/a.pdf", 12),
        lambda s: aio.content_usecases.attach_file(s, 1, "a.pdf", "/files/a.pdf", 12),
    ),
    Question(
        "content.remove_attachment.refused",
        lambda s: content_usecases.remove_attachment(s, 999_999),
        lambda s: aio.content_usecases.remove_attachment(s, 999_999),
    ),
    # ---- engagement ---------------------------------------------------------------------------
    Question(
        "engagement.comments_of_post",
        lambda s: engagement_usecases.comments_of_post(s, 1),
        lambda s: aio.engagement_usecases.comments_of_post(s, 1),
    ),
    Question(
        "engagement.reactions_of_post",
        lambda s: engagement_usecases.reactions_of_post(s, 1),
        lambda s: aio.engagement_usecases.reactions_of_post(s, 1),
    ),
    Question(
        "engagement.visits_of_post",
        lambda s: engagement_usecases.visits_of_post(s, 1),
        lambda s: aio.engagement_usecases.visits_of_post(s, 1),
    ),
    Question(
        "engagement.plan_for_visits_of_post",
        lambda s: engagement_usecases.plan_for_visits_of_post(s, 1),
        lambda s: aio.engagement_usecases.plan_for_visits_of_post(s, 1),
    ),
    Question(
        "engagement.add_comment",
        lambda s: engagement_usecases.add_comment(s, 1, 1, "nice"),
        lambda s: aio.engagement_usecases.add_comment(s, 1, 1, "nice"),
        generates="`created_at` is set by the code and not by a model default, on purpose",
    ),
    Question(
        "engagement.add_comment.refused",
        lambda s: engagement_usecases.add_comment(s, 1, 1, ""),
        lambda s: aio.engagement_usecases.add_comment(s, 1, 1, ""),
    ),
    Question(
        "engagement.add_reaction",
        lambda s: engagement_usecases.add_reaction(s, 1, 1, "like"),
        lambda s: aio.engagement_usecases.add_reaction(s, 1, 1, "like"),
        generates="`created_at` is set by the code at the moment of the call",
    ),
    Question(
        "engagement.record_visit",
        lambda s: engagement_usecases.record_visit(s, 1, "10.0.0.1", "curl"),
        lambda s: aio.engagement_usecases.record_visit(s, 1, "10.0.0.1", "curl"),
        generates="`visited_at` is the instant of the visit, which is the point of recording it",
    ),
    # ---- billing ------------------------------------------------------------------------------
    Question(
        "billing.list_plans",
        lambda s: billing_usecases.list_plans(s),
        lambda s: aio.billing_usecases.list_plans(s),
    ),
    Question(
        "billing.subscriptions_of_user",
        lambda s: billing_usecases.subscriptions_of_user(s, 1),
        lambda s: aio.billing_usecases.subscriptions_of_user(s, 1),
    ),
    Question(
        "billing.invoices_of_subscription",
        lambda s: billing_usecases.invoices_of_subscription(s, 1),
        lambda s: aio.billing_usecases.invoices_of_subscription(s, 1),
    ),
    Question(
        "billing.invoices_of_customer",
        lambda s: billing_usecases.invoices_of_customer(s, 1),
        lambda s: aio.billing_usecases.invoices_of_customer(s, 1),
    ),
    Question(
        "billing.unpaid_invoices",
        lambda s: billing_usecases.unpaid_invoices(s),
        lambda s: aio.billing_usecases.unpaid_invoices(s),
    ),
    Question(
        "billing.subscribe",
        lambda s: billing_usecases.subscribe(s, 1, 1),
        lambda s: aio.billing_usecases.subscribe(s, 1, 1),
        generates="the subscription is stamped with the instant it started",
    ),
    Question(
        "billing.cancel_subscription.refused",
        lambda s: billing_usecases.cancel_subscription(s, 999_999),
        lambda s: aio.billing_usecases.cancel_subscription(s, 999_999),
    ),
    Question(
        "billing.issue_invoice",
        lambda s: billing_usecases.issue_invoice(s, 1, 4_900),
        lambda s: aio.billing_usecases.issue_invoice(s, 1, 4_900),
        generates="`issued_at` is the instant the invoice was raised",
    ),
    Question(
        "billing.pay_invoice.refused",
        lambda s: billing_usecases.pay_invoice(s, 999_999, "card"),
        lambda s: aio.billing_usecases.pay_invoice(s, 999_999, "card"),
    ),
    Question(
        "billing.paginate_invoices",
        lambda s: billing_usecases.paginate_invoices(s, page=1, per_page=3),
        lambda s: aio.billing_usecases.paginate_invoices(s, page=1, per_page=3),
    ),
    Question(
        "billing.show_invoice",
        lambda s: billing_usecases.show_invoice(s, 1),
        lambda s: aio.billing_usecases.show_invoice(s, 1),
    ),
    Question(
        "billing.show_invoice.refused",
        lambda s: billing_usecases.show_invoice(s, 999_999),
        lambda s: aio.billing_usecases.show_invoice(s, 999_999),
    ),
    Question(
        "billing.payments_of",
        lambda s: billing_usecases.payments_of(s, 1),
        lambda s: aio.billing_usecases.payments_of(s, 1),
    ),
    Question(
        "billing.billing_report",
        lambda s: billing_usecases.billing_report(s, _PARITY_CUTOFF),
        lambda s: aio.billing_usecases.billing_report(s, _PARITY_CUTOFF),
    ),
    # ---- blog ---------------------------------------------------------------------------------
    Question(
        "blog.list_posts",
        lambda s: blog_usecases.list_posts(s),
        lambda s: aio.blog_usecases.list_posts(s),
        generates="the rows carry a column stamped by the SERVER at insert time, and the two database files are seeded one after the other",
    ),
    Question(
        "blog.list_user_posts",
        lambda s: blog_usecases.list_user_posts(s, 1),
        lambda s: aio.blog_usecases.list_user_posts(s, 1),
        generates="the rows carry a column stamped by the SERVER at insert time, and the two database files are seeded one after the other",
    ),
    Question(
        "blog.list_published",
        lambda s: blog_usecases.list_published(s),
        lambda s: aio.blog_usecases.list_published(s),
        generates="the rows carry a column stamped by the SERVER at insert time, and the two database files are seeded one after the other",
    ),
    Question(
        "blog.get_user",
        lambda s: blog_usecases.get_user(s, 1),
        lambda s: aio.blog_usecases.get_user(s, 1),
        generates="it returns a whole `User` row, and a seeded password hash is salted per database",
    ),
    Question(
        "blog.get_user.missing",
        lambda s: blog_usecases.get_user(s, 999_999),
        lambda s: aio.blog_usecases.get_user(s, 999_999),
    ),
    Question(
        "blog.show_post",
        lambda s: blog_usecases.show_post(s, 1),
        lambda s: aio.blog_usecases.show_post(s, 1),
        generates="the rows carry a column stamped by the SERVER at insert time, and the two database files are seeded one after the other",
    ),
    Question(
        "blog.show_post.refused",
        lambda s: blog_usecases.show_post(s, 999_999),
        lambda s: aio.blog_usecases.show_post(s, 999_999),
    ),
    Question(
        "blog.editable_post.refused",
        lambda s: blog_usecases.editable_post(s, 999_999, 1),
        lambda s: aio.blog_usecases.editable_post(s, 999_999, 1),
    ),
    Question(
        "blog.user_stats",
        lambda s: blog_usecases.user_stats(s),
        lambda s: aio.blog_usecases.user_stats(s),
        generates="it returns whole `User` rows, and a seeded password hash is salted per database",
    ),
    Question(
        "blog.register",
        lambda s: blog_usecases.register(s, "parity", "parity@x.com", "hunter22"),
        lambda s: aio.blog_usecases.register(s, "parity", "parity@x.com", "hunter22"),
        generates="the password is hashed with a FRESH SALT, so the same password stored twice is "
        "two different strings — which is the property the hashing exists to have",
    ),
    Question(
        "blog.register.refused",
        lambda s: blog_usecases.register(s, "", "", ""),
        lambda s: aio.blog_usecases.register(s, "", "", ""),
    ),
    Question(
        "blog.login.refused",
        lambda s: blog_usecases.login(s, "demo1", "not-the-password"),
        lambda s: aio.blog_usecases.login(s, "demo1", "not-the-password"),
    ),
    Question(
        "blog.create_post.refused",
        lambda s: blog_usecases.create_post(s, 1, title="", body="b"),
        lambda s: aio.blog_usecases.create_post(s, 1, title="", body="b"),
    ),
    Question(
        "blog.edit_post.refused",
        lambda s: blog_usecases.edit_post(s, 999_999, 1, title="x"),
        lambda s: aio.blog_usecases.edit_post(s, 999_999, 1, title="x"),
    ),
    Question(
        "blog.remove_post.refused",
        lambda s: blog_usecases.remove_post(s, 999_999, 1),
        lambda s: aio.blog_usecases.remove_post(s, 999_999, 1),
    ),
    # ---- inventory ----------------------------------------------------------------------------
    Question(
        "inventory.list_warehouses",
        lambda s: inventory_usecases.list_warehouses(s),
        lambda s: aio.inventory_usecases.list_warehouses(s),
        generates="a warehouse inherits `Timestamped`, so its `created_at` is stamped per database",
    ),
    Question(
        "inventory.get_warehouse",
        lambda s: inventory_usecases.get_warehouse(s, 1),
        lambda s: aio.inventory_usecases.get_warehouse(s, 1),
        generates="same `created_at` as the listing above",
    ),
    Question(
        "inventory.get_warehouse.refused",
        lambda s: inventory_usecases.get_warehouse(s, 999_999),
        lambda s: aio.inventory_usecases.get_warehouse(s, 999_999),
    ),
    Question(
        "inventory.list_skus",
        lambda s: inventory_usecases.list_skus(s),
        lambda s: aio.inventory_usecases.list_skus(s),
        generates="`Sku.public_id` is a `uuid4` built by the SEEDER, one per database",
    ),
    Question(
        "inventory.warehouse_stats",
        lambda s: inventory_usecases.warehouse_stats(s),
        lambda s: aio.inventory_usecases.warehouse_stats(s),
        generates="it projects whole `Warehouse` rows, `created_at` included",
    ),
    Question(
        "inventory.paginate_stock",
        lambda s: inventory_usecases.paginate_stock(s, warehouse_id=1, per_page=2),
        lambda s: aio.inventory_usecases.paginate_stock(s, warehouse_id=1, per_page=2),
        generates="the rows carry their SKU, and a SKU carries a seeded `uuid4`",
    ),
    Question(
        "inventory.get_stock",
        lambda s: inventory_usecases.get_stock(s, 1, 1),
        lambda s: aio.inventory_usecases.get_stock(s, 1, 1),
        generates="the pair loads its warehouse and its SKU, both seeded with minted columns",
    ),
    Question(
        "inventory.get_stock.refused",
        lambda s: inventory_usecases.get_stock(s, 2, 3),
        lambda s: aio.inventory_usecases.get_stock(s, 2, 3),
    ),
    Question(
        "inventory.count_movements",
        lambda s: inventory_usecases.count_movements(s, 1, 1),
        lambda s: aio.inventory_usecases.count_movements(s, 1, 1),
    ),
    Question(
        "inventory.stock_history",
        lambda s: inventory_usecases.stock_history(s, 1, 1),
        lambda s: aio.inventory_usecases.stock_history(s, 1, 1),
        generates="a movement carries the seeded instant it happened at",
    ),
    Question(
        "inventory.movements_of",
        lambda s: inventory_usecases.movements_of(s, 1, 1),
        lambda s: aio.inventory_usecases.movements_of(s, 1, 1),
        generates="same seeded `happened_at` as the history above",
    ),
    Question(
        "inventory.movements_of.refused",
        lambda s: inventory_usecases.movements_of(s, 2, 3),
        lambda s: aio.inventory_usecases.movements_of(s, 2, 3),
    ),
    Question(
        "inventory.stock_of_warehouse",
        lambda s: inventory_usecases.stock_of_warehouse(s, 1),
        lambda s: aio.inventory_usecases.stock_of_warehouse(s, 1),
        generates="the rows carry their SKU and its seeded `uuid4`",
    ),
    Question(
        "inventory.stock_of_warehouse.refused",
        lambda s: inventory_usecases.stock_of_warehouse(s, 999_999),
        lambda s: aio.inventory_usecases.stock_of_warehouse(s, 999_999),
    ),
    Question(
        "inventory.stock_with_movements",
        lambda s: inventory_usecases.stock_with_movements(s, 1),
        lambda s: aio.inventory_usecases.stock_with_movements(s, 1),
        generates="the to-many over a COMPOSITE key, and every movement carries a seeded instant",
    ),
    Question(
        "inventory.low_stock",
        lambda s: inventory_usecases.low_stock(s),
        lambda s: aio.inventory_usecases.low_stock(s),
        generates="the view projects `counted_at`, which the seeder stamps",
    ),
    Question(
        "inventory.movement_book",
        lambda s: inventory_usecases.movement_book(s),
        lambda s: aio.inventory_usecases.movement_book(s),
        generates="the ledger lines carry the instant the seeder stamped on each movement",
    ),
    Question(
        "inventory.stock_report",
        lambda s: inventory_usecases.stock_report(s),
        lambda s: aio.inventory_usecases.stock_report(s),
        # It projects whole `Warehouse` rows, and `created_at` is a SERVER default: the two database
        # files are built one after the other, so the two runs agree only while both land inside the
        # same second. It passed alone and failed in the full suite, which is the shape of a flake
        # rather than of drift — and a flake left undeclared is a red nobody trusts later.
        generates="the warehouses carry a server-stamped `created_at`, one per database build",
    ),
    Question(
        "inventory.stream_movements",
        lambda s: list(inventory_usecases.stream_movements(s, warehouse_id=1)),
        lambda s: _drained_movements(s),
        generates="the streamed movements carry their seeded `happened_at`",
    ),
    Question(
        "inventory.create_warehouse",
        lambda s: inventory_usecases.create_warehouse(
            s,
            code="LIS",
            name="Lisboa",
            opened_on=date(2024, 1, 1),
            shift_start=time(8, 0),
            cutoff=time(18, 0),
        ),
        lambda s: aio.inventory_usecases.create_warehouse(
            s,
            code="LIS",
            name="Lisboa",
            opened_on=date(2024, 1, 1),
            shift_start=time(8, 0),
            cutoff=time(18, 0),
        ),
        generates="`created_at` comes from the SERVER default, read back by the RETURNING",
    ),
    Question(
        "inventory.create_warehouse.refused",
        lambda s: inventory_usecases.create_warehouse(
            s,
            code="",
            name="",
            opened_on=date(2024, 1, 1),
            shift_start=time(8, 0),
            cutoff=time(18, 0),
        ),
        lambda s: aio.inventory_usecases.create_warehouse(
            s,
            code="",
            name="",
            opened_on=date(2024, 1, 1),
            shift_start=time(8, 0),
            cutoff=time(18, 0),
        ),
    ),
    Question(
        "inventory.create_sku",
        lambda s: inventory_usecases.create_sku(
            s,
            name="Widget",
            kind=SkuKind.PHYSICAL,
            price=Decimal("9.99"),
            weight_kg=0.1,
            lead_time=timedelta(days=3),
        ),
        lambda s: aio.inventory_usecases.create_sku(
            s,
            name="Widget",
            kind=SkuKind.PHYSICAL,
            price=Decimal("9.99"),
            weight_kg=0.1,
            lead_time=timedelta(days=3),
        ),
        generates="`public_id` is `uuid4()` filled in by PYTHON, one per instance: it is the id "
        "that travels outside, so it must not be the sequential one the database hands out",
    ),
    Question(
        "inventory.create_sku.refused",
        lambda s: inventory_usecases.create_sku(
            s,
            name="",
            kind=SkuKind.PHYSICAL,
            price=Decimal("9.99"),
            weight_kg=0.1,
            lead_time=timedelta(days=3),
        ),
        lambda s: aio.inventory_usecases.create_sku(
            s,
            name="",
            kind=SkuKind.PHYSICAL,
            price=Decimal("9.99"),
            weight_kg=0.1,
            lead_time=timedelta(days=3),
        ),
    ),
    Question(
        "inventory.receive",
        lambda s: inventory_usecases.receive(s, warehouse_id=1, sku_id=1, units=10),
        lambda s: aio.inventory_usecases.receive(s, warehouse_id=1, sku_id=1, units=10),
        generates="the movement it records is stamped by the server default",
    ),
    Question(
        "inventory.receive.refused",
        lambda s: inventory_usecases.receive(s, warehouse_id=1, sku_id=1, units=0),
        lambda s: aio.inventory_usecases.receive(s, warehouse_id=1, sku_id=1, units=0),
    ),
    Question(
        "inventory.ship",
        lambda s: inventory_usecases.ship(s, warehouse_id=1, sku_id=1, units=5),
        lambda s: aio.inventory_usecases.ship(s, warehouse_id=1, sku_id=1, units=5),
        generates="same stamped movement as `receive`",
    ),
    Question(
        "inventory.ship.refused",
        lambda s: inventory_usecases.ship(s, warehouse_id=1, sku_id=1, units=999_999),
        lambda s: aio.inventory_usecases.ship(
            s, warehouse_id=1, sku_id=1, units=999_999
        ),
    ),
    Question(
        "inventory.count_stock",
        lambda s: inventory_usecases.count_stock(
            s, warehouse_id=1, sku_id=1, on_hand=50
        ),
        lambda s: aio.inventory_usecases.count_stock(
            s, warehouse_id=1, sku_id=1, on_hand=50
        ),
    ),
    Question(
        "inventory.count_stock.refused",
        lambda s: inventory_usecases.count_stock(
            s, warehouse_id=1, sku_id=1, on_hand=-1
        ),
        lambda s: aio.inventory_usecases.count_stock(
            s, warehouse_id=1, sku_id=1, on_hand=-1
        ),
    ),
    Question(
        "inventory.update_stock",
        lambda s: inventory_usecases.update_stock(
            s, warehouse_id=1, sku_id=1, on_hand=200, reserved=10
        ),
        lambda s: aio.inventory_usecases.update_stock(
            s, warehouse_id=1, sku_id=1, on_hand=200, reserved=10
        ),
    ),
    Question(
        "inventory.update_stock.refused",
        lambda s: inventory_usecases.update_stock(
            s, warehouse_id=2, sku_id=3, on_hand=1, reserved=0
        ),
        lambda s: aio.inventory_usecases.update_stock(
            s, warehouse_id=2, sku_id=3, on_hand=1, reserved=0
        ),
    ),
    Question(
        "inventory.remove_stock.refused",
        lambda s: inventory_usecases.remove_stock(s, warehouse_id=1, sku_id=1),
        lambda s: aio.inventory_usecases.remove_stock(s, warehouse_id=1, sku_id=1),
    ),
    Question(
        "inventory.reserve",
        lambda s: inventory_usecases.reserve(s, warehouse_id=1, units=5),
        lambda s: aio.inventory_usecases.reserve(s, warehouse_id=1, units=5),
    ),
    Question(
        "inventory.reserve.refused",
        lambda s: inventory_usecases.reserve(s, warehouse_id=1, units=0),
        lambda s: aio.inventory_usecases.reserve(s, warehouse_id=1, units=0),
    ),
    # The orders domain, and it is the longest block here for a reason that is not endpoint count.
    # `reserve` and `settle` are the only operations in these demos that declare an isolation level,
    # take a row lock and rewind a savepoint, so this is where the asynchronous session is compared
    # against its twin doing the things it was actually built for. Every order carries a seeded
    # `placed_at`, which is why so many rows here declare a mint: the two colours get one database
    # FILE each and the seeder stamps them independently.
    Question(
        "orders.list_orders",
        lambda s: orders_usecases.list_orders(s),
        lambda s: aio.orders_usecases.list_orders(s),
        generates="every order carries a seeded `placed_at`, one per database build",
    ),
    Question(
        "orders.paginate_orders",
        lambda s: orders_usecases.paginate_orders(s, page=1, per_page=5),
        lambda s: aio.orders_usecases.paginate_orders(s, page=1, per_page=5),
        generates="the paged orders carry their seeded `placed_at`",
    ),
    Question(
        "orders.get_order",
        lambda s: orders_usecases.get_order(s, 1),
        lambda s: aio.orders_usecases.get_order(s, 1),
        generates="the order and its three parties carry seeded instants",
    ),
    Question(
        "orders.get_order.refused",
        lambda s: orders_usecases.get_order(s, 9999),
        lambda s: aio.orders_usecases.get_order(s, 9999),
    ),
    Question(
        "orders.order_lines",
        lambda s: orders_usecases.order_lines(s, 1),
        lambda s: aio.orders_usecases.order_lines(s, 1),
        generates="the included SKUs carry their seeded `created_at`",
    ),
    Question(
        # The existence check that costs a statement and is not skipped: an order with no lines and
        # an order that never existed are the same empty list without it.
        "orders.order_lines.refused",
        lambda s: orders_usecases.order_lines(s, 9999),
        lambda s: aio.orders_usecases.order_lines(s, 9999),
    ),
    Question(
        "orders.orders_of_customer",
        lambda s: orders_usecases.orders_of_customer(s, 4),
        lambda s: aio.orders_usecases.orders_of_customer(s, 4),
        generates="the orders and their lines carry seeded instants",
    ),
    Question(
        "orders.orders_of_customer.refused",
        lambda s: orders_usecases.orders_of_customer(s, 9999),
        lambda s: aio.orders_usecases.orders_of_customer(s, 9999),
    ),
    Question(
        "orders.orders_per_state",
        lambda s: orders_usecases.orders_per_state(s),
        lambda s: aio.orders_usecases.orders_per_state(s),
    ),
    Question(
        "orders.customer_orders",
        lambda s: orders_usecases.customer_orders(s),
        lambda s: aio.orders_usecases.customer_orders(s),
        generates="the annotated customers carry their seeded `created_at`",
    ),
    Question(
        "orders.place_order",
        lambda s: orders_usecases.place_order(
            s, reference="ORD-PARITY", customer_id=1, warehouse_id=2, lines=[(2, 3)]
        ),
        lambda s: aio.orders_usecases.place_order(
            s, reference="ORD-PARITY", customer_id=1, warehouse_id=2, lines=[(2, 3)]
        ),
        generates="`placed_at` is stamped with the clock at the moment of writing",
    ),
    Question(
        # The shape refused BEFORE anything is read: a repeated SKU says two different things about
        # one line, and both colours have to refuse it with the same word.
        "orders.place_order.refused",
        lambda s: orders_usecases.place_order(
            s,
            reference="ORD-DUP",
            customer_id=1,
            warehouse_id=2,
            lines=[(2, 1), (2, 4)],
        ),
        lambda s: aio.orders_usecases.place_order(
            s,
            reference="ORD-DUP",
            customer_id=1,
            warehouse_id=2,
            lines=[(2, 1), (2, 4)],
        ),
    ),
    Question(
        "orders.set_line",
        lambda s: orders_usecases.set_line(s, order_id=1, sku_id=4, quantity=2),
        lambda s: aio.orders_usecases.set_line(s, order_id=1, sku_id=4, quantity=2),
        generates="the re-read lines carry their SKUs' seeded `created_at`",
    ),
    Question(
        "orders.set_line.refused",
        lambda s: orders_usecases.set_line(s, order_id=1, sku_id=4, quantity=0),
        lambda s: aio.orders_usecases.set_line(s, order_id=1, sku_id=4, quantity=0),
    ),
    Question(
        "orders.remove_line",
        lambda s: orders_usecases.remove_line(s, order_id=1, sku_id=7),
        lambda s: aio.orders_usecases.remove_line(s, order_id=1, sku_id=7),
        generates="the re-total re-reads the lines, whose SKUs carry a seeded `created_at`",
    ),
    Question(
        "orders.remove_line.refused",
        lambda s: orders_usecases.remove_line(s, order_id=1, sku_id=9999),
        lambda s: aio.orders_usecases.remove_line(s, order_id=1, sku_id=9999),
    ),
    Question(
        # Order 2 is RESERVED, so this walks the half of the cancellation that gives the units back.
        # A boolean `cancelled` could not tell it from the DRAFT case, and one of the two would be
        # wrong every time without failing.
        "orders.cancel_order",
        lambda s: orders_usecases.cancel_order(s, order_id=2),
        lambda s: aio.orders_usecases.cancel_order(s, order_id=2),
        generates="the cancelled order carries its seeded `placed_at`",
    ),
    Question(
        "orders.cancel_order.refused",
        lambda s: orders_usecases.cancel_order(s, order_id=4),
        lambda s: aio.orders_usecases.cancel_order(s, order_id=4),
    ),
    Question(
        # Order 12 is a DRAFT whose single line the warehouse can cover, so this is the happy path
        # of the operation the domain was built around.
        "orders.reserve",
        lambda s: orders_usecases.reserve(s, order_id=12),
        lambda s: aio.orders_usecases.reserve(s, order_id=12),
        generates="the reserved order carries its seeded `placed_at`",
    ),
    Question(
        # Order 1 asks for more than the warehouse has free, and a shortage refuses the WHOLE order:
        # a partial reservation is not a state this domain has.
        "orders.reserve.refused",
        lambda s: orders_usecases.reserve(s, order_id=1),
        lambda s: aio.orders_usecases.reserve(s, order_id=1),
    ),
    Question(
        # Order 2 is RESERVED and subscription 3 belongs to its customer, so this settles: the
        # invoice is issued outside the savepoint, the payment and the shipment inside it.
        "orders.settle",
        lambda s: orders_usecases.settle(s, order_id=2, subscription_id=3),
        lambda s: aio.orders_usecases.settle(s, order_id=2, subscription_id=3),
        generates="the invoice and the payment are stamped with the clock as they are written",
    ),
    Question(
        # Subscription 1 belongs to somebody else. Nothing in the schema stops an order pointing at
        # another person's invoice, so the rule lives in the use case — and it has to refuse the
        # same way on both colours or one demo adds up money across two people who never met.
        "orders.settle.refused",
        lambda s: orders_usecases.settle(s, order_id=2, subscription_id=1),
        lambda s: aio.orders_usecases.settle(s, order_id=2, subscription_id=1),
    ),
    Question(
        "orders.attach_invoice",
        lambda s: orders_usecases.attach_invoice(s, order_id=1, invoice_id=1),
        lambda s: aio.orders_usecases.attach_invoice(s, order_id=1, invoice_id=1),
        generates="the billed order carries its seeded `placed_at`",
    ),
    Question(
        "orders.attach_invoice.refused",
        lambda s: orders_usecases.attach_invoice(s, order_id=1, invoice_id=9999),
        lambda s: aio.orders_usecases.attach_invoice(s, order_id=1, invoice_id=9999),
    ),
    Question(
        # Every seeded order has lines, so this is the FK-restrict path: the engine would refuse
        # anyway, from inside a commit, and checking first is what lets a delete page explain it.
        "orders.remove_order",
        lambda s: orders_usecases.remove_order(s, order_id=1),
        lambda s: aio.orders_usecases.remove_order(s, order_id=1),
    ),
    Question(
        "orders.remove_order.refused",
        lambda s: orders_usecases.remove_order(s, order_id=9999),
        lambda s: aio.orders_usecases.remove_order(s, order_id=9999),
    ),
    Question(
        "orders.order_report",
        lambda s: orders_usecases.order_report(s),
        lambda s: aio.orders_usecases.order_report(s),
        generates="every figure in the report is built over rows carrying seeded instants",
    ),
    # The traffic export, drained on both sides. The rows arrive NARROW — the query names three
    # columns — so a colour that lost the `only()` would return whole visits and diverge here.
    #
    # THE ANSWER IS PROJECTED RATHER THAN HANDED OVER WHOLE, and that is a property of these two
    # rows rather than a convenience. `_shape` compares models by `repr`, and the `repr` of a half
    # loaded row reads every column — including the ones the query deliberately left behind, which
    # RAISE by design. So the two narrowed questions compare the columns they asked for, which is
    # also the only comparison that means anything about them.
    Question(
        "engagement.stream_visits",
        lambda s: [
            (visit.id, visit.ip)
            for visit in engagement_usecases.stream_visits(s, post_id=1)
        ],
        lambda s: _drained_visits(s),
    ),
    Question(
        "content.revision_timeline",
        lambda s: [
            (revision.id, revision.post_id)
            for revision in content_usecases.revision_timeline(s, 1)
        ],
        lambda s: _drained_timeline(s),
    ),
    Question(
        "orders.stream_order_lines",
        lambda s: list(orders_usecases.stream_order_lines(s)),
        lambda s: _drained_lines(s),
        generates="the streamed lines carry their SKUs' seeded `created_at`",
    ),
    Question(
        # Not a database operation at all, and in the table anyway: it is the DEFAULT `settle` runs
        # when nobody hands it a processor, so the two colours disagreeing about what "accepted"
        # means would change what `settle` does on one demo and not the other.
        "orders.accept_every_charge",
        lambda s: orders_usecases.accept_every_charge(Decimal("10.00")),
        lambda s: aio.orders_usecases.accept_every_charge(Decimal("10.00")),
    ),
    # --- logistics: the domain whose answers the ENGINE computes ---------------------------------
    # Every row here matters more than the average one, and the reason is worth stating: this
    # domain's SQL is the hardest in the demos to check by eye. `RANGE BETWEEN 2 PRECEDING AND 2
    # FOLLOWING` written twice would be two frames somebody has to compare by reading, and the
    # difference between it and `ROWS` does not surface as an error — it surfaces as one demo quietly
    # answering a different question. Comparing the STATEMENTS is what makes that impossible.
    Question(
        "logistics.list_depots",
        lambda s: logistics_usecases.list_depots(s),
        lambda s: aio.logistics_usecases.list_depots(s),
    ),
    Question(
        # The sheet: three statements, a square root over a sum of squares as the ORDER BY key, and
        # two roundings of one division. If any of the four drifted, this is where it shows.
        "logistics.delivery_sheet",
        lambda s: logistics_usecases.delivery_sheet(s, 1),
        lambda s: aio.logistics_usecases.delivery_sheet(s, 1),
        generates="the sheet carries the delivery's seeded promise, minted per database file",
    ),
    Question(
        "logistics.delivery_sheet.refused",
        lambda s: logistics_usecases.delivery_sheet(s, 9999),
        lambda s: aio.logistics_usecases.delivery_sheet(s, 9999),
    ),
    Question(
        "logistics.dispatch_board",
        lambda s: logistics_usecases.dispatch_board(s, limit=5),
        lambda s: aio.logistics_usecases.dispatch_board(s, limit=5),
        generates="the promises are seeded instants, so the two database files date them apart",
    ),
    Question(
        "logistics.slot_load",
        lambda s: logistics_usecases.slot_load(s, limit=10),
        lambda s: aio.logistics_usecases.slot_load(s, limit=10),
    ),
    Question(
        # The one WRITE, and it is here for the reason the whole file exists: the two colours pick
        # the depot with the same statement and then have to agree on what the sheet says AFTER it.
        "logistics.reroute_delivery",
        lambda s: logistics_usecases.reroute_delivery(s, 1),
        lambda s: aio.logistics_usecases.reroute_delivery(s, 1),
        generates="the sheet it answers with carries the delivery's seeded promise",
    ),
    Question(
        "logistics.reroute_delivery.refused",
        lambda s: logistics_usecases.reroute_delivery(s, 9999),
        lambda s: aio.logistics_usecases.reroute_delivery(s, 9999),
    ),
)


async def _drained_lines(session: AsyncSession) -> list[OrderLine]:
    """Drains the asynchronous order-line stream, for the same reason `_drained_movements` does."""
    return [
        line async for line in await aio.orders_usecases.stream_order_lines(session)
    ]


async def _drained_movements(session: AsyncSession) -> list[StockMovement]:
    """Drains the asynchronous stream so it can be compared with the synchronous list.

    `AsyncSession.iterate` is NOT a coroutine — it hands back the iterator straight away, exactly as
    the synchronous one does — so the twin has nothing to await inside it and the call shape becomes
    `async for x in await stream(...)`. Comparing the two unconsumed iterators would compare two
    objects that have run no SQL at all, which is the one thing this file must not do.
    """
    return [
        movement
        async for movement in await aio.inventory_usecases.stream_movements(
            session, warehouse_id=1
        )
    ]


def _build_database(path: Path) -> None:
    """Creates the demo schema on a SQLite FILE and seeds it, with the synchronous driver.

    Setting up needs no async, the same way `src/test/integration/test_async_e2e.py` builds its
    table with psycopg2 before driving psycopg 3 over it.
    """
    driver = SQLiteDriver.connect(str(path))
    dialect = SQLiteDialect()
    for model in MODELS:
        driver.execute(emit_create_table(snake_table(model), dialect), ())
    # The views LAST: they read from the tables, so the tables have to be there first.
    for view in VIEWS:
        driver.execute(emit_create_view(snake_table(view), dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    seed(session, Scale.MINIMAL)
    session.close()


def _recording(collector: DebugCollector) -> Recording:
    """Freezes a capture scope into the two things worth comparing across colours."""
    report = collector.report()
    return Recording(
        statements=tuple((record.sql, record.params) for record in report.records),
        warnings=report.warnings,
    )


Answers = tuple[object, Recording, object, Recording]


def _ask(directory: Path, question: Question) -> Answers:
    """Asks the question of both colours over the same seed, and records both runs.

    Each colour gets its OWN database file, built from the same seeder. That is not tidiness: half
    these questions WRITE, and sharing one file would let the synchronous `create_role` shift the
    ids the asynchronous one then reads, turning a parity test into a test of who ran first.
    """
    synchronous_path = directory / f"{question.name}-sync.sqlite"
    asynchronous_path = directory / f"{question.name}-async.sqlite"
    _build_database(synchronous_path)
    _build_database(asynchronous_path)

    session = SnakeSession(
        CaptureDriver(SQLiteDriver.connect(str(synchronous_path))), SQLiteDialect()
    )
    try:
        with capture_queries() as collector:
            synchronous = question.ask(session)
        sync_recording = _recording(collector)
    finally:
        session.close()

    async def asked() -> tuple[object, Recording]:
        driver = await AsyncSQLiteDriver.connect(str(asynchronous_path))
        asynchronous_session = AsyncSession(AsyncCaptureDriver(driver), SQLiteDialect())
        try:
            with capture_queries() as async_collector:
                answer = await question.ask_async(asynchronous_session)
            return answer, _recording(async_collector)
        finally:
            await asynchronous_session.close()

    # `asyncio.run` and not a pytest plugin: this repository drives its async tests this way
    # already, and a plugin for four lines would be a dependency nobody needs.
    asynchronous, async_recording = asyncio.run(asked())
    return synchronous, sync_recording, asynchronous, async_recording


@pytest.fixture(scope="session")
def ask(tmp_path_factory: pytest.TempPathFactory) -> Callable[[Question], Answers]:
    """Asks a question of both colours, ONCE per question however many assertions read the result.

    Three separate tests read the same run —the answer, the SQL, the message— and each of them
    deserves to fail on its own, saying which of the three broke. Building and seeding the schema
    three times over to get that would be paying twenty-nine `CREATE TABLE`s for a cache miss, so the
    run is memoised and the assertions stay separate.
    """
    directory = tmp_path_factory.mktemp("parity")
    answers: dict[str, Answers] = {}

    def asker(question: Question) -> Answers:
        if question.name not in answers:
            answers[question.name] = _ask(directory, question)
        return answers[question.name]

    return asker


# What an operation can mint at call time: a UUID, an instant, or a secret. Blanked only in the rows
# that DECLARE they mint one, so a row that says nothing keeps comparing every character.
_MINTED = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:?\d{2})?"
    # Base64 as well as url-safe base64: a scrypt hash is `scrypt$<salt>$<key>` and its two halves
    # carry `+`, `/` and `=`, which the url-safe alphabet does not have.
    r"|[A-Za-z0-9_+/=-]{24,}"
    # The parameters travel as Python objects, so an instant reaches the comparison as the repr of a
    # `datetime` and not as the ISO text above. Both spellings of the same minted value.
    r"|datetime\.datetime\([^()]*\)"
    r"|SnakeUtc\([^()]*\)"
)


def _blank(text: str) -> str:
    """Replaces whatever the operation minted with a marker, leaving the rest to compare exactly."""
    return _MINTED.sub("<minted>", text)


_CALLER = re.compile(r" at \S+:\d+: ")
"""The `at file:line:` an N+1 warning carries. It names the CALLER, so it differs by colour."""


def _blank_caller(warnings: tuple[str, ...]) -> tuple[str, ...]:
    """Blanks the caller location out of each warning; the count and the SQL still compare exactly."""
    return tuple(_CALLER.sub(" at <caller>: ", warning) for warning in warnings)


def _shape(value: object) -> object:
    """A comparable rendering of an answer, whatever shape the use case returns.

    `repr` on a model and not the instance itself, because a `@snake_model` declares no `__eq__`:
    two hydrations of the same row are two objects, and comparing them directly would compare
    identity and pass for the wrong reason. The `repr` carries every column, which is what the
    comparison is about; a relation the query forgot to load is caught by the SQL instead.
    """
    if isinstance(value, Failure):
        return f"Failure({value.reason})"
    if isinstance(value, list):
        return [_shape(item) for item in value]
    if value is None:
        return None
    return repr(value)


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda question: question.name)
def test_both_colours_give_the_same_answer(
    question: Question, ask: Callable[[Question], Answers]
) -> None:
    """The answer is the same whichever session asked: same rows, same failure, same reason."""
    synchronous, _, asynchronous, _ = ask(question)

    if question.generates:
        assert _blank(repr(_shape(asynchronous))) == _blank(repr(_shape(synchronous)))
    else:
        assert _shape(asynchronous) == _shape(synchronous)


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda question: question.name)
def test_both_colours_emit_the_same_sql(
    question: Question, ask: Callable[[Question], Answers]
) -> None:
    """The same statements in the same order with the same parameters, because it is ONE fragment.

    This is the assertion that proves the seam rather than the outcome. Two independent
    implementations can agree on the answer for a long time while emitting different SQL — one of
    them quietly loading a relation row by row — and the answer alone would never say so.
    """
    _, synchronous, _, asynchronous = ask(question)

    if question.generates:
        assert [
            (sql, _blank(repr(params))) for sql, params in asynchronous.statements
        ] == [(sql, _blank(repr(params))) for sql, params in synchronous.statements]
    else:
        assert asynchronous.statements == synchronous.statements


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda question: question.name)
def test_both_colours_say_the_same_thing_about_that_sql(
    question: Question, ask: Callable[[Question], Answers]
) -> None:
    """The ORM's complaint about the run is identical, word for word, on both paths.

    Matching SQL is not enough, and the reason is in this repository's own history: the two sessions
    once explained the same complaint with two different wordings, and the check that only looked at
    the SQL passed the whole time. What the developer READS is the product.

    EXCEPT the caller the warning names, which cannot match and must not be asked to. An N+1 warning
    now ends in the `file:line` that fires the repeat, and that line is the CALLER — `shared/aio/`
    on one side, `shared/usecases/` or the selector on the other. Two different files is not drift,
    it is the duplication this whole file exists to watch. So the location is blanked, exactly the
    way a minted value is, and the count and the SQL still compare character for character. What is
    kept is the assertion below: both colours must name SOME caller, so a location that vanished on
    one side is still a failure.
    """
    _, synchronous, _, asynchronous = ask(question)

    assert _blank_caller(asynchronous.warnings) == _blank_caller(synchronous.warnings)
    assert sum(_CALLER.search(w) is not None for w in asynchronous.warnings) == sum(
        _CALLER.search(w) is not None for w in synchronous.warnings
    )


def test_the_table_covers_every_asynchronous_use_case() -> None:
    """Every public function in `shared/aio/` appears in the table above, asked of both colours.

    Without this the table is a sample, and a sample of a mirror is not a mirror: an operation added
    to both layers and to no row here would be a use case whose two colours nobody ever compared —
    precisely the state this file exists to make impossible.
    """
    asked = {question.name for question in QUESTIONS}
    missing = sorted(
        f"{domain}.{name}"
        for domain, names in aio.public_functions().items()
        for name in names
        if not any(
            entry == f"{domain}.{name}" or entry.startswith(f"{domain}.{name}.")
            for entry in asked
        )
    )

    assert missing == [], (
        f"these asynchronous use cases are never compared against their synchronous twin: "
        f"{missing}. Add a row to QUESTIONS in this file."
    )


async def _drained_visits(session: AsyncSession) -> list[tuple[int, str]]:
    """Drains the asynchronous traffic stream, projecting the two columns the file prints.

    Two reasons in one line: the stream has to be CONSUMED before it can be compared —
    `_drained_movements` says why — and the rows are NARROW, so only the columns the query asked for
    can be read off them at all.
    """
    return [
        (visit.id, visit.ip)
        async for visit in await aio.engagement_usecases.stream_visits(
            session, post_id=1
        )
    ]


async def _drained_timeline(session: AsyncSession) -> list[tuple[int, int]]:
    """The asynchronous revision timeline, projected: its rows carry no `body` to compare."""
    return [
        (revision.id, revision.post_id)
        for revision in await aio.content_usecases.revision_timeline(session, 1)
    ]
