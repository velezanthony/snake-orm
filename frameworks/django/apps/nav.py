"""The sidebar of the Django demo: the shared catalogue turned into Django URLs, once, for everybody.

`shared/web/nav.py` says WHICH sections exist and which pages hang off each one, and it says it
without a single path — deliberately, because Django reverses a route by its name and Flask by its
endpoint, and a path written in the shared layer would be a third answer that nothing executes. So
the pairing of `(domain, action)` with a route has to live in the framework, and this module is
where Django's half of it lives.

**The map is explicit, and that is the point.** Deriving the url name from the pair —`f"{domain}_
{action}"`— would work for `inventory_list` and then quietly stop working for the blog, whose routes
were named `post_list` and `post_create` long before this catalogue existed, and for the lab, which
is namespaced (`lab:list`). A convention that holds for one domain out of three is not a convention;
it is a coincidence with a rename waiting behind it. Written out, adding a section is one line here
and `reverse()` fails loudly at the first request if that line is wrong.

A missing entry raises `KeyError`, on purpose and without a fallback. The alternative —skipping the
page— paints a sidebar that is silently one link short on every page of the demo, which is exactly
the sort of thing nobody notices until the section it belonged to is reported missing.

**Why a context processor and not something each view passes.** The sidebar is on EVERY page,
including the ones no view of ours renders: the 404, the login form, the pages of a domain somebody
adds next month. A view that has to remember to put `sidebar` in its context is a view that will
forget, and the failure is silent — Django renders a missing variable as nothing, so the page comes
out with no navigation at all and a 200 status. Wiring it once in `TEMPLATES["OPTIONS"]` makes the
question "does this page have a sidebar?" unanswerable in the wrong direction.
"""

from __future__ import annotations

from typing import TypedDict

from django.http import HttpRequest
from django.urls import reverse

from shared.web.nav import sidebar_sections


class SidebarLink(TypedDict):
    """One link of the sidebar: what it says, where it goes, and whether it is the page you are on."""

    label: str
    href: str
    current: bool


class SidebarGroup(TypedDict):
    """One section of the sidebar: its heading, its one-line description and its links."""

    label: str
    blurb: str
    links: list[SidebarLink]


# `(domain, action)` -> the Django url name that serves it. Only the pages the catalogue marks
# `in_sidebar` need an entry: `detail`, `update` and `delete` all need a key, and a sidebar link has
# nowhere to get one.
_URL_NAMES: dict[tuple[str, str], str] = {
    ("blog", "list"): "post_list",
    ("blog", "create"): "post_create",
    ("inventory", "catalogue"): "inventory_catalogue",
    ("inventory", "list"): "inventory_list",
    ("inventory", "create"): "inventory_create",
    # The reorder screen. It carries no key — "what is running out" is a question about the whole
    # stockroom — so it is one of the few pages beyond `list` and `create` a blind link can reach.
    # Its sibling `warehouse` is absent for the ordinary reason: it needs a warehouse id.
    ("inventory", "alerts"): "inventory_alerts",
    ("inventory", "report"): "inventory_report",
    # The export is a link like any other and what it answers is a CSV, not a page. That is why it
    # needs an entry here and no template anywhere: the sidebar's job is to reach the route, and
    # what the route hands back is the route's business.
    ("inventory", "export"): "inventory_export",
    ("orders", "list"): "orders_list",
    ("orders", "create"): "orders_create",
    # The bare `operate/` and not the one with an id: the catalogue marks this page `in_sidebar`
    # precisely because it is the one operation entry a link can reach without a key, and the
    # chooser behind it is what turns "no id" into a page rather than a 404.
    ("orders", "operate"): "orders_operate_index",
    ("orders", "report"): "orders_report",
    ("orders", "export"): "orders_export",
    # Billing has three pages and no `create`, `update` or `delete`, which is the domain's whole
    # statement rather than an entry somebody forgot: an invoice is raised by an operation and
    # settled by another, never typed into a form. `detail` is absent for the ordinary reason —
    # it needs an id and a sidebar link has nowhere to get one.
    ("billing", "list"): "billing_list",
    ("billing", "report"): "billing_report",
    # Taxonomy has four pages and no `update` or `delete`: a tag is a name that rows point at, so
    # renaming one rewrites what every post carrying it says. `detail` is absent for the ordinary
    # reason — it needs a post id and a sidebar link has nowhere to get one.
    ("taxonomy", "list"): "taxonomy_list",
    ("taxonomy", "create"): "taxonomy_create",
    ("taxonomy", "filter"): "taxonomy_filter",
    # Logistics has four pages and no `create`: a delivery is booked by whatever system takes the
    # customer's order and a depot is a building somebody surveyed, so neither is a form. `detail`
    # is absent for the ordinary reason — it needs a delivery id and a sidebar link has nowhere to
    # get one.
    ("logistics", "list"): "logistics_list",
    ("logistics", "dispatch"): "logistics_dispatch",
    ("logistics", "load"): "logistics_load",
    # The three sections E.3 of the phase 8 plan gave the domains that answered only as JSON.
    # `detail` is absent from all three for the ordinary reason — it needs a key and a sidebar link
    # has nowhere to get one.
    ("content", "list"): "content_list",
    ("engagement", "list"): "engagement_list",
    # The export is a link like any other and what it answers is a CSV, not a page — the same entry
    # `inventory` has, for the same reason: the sidebar's job is to reach the route.
    ("engagement", "export"): "engagement_export",
    ("accounts", "list"): "accounts_list",
    ("lab", "list"): "lab:list",
    ("lab", "aggregates"): "lab:aggregates",
    ("lab", "subqueries"): "lab:subqueries",
    ("lab", "joins"): "lab:joins",
    ("lab", "expressions"): "lab:expressions",
    ("lab", "plans"): "lab:plans",
    ("lab", "asynchronous"): "lab:asynchronous",
    ("lab", "pagination"): "lab:pagination",
    ("lab", "problems"): "lab:problems",
}


def _current_url_name(request: HttpRequest) -> str | None:
    """The url name of the route being served, namespaced the same way `_URL_NAMES` writes them.

    `resolver_match` is `None` while the URL has not been resolved yet — a template rendered from a
    middleware or a handler that runs before resolution — and the honest answer there is "no page is
    current", not a crash on a page that has nothing to do with navigation.
    """
    match = request.resolver_match
    if match is None:
        return None
    return f"{match.app_name}:{match.url_name}" if match.app_name else match.url_name


def sidebar(request: HttpRequest) -> dict[str, list[SidebarGroup]]:
    """The context processor: hands every template the sections, their links and the current one.

    `reverse()` is called per request rather than resolved once at import, because at import time the
    URLconf is not loaded yet — Django builds it lazily on the first request. Ten reversals against
    an in-memory table is not a cost worth caching around; a module that cannot be imported is.
    """
    current = _current_url_name(request)
    groups: list[SidebarGroup] = []
    for section in sidebar_sections():
        links: list[SidebarLink] = []
        for page in section.pages:
            if not page.in_sidebar:
                continue
            url_name = _URL_NAMES[(section.domain, page.action)]
            links.append(
                {
                    "label": page.label,
                    "href": reverse(url_name),
                    "current": url_name == current,
                }
            )
        groups.append({"label": section.label, "blurb": section.blurb, "links": links})
    return {"sidebar": groups}
