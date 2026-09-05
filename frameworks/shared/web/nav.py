"""The catalogue of the sidebar: WHICH sections a demo has and WHICH pages hang off each one.

**There is no URL here, and that is the whole design.** Django reverses a route by its name and
Flask by its endpoint; FastAPI does neither because it has no templates. A path written down here
would be a THIRD answer to a question two routers already answer, and the only one nothing
executes: it would go stale the first time a route moved, and nothing would go red. So a section
says `inventory` and a page says `detail`, and each framework turns that pair into a link with its
own tag. The catalogue names things; the router locates them.

`in_sidebar` is a field rather than something inferred from the action, because a page missing from
the sidebar is not an unimportant one: `detail`, `update` and `delete` all need a key, and a sidebar
link has nowhere to get one. Listing them would emit links to `/inventory/detail/` with no pair in
them — a 404 rendered on purpose, on every page. That is why every `detail` below is `False`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NavPage:
    """One page of a section: what it DOES, what it is called, and whether it can be linked blind.

    `action` is the same vocabulary as the page taxonomy — `list`, `detail`, `create`, `update`,
    `delete`, `report`, `export` — so opening any domain tells you where the same thing lives in the
    others. A framework maps it to a route; nothing here knows how.
    """

    action: str
    label: str
    in_sidebar: bool


@dataclass(frozen=True, slots=True)
class NavSection:
    """One domain in the sidebar, with the pages it offers and one line saying what it is for.

    `blurb` is not decoration: a sidebar of eight nouns tells a reader nothing about which of them
    exercises the thing they came to see. One line per section turns navigation into a contents page.
    """

    domain: str
    label: str
    blurb: str
    pages: tuple[NavPage, ...]


# Written once rather than per domain: "the same five everywhere" IS the taxonomy, and hand-copied
# tuples are how two domains drift apart.
_CRUD_PAGES: tuple[NavPage, ...] = (
    NavPage(action="list", label="Browse", in_sidebar=True),
    NavPage(action="detail", label="Detail", in_sidebar=False),
    NavPage(action="create", label="New entry", in_sidebar=True),
    NavPage(action="update", label="Edit", in_sidebar=False),
    NavPage(action="delete", label="Delete", in_sidebar=False),
)


# Deliberately NOT renamed per domain, unlike the CRUD two below: "Report" and "Export CSV" already
# say what they do anywhere, and nine different names would hide the one thing the taxonomy buys.
_REPORTING_PAGES: tuple[NavPage, ...] = (
    NavPage(action="report", label="Report", in_sidebar=True),
    NavPage(action="export", label="Export CSV", in_sidebar=True),
)


def _crud_pages(*, list_label: str, create_label: str) -> tuple[NavPage, ...]:
    """The five CRUD pages with the two SIDEBAR labels renamed for the domain.

    Only those two get a name of their own: they are the ones a reader meets cold, in a list of every
    section at once, where "Browse" says nothing. The other three are read from inside the domain.
    """
    renamed = {"list": list_label, "create": create_label}
    return tuple(
        NavPage(
            action=page.action,
            label=renamed.get(page.action, page.label),
            in_sidebar=page.in_sidebar,
        )
        for page in _CRUD_PAGES
    )


SECTIONS: tuple[NavSection, ...] = (
    NavSection(
        domain="blog",
        label="Blog",
        blurb=(
            "The everyday shape: to-one and to-many relations loaded without N+1, and the "
            "N-N of tags resolved with a subquery over the bridge table."
        ),
        pages=_crud_pages(list_label="Posts", create_label="New post"),
    ),
    NavSection(
        domain="content",
        label="Content",
        blurb=(
            "The only section that asks for the same table twice on purpose: the timeline "
            "of a post DEFERS the body — every column except the one that is the size of an "
            "article — and the panel under it brings the bodies. Two questions, and the "
            "difference between them is a page rather than a paragraph."
        ),
        pages=(
            # No `create`: a revision and an attachment do not exist apart from the post that
            # carries them, so both are written from the post's own sheet.
            NavPage(action="list", label="Post histories", in_sidebar=True),
            NavPage(action="detail", label="Detail", in_sidebar=False),
        ),
    ),
    NavSection(
        domain="engagement",
        label="Engagement",
        blurb=(
            "Where a TRIGGER becomes visible: the visit counter on a post is moved by the "
            "engine, underneath the object the handler is holding, so recording a visit "
            "answers with a row REFRESHED from the database rather than with a number Python "
            "added up. It is the one figure on the demo no page could work out for itself."
        ),
        pages=(
            # No `create` or `delete`: a comment, a reaction and a visit are all written from the
            # post's sheet, and nothing on either surface withdraws one.
            NavPage(action="list", label="Traffic board", in_sidebar=True),
            NavPage(action="detail", label="Detail", in_sidebar=False),
            NavPage(action="export", label="Export CSV", in_sidebar=True),
        ),
    ),
    NavSection(
        domain="inventory",
        label="Inventory",
        blurb=(
            "The hard shape: stock is identified by the PAIR (warehouse, sku), so the key "
            "travels in the URL in two halves and the movements hang off a foreign key two "
            "columns wide."
        ),
        pages=(
            *_crud_pages(list_label="Stock", create_label="New stock row"),
            # A stock pair POINTS AT a warehouse and a SKU, and neither could be created from a
            # page: the demo could only ever stock what the seeder had made. One page and not two,
            # because what the inventory is made OF is a single question — and the warehouse-wide
            # `reserve` lands here, since it reserves across a whole warehouse in one statement.
            NavPage(action="catalogue", label="Warehouses & SKUs", in_sidebar=True),
            # WHAT DO I NEED TO REORDER. The `LowStock` view was reachable from the API and from
            # nowhere a person looks. Its own page and NOT a slice of the report: `StockReport` is a
            # frozen shape whose statement budget is pinned, and a seventh figure would move it.
            NavPage(action="alerts", label="Running out", in_sidebar=True),
            # ONE WAREHOUSE AND EVERY LINE IN IT: `stock_with_movements` is the to-many over a
            # COMPOSITE key, the hardest shape in the demos. Reached from the catalogue's rows.
            NavPage(action="warehouse", label="Warehouse sheet", in_sidebar=False),
            *_REPORTING_PAGES,
        ),
    ),
    NavSection(
        domain="orders",
        label="Orders",
        blurb=(
            "The only section where two customers want the same unit: a transaction that "
            "declares its isolation level before it reads, holds the stock under a row lock "
            "while it decides, and rewinds a declined payment to a savepoint without losing "
            "the invoice it had already issued."
        ),
        pages=(
            *_crud_pages(list_label="Orders", create_label="New order"),
            # The one sidebar page that is neither `list` nor `create`: an operation is something
            # you go looking for. It carries no id, so the framework routes the bare path to a
            # chooser and the path with an id to `order_operation`.
            NavPage(
                action="operate", label="Reserve / settle / cancel", in_sidebar=True
            ),
            # WHAT HAS THIS CUSTOMER ORDERED. The report names every customer and what they spent;
            # the sheet behind the name answered only as JSON until this page existed.
            NavPage(action="customer", label="Customer sheet", in_sidebar=False),
            *_REPORTING_PAGES,
        ),
    ),
    NavSection(
        domain="billing",
        label="Billing",
        blurb=(
            "The money, read-only on purpose: an invoice is raised by an operation and "
            "settled by another, never typed into a form. Three pages instead of five, and "
            "the one listing in the demos that flattens THREE to-one hops per row without "
            "paying a query for any of them."
        ),
        pages=(
            # No `create`, `update` or `delete`, and the absence is the domain's whole statement: a
            # page that let somebody retype an amount would demo the one thing accounting must not
            # offer.
            NavPage(action="list", label="Invoices", in_sidebar=True),
            NavPage(action="detail", label="Detail", in_sidebar=False),
            NavPage(action="report", label="Report", in_sidebar=True),
        ),
    ),
    NavSection(
        domain="taxonomy",
        label="Tags",
        blurb=(
            "The only N—N in the catalogue with an explicit bridge, and the section where a "
            "set operation earns its place: requiring two tags is a condition on two "
            "DIFFERENT bridge rows, so no WHERE expresses it and the engine is asked to "
            "INTERSECT. Ticking a box twice is also why tagging had to become idempotent."
        ),
        pages=(
            # No `update` or `delete`: a tag is a NAME that rows point at, so renaming one rewrites
            # the meaning of every post carrying it and deleting one silently unfiles them.
            NavPage(action="list", label="Tags", in_sidebar=True),
            NavPage(action="create", label="New tag", in_sidebar=True),
            NavPage(action="detail", label="Detail", in_sidebar=False),
            NavPage(action="filter", label="Filter posts", in_sidebar=True),
            # WHERE A TAG SITS. A taxonomy is a hierarchy, and this draws one: the breadcrumb up to
            # the root and the section under it, each ONE statement whatever the depth.
            NavPage(action="tree", label="Tag tree", in_sidebar=False),
        ),
    ),
    NavSection(
        domain="logistics",
        label="Logistics",
        blurb=(
            "The only section that measures anything: the depot a delivery should leave "
            "from is a distance — a square root over a sum of squares the engine computes so "
            "that only the three nearest travel — and the load of an hour is a window whose "
            "span is a VALUE rather than a count of rows, so two vans booked at nine read one "
            "figure instead of three."
        ),
        pages=(
            # No `create`, `update` or `delete`: a delivery is booked by whatever takes the order, a
            # depot is a surveyed building and a box size is a fact about cardboard. The one thing a
            # dispatcher changes — which depot a delivery leaves from — is a button on the sheet.
            NavPage(action="list", label="Depots", in_sidebar=True),
            NavPage(action="detail", label="Delivery sheet", in_sidebar=False),
            # Both are `report`-shaped without being called `report`: naming either of them that
            # would leave the OTHER one nameless, and `report` means a summary of a domain.
            NavPage(action="dispatch", label="Dispatch board", in_sidebar=True),
            NavPage(action="load", label="Slot load", in_sidebar=True),
        ),
    ),
    NavSection(
        domain="accounts",
        label="Accounts",
        blurb=(
            "The administrative N—N: roles and who holds them, over a bridge table with no "
            "payload at all. The grants screen is the tag screen with different nouns, which "
            "is the point of having a page taxonomy — the same operation looks the same "
            "wherever a reader meets it."
        ),
        pages=(
            # No `update` or `delete` of a role, the same argument `taxonomy` makes about a tag. The
            # creation form lives on the listing: a role is one field.
            NavPage(action="list", label="Roles & people", in_sidebar=True),
            NavPage(action="detail", label="Detail", in_sidebar=False),
        ),
    ),
    NavSection(
        domain="lab",
        label="Lab",
        blurb=(
            "The ORM with the lid off: aggregates, subqueries, joins, scalar functions and "
            "pagination, plus a page that provokes an N+1 on purpose so the panel flags it."
        ),
        pages=(
            # `list` and not `index`: it IS the landing listing, and another name would make this
            # the one section the sidebar has to special-case.
            NavPage(action="list", label="Seeded volume", in_sidebar=True),
            NavPage(action="aggregates", label="Aggregates", in_sidebar=True),
            NavPage(action="subqueries", label="Subqueries", in_sidebar=True),
            NavPage(action="joins", label="Joins / include", in_sidebar=True),
            NavPage(action="expressions", label="Scalar functions", in_sidebar=True),
            NavPage(action="plans", label="Plan and report", in_sidebar=True),
            NavPage(action="asynchronous", label="Async seam", in_sidebar=True),
            NavPage(action="pagination", label="Pagination", in_sidebar=True),
            NavPage(action="problems", label="Problems on purpose", in_sidebar=True),
        ),
    ),
)


_BY_DOMAIN: dict[str, NavSection] = {section.domain: section for section in SECTIONS}


def section(domain: str) -> NavSection:
    """The section of a domain. `KeyError` if there is none, on purpose.

    A template asking for a domain that does not exist has a typo in it, and the useful outcome is a
    loud one. Returning `None` would paint an empty heading and leave the typo in the file.
    """
    return _BY_DOMAIN[domain]


def sidebar_sections() -> tuple[NavSection, ...]:
    """The sections the sidebar shows, in the order it shows them.

    Today that is all of them, and it is still a function rather than the constant: the sidebar's
    contents will depend on who is looking (the lab is a developer's page) long before the catalogue
    itself does, and callers that already go through here will not have to change.
    """
    return SECTIONS
