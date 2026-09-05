"""The sidebar catalogue: that it stays a catalogue and not a second routing table.

`shared.web.nav` is the one place that says WHICH sections a demo has and WHICH pages hang off each
of them. What it must never say is where they live, and that is not style: Django reverses a route
by name and Flask by endpoint, so any path written here would be a third answer to a question two
routers already answer — and the one nobody runs.

So what is pinned below is the shape of the catalogue rather than its contents: unique domains, a
landing page in every section, and no empty label. Those are the three ways an entry can be added
tomorrow and be silently useless — a duplicate domain that shadows another, a section you cannot
enter, a link with nothing to click on.
"""

from __future__ import annotations

import pytest

from shared.web import nav


def test_no_two_sections_claim_the_same_domain() -> None:
    """The domain is the KEY the frameworks look a section up by, so a duplicate hides one."""
    domains = [section.domain for section in nav.SECTIONS]

    assert len(domains) == len(set(domains)), f"repeated domains: {domains}"


def test_every_section_has_a_landing_page() -> None:
    """`list` is the action you arrive at a section through: without one it is unreachable.

    The taxonomy of the plan fixes `list` as the entry point of every domain, and that includes the
    lab: its index IS a listing (one COUNT per table). Calling it something else there would make
    this invariant a special case, and a special case is what a sidebar link falls through.
    """
    for section in nav.SECTIONS:
        actions = {page.action for page in section.pages}
        assert "list" in actions, f"{section.domain} has no landing page: {actions}"


def test_every_section_shows_at_least_one_page_in_the_sidebar() -> None:
    """A section whose pages are all `in_sidebar=False` is a heading pointing at nothing."""
    for section in nav.SECTIONS:
        assert any(page.in_sidebar for page in section.pages), section.domain


def test_labels_and_blurbs_are_written() -> None:
    """An empty label is a link with no text, and an empty blurb a section nobody can place."""
    for section in nav.SECTIONS:
        assert section.label.strip(), section.domain
        assert section.blurb.strip(), section.domain
        for page in section.pages:
            assert page.label.strip(), f"{section.domain}.{page.action}"


def test_no_section_repeats_an_action() -> None:
    """The action is what a framework maps to a route, so two pages sharing one is ambiguous."""
    for section in nav.SECTIONS:
        actions = [page.action for page in section.pages]
        assert len(actions) == len(set(actions)), f"{section.domain}: {actions}"


_CRUD = {"list", "detail", "create", "update", "delete"}


def test_blog_is_the_plain_crud_domain_and_stays_five_pages() -> None:
    """`blog` is the only section that is still exactly the five, and that is what it is FOR.

    It covers CRUD, N+1 and N—N and nothing else, so it is the baseline every other section is read
    against. The day it grows a sixth page, the catalogue has stopped having a plain case in it.
    """
    assert {page.action for page in nav.section("blog").pages} == _CRUD


def test_inventory_carries_the_five_a_report_an_export_and_three_of_its_own() -> None:
    """The pilot has grown four times now, and the five underneath have survived every one.

    That is the whole invariant: a domain that grows a page must not quietly rename one of the ones
    it already had, because "open a domain and the same thing is in the same place" is the only
    reason the catalogue is worth having. `report` and `export` are the two page types the plan adds,
    and they are spelled the same here as in `orders` — a section that called one of them `csv` would
    still render and would break the promise.

    The three that belong to this domain alone each arrived with a question that had nowhere else to
    be asked, which is the bar, and never with symmetry:

    * `catalogue` — a stock pair POINTS AT a warehouse and a SKU, and until it existed neither could
      be brought into being from a page: the demo could only stock what the seeder had made. The
      warehouse-wide `reserve` lands there too, because it holds units across a whole warehouse in
      one statement while every other page here is about one pair.
    * `alerts` — WHAT DO I NEED TO REORDER. The read-only `LowStock` view answered that to
      `/api/inventory/low-stock` and to nobody looking at a screen, so the section had the summary of
      the inventory and not the decision anybody takes from it. It is a page of its own rather than a
      sixth figure on the report because the report's statement budget is pinned for another reason.
    * `warehouse` — WHAT IS IN THIS SHED AND WHAT HAS EACH LINE BEEN DOING. The listing answers the
      first half and the pair detail answers the second one SKU at a time; `stock_with_movements`
      answers both in one go, and it is the to-many over a composite key — the hardest shape in the
      demos, and the last one without a screen.
    """
    actions = {page.action for page in nav.section("inventory").pages}

    assert actions == _CRUD | {
        "report",
        "export",
        "catalogue",
        "alerts",
        "warehouse",
    }


def test_orders_carries_the_same_seven_plus_two_of_its_own() -> None:
    """`orders` is CRUD, a report and an export — the seven `inventory` also has — plus two.

    The SEVEN are what this test is really about. They are the shared spine, and they have to keep
    matching between the two biggest sections, because a reader who has learnt where `export` lives
    in one of them has learnt it for both.

    The two that are this domain's own are the exception the spine tolerates, and each carries its
    own argument:

    * `operate` — an operation here is something a person goes looking for, so it is the one page in
      the catalogue that is neither a landing nor a creation and is still linked blind.
    * `customer` — WHAT HAS THIS CUSTOMER ORDERED, AND WHAT WAS ON EACH ORDER. The report names every
      customer and what they have spent; the sheet behind the name answered only as JSON, and
      `paginate_orders` has been accepting a `customer_id` no page ever passed. It is not in the
      sidebar, because it needs an id.
    """
    actions = {page.action for page in nav.section("orders").pages}

    assert actions == _CRUD | {"report", "export", "operate", "customer"}


def test_billing_is_read_only_and_says_so_by_what_it_does_not_offer() -> None:
    """THREE pages, and the two missing ones are the statement: no `create`, no `update`, no `delete`.

    The plan gives billing list, detail and report because an invoice is raised by an operation and
    settled by another — never typed into a form. Asserting the ABSENCE is what keeps somebody from
    "completing" the section later out of a sense of symmetry, which would turn a deliberate design
    into an accident nobody could tell from an omission.
    """
    actions = {page.action for page in nav.section("billing").pages}

    assert actions == {"list", "detail", "report"}
    assert not actions & {"create", "update", "delete"}


def test_the_report_and_export_pages_are_offered_from_the_sidebar() -> None:
    """Both need no key, so both can be linked blind — unlike detail, update and delete.

    It is the same test `operate` gets, and for the same reason: a page that is neither a landing nor
    a creation and is STILL in the sidebar is an exception, and an exception is worth pinning rather
    than leaving to be noticed when somebody wonders why it is there.
    """
    for domain in ("inventory", "orders", "billing"):
        for page in nav.section(domain).pages:
            if page.action in {"report", "export"}:
                assert page.in_sidebar, f"{domain}.{page.action}"


def test_the_operation_page_is_offered_from_the_sidebar() -> None:
    """Unlike detail, update and delete, an operation is something a person goes looking for.

    It is the one page in the catalogue that is neither a landing nor a creation and is still linked
    blind, so the exception is pinned rather than left to be noticed: the framework routes the
    id-less path to a chooser, and the id-bearing one to the operation itself.
    """
    operate = [page for page in nav.section("orders").pages if page.action == "operate"]

    assert [page.in_sidebar for page in operate] == [True]


def test_the_reorder_screen_is_linked_blind_and_the_two_sheets_are_not() -> None:
    """Three pages arrived together and only one of them can be a sidebar link. The rule is the KEY.

    `alerts` asks a question about the whole stockroom, so a link with nothing in it reaches the
    whole answer — the same property `report` and `export` have, and the reason all three can sit in
    a table of contents. `warehouse` and `customer` are sheets ABOUT one row, so a blind link would
    have to invent an id: `/inventory/warehouse/` with nothing after it is a 404 painted on purpose,
    on every page of the demo, which is the failure `in_sidebar` exists to make impossible.

    It is pinned rather than left to be noticed because the three read alike in the catalogue and are
    not alike at all, and the one that would break is the one somebody "completes" for symmetry.
    """
    flags = {
        (section.domain, page.action): page.in_sidebar
        for section in nav.SECTIONS
        for page in section.pages
    }

    assert flags[("inventory", "alerts")] is True
    assert flags[("inventory", "warehouse")] is False
    assert flags[("orders", "customer")] is False


def test_the_detail_family_is_reached_from_a_page_and_not_from_the_sidebar() -> None:
    """`detail`, `update` and `delete` all need an id, which a sidebar link does not have.

    This is the whole reason `in_sidebar` exists as a flag instead of being inferred: a catalogue
    that listed them would produce links to `/inventory/detail/` with no key in it.
    """
    reached_from_a_page = {"detail", "update", "delete"}
    for section in nav.SECTIONS:
        for page in section.pages:
            if page.action in reached_from_a_page:
                assert not page.in_sidebar, f"{section.domain}.{page.action}"


def test_sidebar_sections_keeps_the_order_of_the_catalogue() -> None:
    """The sidebar is read top to bottom, so its order is the catalogue's and not a set's."""
    assert [s.domain for s in nav.sidebar_sections()] == [
        s.domain for s in nav.SECTIONS
    ]


def test_asking_for_a_domain_that_does_not_exist_says_so() -> None:
    """A typo in a template name has to fail loudly, not paint an empty sidebar section.

    `auth` is the probe because it is a REAL domain with no SIDEBAR SECTION, and the distinction is
    the whole reason it is the one left: it HAS pages — the login, the sign-up and the access ledger
    of one person — and none of them belongs in a table of contents of the demo's data. They are
    reached from the topbar and from a row of `accounts`, which is where somebody looking for them
    would go. A made-up word would prove the same thing about `KeyError` and nothing about the case
    that will actually happen — a template written ahead of its section.

    IT HAS NOW MOVED THREE TIMES, and every move is the good outcome. It was `billing` until billing
    got its three pages, `taxonomy` until taxonomy got its four, and `content` until E.3 gave
    `accounts`, `content` and `engagement` a section each. Each time the test was naming a real gap
    and the gap closed. What is left is not a gap: `auth` is a domain that will not have a section,
    so this probe has stopped moving rather than run out — and the day somebody gives it one, this
    test gets deleted rather than repaired.
    """
    with pytest.raises(KeyError):
        nav.section("auth")


def test_the_catalogue_is_frozen() -> None:
    """Nobody re-labels a section from a request: it is a module-level constant shared by threads."""
    section = nav.section("inventory")

    with pytest.raises(AttributeError):
        section.label = "Almacén"  # type: ignore[misc]
