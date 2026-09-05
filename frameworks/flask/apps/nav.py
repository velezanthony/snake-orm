"""The sidebar of the Flask demo: the shared catalogue turned into LINKS this router can reverse.

`shared.web.nav` says WHICH sections exist and WHICH pages hang off each one, and it deliberately
says nothing about where they live. This module is the other half, and it is per-framework because
the answer is: Flask reverses an endpoint (`blog.list_posts`), Django reverses a route name
(`post_list`), and the two are not the same string. Writing a path in the shared catalogue would be
a THIRD answer to a question two routers already answer — and the only one of the three that nothing
executes, so it would go stale the first time a route moved and nothing would go red.

So `ENDPOINTS` lives here, next to the blueprints it names, and it is an explicit dict rather than a
convention like `f"{domain}.{action}"`. A convention would look tidier and would be a lie: this demo
calls the blog's listing `blog.list_posts` and its creation form `blog.new_post_form`, because those
names were chosen to read well from the views that use them, not to be derivable from a catalogue
written afterwards. Renaming eight endpoints to satisfy a formatting rule would be the tail wagging
the dog; declaring the eight pairs is four lines longer and cannot silently mismap.

A missing entry is a `KeyError` at render time, on purpose, and it can only happen for a page the
catalogue flags `in_sidebar=True` — which is to say, for a page somebody added to the catalogue and
forgot to route here. That is exactly the moment you want to be told.
"""

from __future__ import annotations

from typing import TypedDict

from flask import has_request_context, request, url_for

from shared.web import nav


class SidebarLink(TypedDict):
    """One link of the sidebar: what it says, where it goes, and whether it is the page you are on."""

    label: str
    href: str
    current: bool


class SidebarGroup(TypedDict):
    """One section of the sidebar: its heading, its one-line blurb and the links under it."""

    label: str
    blurb: str
    links: list[SidebarLink]


# `(domain, action)` as the catalogue names it -> the Flask endpoint that serves it. Only the pages
# the catalogue marks `in_sidebar=True` need an entry: `detail`, `update` and `delete` all need a
# key, and a sidebar link has nowhere to get one.
ENDPOINTS: dict[tuple[str, str], str] = {
    # Taxonomy has four pages and no `update` or `delete`: a tag is a name that rows point at, so
    # renaming one rewrites what every post carrying it says. `detail` is absent for the ordinary
    # reason — it needs a post id and a sidebar link has nowhere to get one.
    ("taxonomy", "list"): "taxonomy.tag_list",
    ("taxonomy", "create"): "taxonomy.tag_create",
    ("taxonomy", "filter"): "taxonomy.filter_posts",
    ("blog", "list"): "blog.list_posts",
    ("blog", "create"): "blog.new_post_form",
    ("inventory", "catalogue"): "inventory.stock_catalogue",
    ("inventory", "list"): "inventory.list_stock",
    ("inventory", "create"): "inventory.new_stock_form",
    # The reorder screen. It carries no key — "what is running out" is a question about the whole
    # stockroom — so it is one of the few pages beyond `list` and `create` a blind link can reach.
    # Its sibling `warehouse` is absent for the ordinary reason: it needs a warehouse id.
    ("inventory", "alerts"): "inventory.stock_alerts",
    ("inventory", "report"): "inventory.stock_report",
    # `export` is in the sidebar and serves no page: the endpoint answers `text/csv`, so this link
    # starts a download instead of navigating. It is still a `(domain, action)` like any other,
    # which is the point of the catalogue naming actions rather than describing responses.
    ("inventory", "export"): "inventory.export_movements",
    ("orders", "list"): "orders.list_orders",
    ("orders", "create"): "orders.new_order_form",
    ("orders", "report"): "orders.order_report",
    ("orders", "export"): "orders.export_lines",
    # Billing's THREE, and there is no `create`/`update`/`delete` pair to add here because the
    # domain has none. The catalogue says so and `shared/tests/test_nav.py` asserts the absence, so
    # an entry invented here would fail the other direction of the wiring test rather than paint a
    # link: `test_no_demo_maps_a_page_the_catalogue_no_longer_offers`.
    ("billing", "list"): "billing.invoice_list",
    ("billing", "report"): "billing.billing_report",
    # The one sidebar entry that is neither `list` nor `create`, and the one that shows why the
    # catalogue writes no URLs: `operate` carries no id, so it can only mean the CHOOSER. Flask
    # reverses that to `orders.choose_order` and Django to a route name of its own; a path written
    # into `shared/web/nav.py` would have been a third answer that nothing executes.
    ("orders", "operate"): "orders.choose_order",
    # Logistics has four pages and no `create`: a delivery is booked by whatever system takes the
    # customer's order and a depot is a building somebody surveyed, so neither is a form. `detail`
    # is absent for the ordinary reason — it needs a delivery id and a sidebar link has nowhere to
    # get one.
    ("logistics", "list"): "logistics.depot_list",
    ("logistics", "dispatch"): "logistics.dispatch_board",
    ("logistics", "load"): "logistics.slot_load",
    # The three sections E.3 of the phase 8 plan gave the domains that answered only as JSON.
    # `detail` is absent from all three for the ordinary reason — it needs a key and a sidebar link
    # has nowhere to get one.
    ("content", "list"): "content.post_index",
    ("engagement", "list"): "engagement.traffic_board",
    # The export is in the sidebar and serves no page: the endpoint answers `text/csv`, so this
    # link starts a download instead of navigating — the same entry `inventory` has.
    ("engagement", "export"): "engagement.export_visits",
    ("accounts", "list"): "accounts.role_directory",
    ("lab", "list"): "lab.list_sections",
    ("lab", "aggregates"): "lab.aggregates",
    ("lab", "subqueries"): "lab.subqueries",
    ("lab", "joins"): "lab.joins",
    ("lab", "expressions"): "lab.expressions",
    ("lab", "plans"): "lab.plans",
    ("lab", "asynchronous"): "lab.asynchronous",
    ("lab", "pagination"): "lab.pagination",
    ("lab", "problems"): "lab.problems",
}


def sidebar_groups() -> list[SidebarGroup]:
    """The whole sidebar, resolved: every linkable page of every section, with the current one marked.

    `current` is an EXACT endpoint match and not "this page belongs to that domain". The attribute it
    feeds is `aria-current="page"`, and on the detail of a stock row the listing is not the page you
    are on — marking it would be telling a screen reader something untrue in order to keep a highlight
    lit.
    """
    current = request.endpoint if has_request_context() else None
    groups: list[SidebarGroup] = []
    for section in nav.sidebar_sections():
        links: list[SidebarLink] = [
            {
                "label": page.label,
                "href": url_for(ENDPOINTS[section.domain, page.action]),
                "current": ENDPOINTS[section.domain, page.action] == current,
            }
            for page in section.pages
            if page.in_sidebar
        ]
        groups.append({"label": section.label, "blurb": section.blurb, "links": links})
    return groups


def inject_sidebar() -> dict[str, list[SidebarGroup]]:
    """The context processor: every template gets `sidebar`, because the shell is in every template.

    Registered on the APP and not on a blueprint. The shell wraps the blog, the lab, the auth forms
    and the error page, and a sidebar that only some of them could draw would be a shell that renders
    differently depending on which blueprint answered — which is the sort of bug you find by clicking.
    """
    return {"sidebar": sidebar_groups()}
