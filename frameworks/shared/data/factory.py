"""DETERMINISTIC data generator for the 29 tables, at the requested scale.

Stdlib only (`random.Random` with a fixed seed, no faker): the same scale ALWAYS produces the same
data, so the debug panel is reproducible across boots. It inserts in dependency order and uses
`session.add_all` (batched multi-row INSERT) for everything; visits —the big table— are seeded in
BATCHES so millions of objects are not built in memory at once.

`add_all` fills the `id` IN-PLACE after the INSERT (RETURNING), so the inserted instances already
work as parents for the children's FKs, without re-reading anything. The PRIMARY entities (users,
blogs, posts, comments, visits, tags) are fixed by the `Scale`; the rest is DERIVED by per-parent
ratios.

Demo login: every user shares the `DEMO_PASSWORD` password (hashed ONCE and the same hash reused,
salt included), so seeding is fast even at massive scale.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from random import Random
from typing import TypeVar

from snakeorm import SnakeModel, SnakeSession, SnakeUtc

from shared.auth import hash_password
from shared.data.scales import Scale
from shared.models import (
    Delivery,
    Depot,
    MovementReason,
    PackagingUnit,
    Order,
    OrderLine,
    OrderState,
    Sku,
    SkuKind,
    Stock,
    StockMovement,
    Warehouse,
    ApiToken,
    Attachment,
    Blog,
    Category,
    Comment,
    Invoice,
    CardPayment,
    LoginSession,
    Payment,
    PaypalPayment,
    Plan,
    Post,
    PostRevision,
    PostTag,
    Reaction,
    Role,
    Subscription,
    TransferPayment,
    Tag,
    TagGroup,
    User,
    WalletPayment,
    UserRole,
    Visit,
)

# Type variable for the generic insertion helper (classic PEP 484; the project is 3.11+).
M = TypeVar("M", bound=SnakeModel)

# Fixed seed: the same data on every boot (reproducible panel).
_SEED = 20240501

# Demo password for EVERY seeded user (documented; the login uses "test1234").
DEMO_PASSWORD = "test1234"

# Time window of the history: timestamps are spread over this range (aware, UTC).
_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
_SPAN_SECONDS = int((_END - _START).total_seconds())

# Batch size of the VOLUME table: rows are built and inserted N at a time (bounded memory).
_VISIT_BATCH = 5_000

# ---- Lexicon (stdlib, no faker): small pools the RNG combines ------------------------------------

_ROLE_NAMES = ("admin", "author", "reader")
_PLAN_ROWS = (("free", 0), ("pro", 900), ("team", 2900))
_TAG_GROUP_NAMES = ("temas", "lenguajes", "niveles", "formatos")
_TAG_POOL = (
    "python",
    "sql",
    "orm",
    "typing",
    "async",
    "testing",
    "architecture",
    "performance",
    "security",
    "postgres",
    "sqlite",
    "migrations",
    "tooling",
    "design",
    "patterns",
    "clean-code",
    "ci",
    "docs",
    "beginner",
    "advanced",
    "tutorial",
    "deep-dive",
    "opinion",
    "release",
    "benchmark",
    "internals",
)

# THE SHAPE OF THE TAXONOMY, as `child name -> parent name`. A tag missing from this mapping is a
# ROOT, which is why the mapping holds only the children: writing `"python": None` for every root
# would be a second way of saying the same thing, and two spellings of one fact drift.
#
# It is a real tree and not a chain of pairs, and that is what the pages need to be worth drawing:
# `python > async > performance` is three deep, so a breadcrumb has something to print and a walk
# that only went up one level would visibly stop short. Every parent appears EARLIER in `_TAG_POOL`
# than its child, which is what lets the waves below insert a parent before the row that points at
# it without sorting anything.
_TAG_PARENTS = {
    "orm": "sql",
    "typing": "python",
    "async": "python",
    "performance": "async",
    "security": "architecture",
    "postgres": "sql",
    "sqlite": "sql",
    "migrations": "orm",
    "design": "architecture",
    "patterns": "design",
    "clean-code": "patterns",
    "ci": "tooling",
    "docs": "tooling",
    "benchmark": "performance",
    "internals": "architecture",
}
_ADJECTIVES = (
    "hidden",
    "practical",
    "deep",
    "gentle",
    "modern",
    "typed",
    "compiled",
    "elegant",
    "brutal",
    "clean",
    "fast",
    "lazy",
    "strict",
    "recursive",
    "portable",
)
_NOUNS = (
    "descriptors",
    "joins",
    "subqueries",
    "aggregates",
    "migrations",
    "dialects",
    "sessions",
    "relations",
    "metadata",
    "indexes",
    "constraints",
    "pipelines",
    "queries",
    "seams",
    "types",
)
_KINDS = ("like", "love", "wow", "insightful", "bookmark")
# The four KINDS a payment can be, as classes rather than as words: `method` is the discriminator
# now, so the class is what carries it. Choosing a string here and passing it as `method=` is exactly
# what stopped being possible, and it is the same reason it stopped — the word and the shape of the
# row were two independent facts that happened to agree.
_METHODS: tuple[type[Payment], ...] = (
    CardPayment,
    PaypalPayment,
    TransferPayment,
    WalletPayment,
)
_AGENTS = (
    "Mozilla/5.0 (Firefox)",
    "Mozilla/5.0 (Chrome)",
    "Mozilla/5.0 (Safari)",
    "curl/8.4",
    None,
)


_WAREHOUSE_ROWS: tuple[tuple[str, str], ...] = (
    ("MAD", "Madrid central"),
    ("BCN", "Barcelona port"),
    ("SVQ", "Sevilla south"),
    ("BIO", "Bilbao north (closed)"),
)
"""Four warehouses, the last one closed: the partial index over the active ones needs a row that is
NOT active, or it indexes everything and proves nothing."""


_DEPOT_ROWS: tuple[tuple[str, str, float, float], ...] = (
    ("MAD", "Madrid Vallecas", 40.4, -3.6),
    ("BCN", "Barcelona Zona Franca", 41.3, 2.1),
    ("SVQ", "Sevilla La Negrilla", 37.4, -5.9),
    ("VLC", "Valencia Fuente del Jarro", 39.5, -0.4),
)
"""Four depots, spread wide enough that a destination has an unambiguous nearest one.

Not decoration: the sheet ranks depots by distance and says whether the assigned one won, so with
depots clustered together the ranking would be noise and the routing verdict would flip with the last
digit of a float. These are the real coordinates of four Spanish industrial estates, rounded to a
tenth of a degree — about eleven kilometres, which is far below the distance between any two of them.
"""

_PACKAGING_ROWS: tuple[tuple[str, int], ...] = (
    ("carton", 12),
    ("crate", 25),
    ("pallet", 48),
)
"""Three box sizes, and NONE of them divides the unit counts below evenly on purpose.

That is the whole point of seeding three: the picking slip shows how many boxes get a label (rounded
UP) and how many leave sealed (rounded DOWN), and those two figures are equal whenever the division
comes out exact. A seed where every delivery packed cleanly would draw a page on which the two
columns always agreed — which is a page that proves nothing about either rounding.
"""


def _insert(session: SnakeSession, rows: Sequence[M]) -> list[M]:
    """Inserts `rows` and RETURNS them with the id already filled IN-PLACE. Empty list = no-op.

    The seeder NEEDS the ids: every batch is the parent for the next one's FKs. With `RETURNING`,
    `add_all` fills them in and a single statement is enough.

    Without `RETURNING` (MySQL) they are not filled in, and that is not an ORM oversight:
    `last_insert_id` talks about ONE row, and whether the ids of a multi-row INSERT come out
    consecutive depends on the server configuration (`innodb_autoinc_lock_mode`), not on the ORM.
    Deducing them would mean writing foreign keys in silence. So here the price is paid explicitly:
    one insert per row, which does recover the id. Slower and correct, instead of fast and false.
    """
    materialized = list(rows)
    if not materialized:
        return materialized
    if session.dialect.supports_returning:
        session.add_all(materialized)
    else:
        for row in materialized:
            session.add(row)
    return materialized


def _insert_leaves(session: SnakeSession, rows: Sequence[M]) -> None:
    """Inserts rows whose id NOBODY needs: always batched, on every engine.

    These are the leaves of the graph —visits, comments, reactions, payments, the bridge tables—:
    nothing references them afterwards, so it does not matter that the id never comes back. And they
    are the vast majority of the volume: at `normal` scale there are 20,000 visits and 2,000 comments
    against 60 users.

    Telling them apart from `_insert` is what keeps seeding fast on an engine without `RETURNING`:
    without this, the price of recovering 60 ids was also paid for the 20,000 rows whose id nobody
    was ever going to look at.

    Whether the split is correct does not depend on remembering it: if a leaf turned out not to be
    one, the missing id would arrive as a foreign key on another row and the required-column guard
    would say so by name. Getting it wrong is allowed; not finding out is not.
    """
    materialized = list(rows)
    if materialized:
        session.add_all(materialized)


def _rand_dt(rng: Random, *, after: SnakeUtc | None = None) -> SnakeUtc:
    """A `SnakeUtc` inside the history window, optionally later than `after` (so a comment or a
    visit lands AFTER the post it belongs to).

    It returns the ORM's OWN instant type and not a `datetime`, and that is the point rather than a
    nicety: every column here is declared `SnakeColumn[SnakeUtc]`, so handing it a plain `datetime`
    is the ORM's own contract broken by the code that exists to demonstrate it. Thirty-three call
    sites were doing it, and nobody saw them because `frameworks/` sat outside the type gate.

    `SnakeUtc.of(...)` is the conversion the ORM publishes for exactly this: an aware datetime in,
    an instant out.
    """
    low = _START if after is None else max(_START, after)
    low_off = int((low - _START).total_seconds())
    offset = rng.randint(min(low_off, _SPAN_SECONDS), _SPAN_SECONDS)
    return SnakeUtc.of(_START + timedelta(seconds=offset))


def _ip(rng: Random) -> str:
    """A pseudo-random IPv4 (private 10.x range) for visits and sessions."""
    return f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


def seed(session: SnakeSession, scale: Scale) -> None:
    """Fills the 29 tables at the given scale. Assumes the schema is ALREADY created; commits it all."""
    spec = scale.spec
    rng = Random(_SEED)
    demo_hash = hash_password(DEMO_PASSWORD)

    # ---- Small catalogs (no FKs) ----------------------------------------------------------------
    roles = _insert(session, [Role(name=name) for name in _ROLE_NAMES])
    plans = _insert(
        session, [Plan(name=name, price_cents=cents) for name, cents in _PLAN_ROWS]
    )
    groups = _insert(session, [TagGroup(name=name) for name in _TAG_GROUP_NAMES])

    # ---- Users (root of the graph): demo1, demo2, ... (predictable login for the demo) -----------
    def _username(i: int) -> str:
        return f"demo{i + 1}"

    users = _insert(
        session,
        [
            User(
                username=_username(i),
                email=f"{_username(i)}@demo.dev",
                password_hash=demo_hash,
            )
            for i in range(spec.users)
        ],
    )
    user_ids = [user.id for user in users]

    # ---- User roles (N—N): 1..2 roles per user --------------------------------------------------
    user_roles: list[UserRole] = []
    for user in users:
        for role in rng.sample(roles, k=rng.randint(1, 2)):
            user_roles.append(UserRole(user_id=user.id, role_id=role.id))
    _insert_leaves(session, user_roles)

    # ---- Tokens and sessions (1—N per user) -----------------------------------------------------
    tokens: list[ApiToken] = []
    sessions: list[LoginSession] = []
    for user in users:
        for t in range(rng.randint(0, 2)):
            tokens.append(
                ApiToken(
                    token=f"tok_{user.id}_{t}_{rng.randint(1000, 9999)}",
                    label=rng.choice(("cli", "ci", "mobile", None)),
                    revoked=rng.random() < 0.15,
                    user_id=user.id,
                    expires_at=_rand_dt(rng),
                )
            )
        for _ in range(rng.randint(1, 3)):
            sessions.append(
                LoginSession(
                    user_id=user.id,
                    ip=_ip(rng),
                    user_agent=rng.choice(_AGENTS),
                    last_seen_at=_rand_dt(rng),
                )
            )
    _insert_leaves(session, tokens)
    _insert_leaves(session, sessions)

    # ---- Blogs and categories -------------------------------------------------------------------
    blogs = _insert(
        session,
        [
            Blog(
                title=f"{rng.choice(_ADJECTIVES).title()} {rng.choice(_NOUNS).title()}",
                slug=f"blog-{i}",
                description=rng.choice(
                    (None, "A demo blog from the SnakeORM laboratory.")
                ),
                owner_id=rng.choice(user_ids),
            )
            for i in range(spec.blogs)
        ],
    )
    categories = _insert(
        session,
        [
            Category(
                name=rng.choice(_NOUNS).title(),
                slug=f"cat-{blog.id}-{j}",
                blog_id=blog.id,
            )
            for blog in blogs
            for j in range(rng.randint(2, 4))
        ],
    )
    cats_by_blog: dict[int, list[int]] = {}
    for cat in categories:
        cats_by_blog.setdefault(cat.blog_id, []).append(cat.id)

    # ---- Posts (with an OPTIONAL category) ------------------------------------------------------
    post_rows: list[Post] = []
    for i in range(spec.posts):
        blog = rng.choice(blogs)
        blog_cats = cats_by_blog.get(blog.id, [])
        post_rows.append(
            Post(
                title=f"{rng.choice(_ADJECTIVES).title()} {rng.choice(_NOUNS)} #{i}",
                body=f"Body of post {i}. " + " ".join(rng.sample(_NOUNS, k=4)),
                published=rng.random() < 0.8,
                blog_id=blog.id,
                category_id=(
                    rng.choice(blog_cats) if blog_cats and rng.random() < 0.8 else None
                ),
                author_id=rng.choice(user_ids),
                created_at=_rand_dt(rng),
            )
        )
    posts = _insert(session, post_rows)
    post_created = {post.id: post.created_at for post in posts}
    post_ids = [post.id for post in posts]

    # ---- Revisions and attachments (1—N per post) -----------------------------------------------
    revisions: list[PostRevision] = []
    attachments: list[Attachment] = []
    for post in posts:
        base = post_created[post.id]
        for r in range(rng.randint(0, 2)):
            revisions.append(
                PostRevision(
                    post_id=post.id,
                    body=f"Revision {r} of post {post.id}.",
                    edited_at=_rand_dt(rng, after=base),
                )
            )
        for a in range(rng.randint(0, 2)):
            attachments.append(
                Attachment(
                    post_id=post.id,
                    filename=f"file-{post.id}-{a}.png",
                    url=f"https://cdn.demo/{post.id}/{a}.png",
                    size_bytes=rng.randint(1024, 5_000_000),
                )
            )
    _insert_leaves(session, revisions)
    _insert_leaves(session, attachments)

    # ---- Comments (total fixed by the scale, spread across posts) -------------------------------
    _insert_leaves(
        session,
        [
            _make_comment(rng, post_ids, user_ids, post_created)
            for _ in range(spec.comments)
        ],
    )

    # ---- Reactions (derived: ~0..6 per post) ----------------------------------------------------
    reactions: list[Reaction] = []
    for post in posts:
        base = post_created[post.id]
        for _ in range(rng.randint(0, 6)):
            reactions.append(
                Reaction(
                    kind=rng.choice(_KINDS),
                    post_id=post.id,
                    user_id=rng.choice(user_ids),
                    created_at=_rand_dt(rng, after=base),
                )
            )
    _insert_leaves(session, reactions)

    # ---- Visits: the VOLUME table, seeded in BATCHES --------------------------------------------
    remaining = spec.visits
    while remaining > 0:
        batch_n = min(_VISIT_BATCH, remaining)
        _insert_leaves(
            session, [_make_visit(rng, post_ids, post_created) for _ in range(batch_n)]
        )
        remaining -= batch_n

    # ---- Tags: a TREE (with a group) + N—N post_tags ---------------------------------------------
    #
    # The names and their groups are drawn FIRST, in pool order, and the rows are inserted
    # afterwards in waves by depth. That split is what keeps the seed deterministic: `rng` is
    # consumed once per tag in the same order it always was, so nesting the taxonomy does not
    # reshuffle every other table that draws after it.
    #
    # The waves are what the foreign key demands — a row cannot point at a parent that has not been
    # inserted yet — and a wave is a batch, so the whole tree still costs one statement per LEVEL
    # rather than one per tag.
    drawn = [
        (
            (_TAG_POOL[i] if i < len(_TAG_POOL) else f"tag{i}"),
            rng.choice(groups).id,
        )
        for i in range(spec.tags)
    ]
    seeded = {name for name, _ in drawn}
    tags: list[Tag] = []
    identifiers: dict[str, int] = {}
    pending = list(drawn)
    while pending:
        # A tag whose parent was not seeded at this scale is a root: the small scales stop part way
        # down `_TAG_POOL`, and an orphan pointing at a row that does not exist is not a tree.
        wave = [
            (name, group_id)
            for name, group_id in pending
            if _TAG_PARENTS.get(name) not in seeded or _TAG_PARENTS[name] in identifiers
        ]
        inserted = _insert(
            session,
            [
                Tag(
                    name=name,
                    group_id=group_id,
                    parent_id=identifiers.get(_TAG_PARENTS.get(name, "")),
                )
                for name, group_id in wave
            ],
        )
        identifiers.update({tag.name: tag.id for tag in inserted})
        tags.extend(inserted)
        pending = [row for row in pending if row not in wave]
    tag_ids = [tag.id for tag in tags]
    post_tags: list[PostTag] = []
    for post in posts:
        for tag_id in rng.sample(tag_ids, k=min(len(tag_ids), rng.randint(1, 4))):
            post_tags.append(PostTag(post_id=post.id, tag_id=tag_id))
    _insert_leaves(session, post_tags)

    # ---- Subscriptions -> invoices -> payments (the billing chain) ------------------------------
    subs = _insert(
        session,
        [
            Subscription(
                active=rng.random() < 0.75,
                user_id=user_id,
                plan_id=rng.choice(plans).id,
                started_at=_rand_dt(rng),
            )
            for user_id in user_ids
            if rng.random() < 0.6
        ],
    )
    invoices = _insert(
        session,
        [
            Invoice(
                amount_cents=rng.choice((900, 2900)),
                paid=rng.random() < 0.7,
                subscription_id=sub.id,
                issued_at=_rand_dt(rng),
            )
            for sub in subs
            for _ in range(rng.randint(1, 3))
        ],
    )
    # ONE BATCH PER KIND, and it is a requirement rather than a preference: `add_all` emits a single
    # INSERT with one column list, so it takes one model at a time. The four kinds share a physical
    # table but they are four classes, and the ORM says so by name instead of guessing. Grouping them
    # is also what a real bulk load does — the card payments arrive from one place and the transfers
    # from another.
    payments_by_kind: dict[type[Payment], list[Payment]] = {
        kind: [] for kind in _METHODS
    }
    for inv in invoices:
        if rng.random() < 0.9:
            kind = rng.choice(_METHODS)
            payments_by_kind[kind].append(
                kind(
                    amount_cents=inv.amount_cents,
                    invoice_id=inv.id,
                    paid_at=_rand_dt(rng),
                )
            )
    for batch in payments_by_kind.values():
        _insert_leaves(session, batch)

    # ---- Warehouses -> SKUs -> stock (COMPOSITE key) -> movements --------------------------------
    # The stock rows are the only ones in the whole seed whose identity is a PAIR, so they carry no
    # id of their own and nothing has to come back from the server: they go in as leaves. Their
    # movements then reference that pair with two columns, which is the shape that makes a to-many
    # bind two placeholders per parent.
    warehouses = _insert(
        session,
        [
            Warehouse(
                code=code,
                name=name,
                active=index < 3,
                opened_on=date(2019 + index, 1 + index, 5 + index),
                shift_start=time(6 + index, 30),
                # With an OFFSET: the cutoff is one moment for every warehouse, so it has to say
                # which. `shift_start` right above carries none, and that is the whole point.
                cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
            )
            for index, (code, name) in enumerate(_WAREHOUSE_ROWS)
        ],
    )
    skus = _insert(
        session,
        [
            Sku(
                name=f"{rng.choice(_ADJECTIVES).title()} {rng.choice(_NOUNS)} #{index}",
                kind=rng.choice(tuple(SkuKind)),
                price=Decimal(f"{rng.randint(2, 400)}.{rng.randint(0, 99):02d}"),
                weight_kg=round(rng.uniform(0.1, 40.0), 2),
                lead_time=timedelta(days=rng.randint(1, 21)),
                attrs={"origin": rng.choice(_NOUNS), "fragile": rng.random() < 0.3},
                related_ids=sorted(rng.sample(range(1, 40), k=rng.randint(0, 3))),
                thumbnail=None,
            )
            for index in range(spec.skus)
        ],
    )
    stock_rows: list[Stock] = []
    movements: list[StockMovement] = []
    # What each warehouse ends up holding, kept as it is built: the orders below pick their SKUs
    # from HERE and not from the whole catalogue. A line whose warehouse never stocked that SKU has
    # no stock row to lock, so phase 3's reservation would be locking nothing while going green.
    stock_by_warehouse: dict[int, list[Stock]] = {}
    for warehouse in warehouses:
        for sku in rng.sample(skus, k=max(1, len(skus) // 2)):
            on_hand = rng.randint(0, 500)
            row = Stock(
                warehouse_id=warehouse.id,
                sku_id=sku.id,
                on_hand=on_hand,
                reserved=min(on_hand, rng.randint(0, 20)),
                counted_at=None,
                counted_local=None,
            )
            stock_rows.append(row)
            stock_by_warehouse.setdefault(warehouse.id, []).append(row)
            for _ in range(rng.randint(1, 3)):
                movement = StockMovement(
                    stock_warehouse_id=warehouse.id,
                    stock_sku_id=sku.id,
                    delta=rng.randint(-40, 120),
                    reason=rng.choice(tuple(MovementReason)),
                    note=None,
                )
                # SPREAD OVER THE HISTORY, like every other date here. `happened_at` is
                # server-defaulted, so left alone every seeded movement claims the instant the seed
                # ran — one bulk INSERT, one `CURRENT_TIMESTAMP` — and every page that orders a
                # movement by when it happened was ordering a tie.
                movement.happened_at = _rand_dt(rng)
                movements.append(movement)
    # ONE pair that is genuinely RUNNING OUT, and it is deliberate for the reason the unreservable
    # order below is: the reorder screen reads a VIEW whose threshold lives in the database, and the
    # random levels above cleared that threshold on every row at the minimal scale — so the page that
    # answers "what do I need to reorder" was being demonstrated over an empty table. Measured: zero
    # low rows at MINIMAL and eight at NORMAL, which is the worst of both, because it means the
    # fixture passes on the machine with the bigger seed and shows nothing on the other.
    #
    # IT MOVES `reserved` AND NEVER `on_hand`, and that is not tidiness. The order planner further
    # down reads `wanted[0].on_hand` to build the line that cannot be reserved, so lowering the shelf
    # here would quietly retune a different fixture two hundred lines away. Raising what is PROMISED
    # is also the truer half: the view was rewritten to compare AVAILABLE rather than the shelf
    # precisely because fifty units of which forty-five are spoken for is five you can actually sell.
    running_out = stock_rows[0]
    running_out.reserved = max(0, running_out.on_hand - 4)

    # TWO IDENTICAL SHIPMENTS, at the newest instant of the window so the book always opens on them.
    # Two units of one SKU leaving one warehouse at one instant are two orders, and the movement
    # book joins its two origins with `UNION ALL` precisely so both lines print. Over random deltas
    # and spread instants the page would give a correct answer while never once showing the case it
    # exists for, which is the quiet way a demonstration stops demonstrating anything.
    for _ in range(2):
        twin = StockMovement(
            stock_warehouse_id=running_out.warehouse_id,
            stock_sku_id=running_out.sku_id,
            delta=-1,
            reason=MovementReason.SALE,
            note=None,
        )
        twin.happened_at = SnakeUtc.of(_END)
        movements.append(twin)

    _insert_leaves(session, stock_rows)
    _insert_leaves(session, movements)

    # ---- Orders -> lines (the SECOND COMPOSITE key) ----------------------------------------------
    # The joint, and the reason this domain exists: an order belongs to a USER, ships from a
    # WAREHOUSE, wants SKUs and — once billed — points at an INVOICE. It is seeded LAST because it is
    # the only domain that depends on three others.
    #
    # And it is seeded with SITUATIONS rather than with noise. Phase 3's operations need one order in
    # every state, one asking for more units than its warehouse holds, and settled orders that really
    # do carry an invoice; data that only usually contains them is the worst kind of fixture, because
    # it passes here and fails on somebody else's machine.
    subscription_owner = {sub.id: sub.user_id for sub in subs}
    invoices_by_user: dict[int, list[int]] = {}
    for invoice in invoices:
        invoices_by_user.setdefault(
            subscription_owner[invoice.subscription_id], []
        ).append(invoice.id)
    # Only a customer who HAS an invoice can be given a billed state. Pointing an order at an invoice
    # belonging to somebody else would seed a graph that no query can make sense of, and the report
    # that joined the two would be adding up other people's money.
    billable = sorted(invoices_by_user)
    # Said out loud rather than left to blow up inside `random`: with no invoiced user there is no
    # order that can carry a billed state, and the failure would otherwise arrive as "cannot choose
    # from an empty sequence" from a stdlib frame that mentions neither orders nor invoices.
    assert billable, (
        "no seeded user has an invoice, so no order can be given a billed state. The billing chain "
        "above seeds subscriptions for a fraction of the users and invoices for each subscription; "
        "if either fraction reached zero at this scale, lower it or raise the user count."
    )
    open_warehouses = [warehouse for warehouse in warehouses if warehouse.active]
    price_of = {sku.id: sku.price for sku in skus}
    states = tuple(OrderState)

    order_rows: list[Order] = []
    planned_lines: list[list[tuple[int, int, Decimal]]] = []
    for index in range(spec.orders):
        # The first pass over the states is EXHAUSTIVE and only then random: at the minimal scale a
        # random draw leaves a state empty often enough that whatever is built on it stops being
        # testable, and the count is the same either way.
        state = states[index] if index < len(states) else rng.choice(states)
        billed = state in (OrderState.INVOICED, OrderState.SETTLED)
        customer_id = rng.choice(billable) if billed else rng.choice(user_ids)
        warehouse = rng.choice(open_warehouses)
        held = stock_by_warehouse[warehouse.id]
        wanted = rng.sample(held, k=min(len(held), rng.randint(1, 3)))
        lines = [
            (row.sku_id, rng.randint(1, 5), price_of[row.sku_id]) for row in wanted
        ]
        if index == 0:
            # ONE order that cannot be reserved, deliberately. Phase 3's refusal path has to be
            # reachable from the seed; if the only way to reach it is hand-editing the data, the case
            # may as well not exist. It is a DRAFT because that is the state a reservation starts in.
            sku_id, _, price = lines[0]
            lines[0] = (sku_id, wanted[0].on_hand + 25, price)
        order_rows.append(
            Order(
                reference=f"ORD-{index + 1:06d}",
                state=state,
                total=sum((price * units for _, units, price in lines), Decimal("0")),
                customer_id=customer_id,
                warehouse_id=warehouse.id,
                invoice_id=(
                    rng.choice(invoices_by_user[customer_id]) if billed else None
                ),
                placed_at=_rand_dt(rng),
            )
        )
        planned_lines.append(lines)

    orders = _insert(session, order_rows)
    _insert_leaves(
        session,
        [
            OrderLine(
                order_id=order.id, sku_id=sku_id, quantity=units, unit_price=price
            )
            for order, order_lines in zip(orders, planned_lines, strict=True)
            for sku_id, units, price in order_lines
        ],
    )

    # ---- Depots -> packaging -> deliveries (the logistics domain) --------------------------------
    # It references nothing outside itself, so it could be seeded anywhere; it is seeded LAST because
    # it is newest, and the same sentence is written next to its entry in `shared/models/__init__.py`
    # so nobody has to work out whether the position means something.
    depots = _insert(
        session,
        [
            Depot(code=code, name=name, latitude=latitude, longitude=longitude)
            for code, name, latitude, longitude in _DEPOT_ROWS
        ],
    )
    packagings = _insert(
        session,
        [
            PackagingUnit(name=name, units_per_box=per_box)
            for name, per_box in _PACKAGING_ROWS
        ],
    )
    # THE DELIVERIES ARE BUILT WITH SITUATIONS IN THEM, not with noise, which is the lesson the
    # orders block above paid for: data that only USUALLY contains the case a page is about passes
    # here and fails on somebody else's machine.
    #
    # Two situations have to be reachable from the seed, and both are what the domain's screens are
    # for. The FIRST delivery is deliberately booked out of the depot FURTHEST from its destination,
    # so the sheet has a row where the assigned depot is not the nearest one and the reroute button
    # has something to do. The SECOND shares its slot hour with the first of its depot, so the load
    # page has a TIE — which is the whole difference between the `RANGE` frame it uses and the `ROWS`
    # one it does not: tied rows come in together, and with no tie in the data the two frames would
    # draw the same table.
    deliveries: list[Delivery] = []
    for index in range(spec.deliveries):
        destination = rng.choice(_DEPOT_ROWS)
        by_distance = sorted(
            depots,
            key=lambda depot: (
                (depot.latitude - destination[2]) ** 2
                + (depot.longitude - destination[3]) ** 2
            ),
        )
        # The first is booked out of the FURTHEST depot; the second out of the same depot as the
        # first, at the same hour, so the tie lands inside ONE partition. A tie split across two
        # depots is not a tie for this window at all — the frame partitions by depot — and seeding
        # one that way would look like a situation and be nothing.
        if index == 0:
            assigned = by_distance[-1].id
        elif index == 1:
            assigned = deliveries[0].depot_id
        else:
            assigned = rng.choice(depots).id
        deliveries.append(
            Delivery(
                reference=f"DLV-{index + 1:06d}",
                depot_id=assigned,
                packaging_id=rng.choice(packagings).id,
                units=rng.randint(1, 400),
                # Jittered around the depot's own position so a destination is somewhere plausible
                # and the nearest depot is usually — but NOT always — the one it was booked out of.
                latitude=round(destination[2] + rng.uniform(-0.4, 0.4), 4),
                longitude=round(destination[3] + rng.uniform(-0.4, 0.4), 4),
                slot_hour=7 if index < 2 else rng.randint(6, 21),
                promised_at=_rand_dt(rng),
            )
        )
    _insert_leaves(session, deliveries)

    session.commit()


def _make_comment(
    rng: Random,
    post_ids: Sequence[int],
    user_ids: Sequence[int],
    post_created: dict[int, SnakeUtc],
) -> Comment:
    """A comment on a random post, from a random author, dated AFTER the post."""
    post_id = rng.choice(post_ids)
    return Comment(
        body=f"Comment: {rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS)}.",
        post_id=post_id,
        author_id=rng.choice(user_ids),
        created_at=_rand_dt(rng, after=post_created[post_id]),
    )


def _make_visit(
    rng: Random, post_ids: Sequence[int], post_created: dict[int, SnakeUtc]
) -> Visit:
    """A visit to a random post, dated AFTER the post was created."""
    post_id = rng.choice(post_ids)
    return Visit(
        post_id=post_id,
        ip=_ip(rng),
        user_agent=rng.choice(_AGENTS),
        visited_at=_rand_dt(rng, after=post_created[post_id]),
    )
