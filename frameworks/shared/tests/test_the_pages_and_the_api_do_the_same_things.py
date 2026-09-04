"""What the PAGES of a domain can DO and what its API can do, held against each other.

`test_the_demos_serve_the_same_routes.py` compares like with like: Django's pages against Flask's,
and the three JSON surfaces against each other. This file asks the question the "BFF mirror" claim
actually rests on: **can you do through `/api/X` what you can do through `/X`?**

WHY IT CANNOT BE ASKED OF URLS, which is structural rather than a detail. A page has to SHOW a form
before it can accept one, so creating is two routes on one side and one on the other. A browser
`<form>` emits only GET and POST, so deleting is a POST to a path that says "delete" and never
`DELETE /api/orders/<id>`. And an API splits a resource into sub-resources that one edit screen keeps
together. Three real differences in SHAPE, none in capability — so the comparison is made on the
OPERATION, which is the vocabulary both surfaces already speak. `operations.py` does the reading.

READS ARE NOT COMPARED HERE, AND THIS PARAGRAPH HAS BEEN REWRITTEN BECAUSE THE FIRST REASON IT GAVE
WAS WRONG. It used to say the two surfaces diverge on reads SYMMETRICALLY — "inventory six against
six, billing four against four" — and that the difference was one of SHAPE: the pages page and
report (`paginate_stock`, `stock_report`), the API serves resources (`stock_of_warehouse`,
`warehouse_stats`). Three of those four examples do not survive being checked. `paginate_stock` and
`stock_report` now answer on BOTH surfaces, and they got there by being GIVEN the half they were
missing rather than by being explained; `stock_of_warehouse` had never diverged in the first place,
since `/orders/operate` reaches it. When `test_the_page_and_the_api_reach_one_usecase.py` held all
23 remaining read divergences up one at a time, THIRTEEN of them were a capability one surface did
not have — an invoice a client could pay over JSON and not read over JSON — and only ten had an
argument behind them.

WHAT IS STILL TRUE IS THE DIVISION OF LABOUR, and that is the reason this file keeps to writes.
Reads ARE compared, next door, on the OPERATION — which is where the shape objection genuinely does
dissolve, because joining on the use case instead of on the URL normalises the shapes away before
the comparison starts. Repeating it here would be two nets answering one question, and the first
time somebody edited one of them they would answer it differently.

WRITES ARE ANOTHER MATTER ENTIRELY, and they are what this file asserts. An operation that CHANGES
data and is reachable from only one surface is the demo teaching that the ORM can do something in
HTML and not in JSON — which is false, and which nothing was checking. Measured when this was
written: twelve of them, all but three in one direction (the API can, the pages cannot).

A write is DERIVED, not listed: a use case whose body reaches a `commit`. The list would be the part
that goes stale, because a read that grows a write is exactly the change nobody remembers to record
and also the one that makes the surfaces diverge in the way that matters.
"""

from __future__ import annotations

import pytest

from shared.tests.operations import (
    api_operations,
    domains,
    ssr_operations,
    writing_operations,
)

# Domains that answer ONLY as JSON, with the reason. Django's root urlconf calls them "the orphan
# domains exposed as a flat JSON API" — they hang off the blog's data without owning a screen, and
# giving each one pages would be four more sections in a sidebar that already carries ten.
_API_ONLY: dict[str, str] = {
    # EMPTY, and it took four sections to empty it. Keeping the heading over nothing is the point:
    # this is where a domain goes when it answers only as JSON, and the block being empty is the
    # claim that no domain does.
}

# `taxonomy` was the first out, with the reason "applied from the blog's editor rather than from a
# section". It came out because the exemption had stopped being true: the domain has four pages of
# its own now, and the reason it grew them is the one this file is about — a screen of tick boxes is
# what turned tagging into an operation somebody can submit twice, and the bridge held two rows for
# one fact until it did.
#
# THE OTHER THREE WENT TOGETHER, in a single pass, and their reasons had
# aged the same way. "An administrative surface with no page in the demo" describes a gap rather than
# a decision; "reached from the blog's own screens" was true of where revisions BELONG and false
# about there being any screen to reach them from — the editor never grew one. So for as long as
# those lines stood, the demos taught in JSON that a post has a history and in HTML that it has none.
# `accounts`, `content` and `engagement` each have a section now, over the same use cases.

# Domains this file cannot read, with why. Not a hole to be tolerated quietly: an unreadable domain
# is one whose divergence nobody is measuring, so it says so out loud.
_UNREADABLE: dict[str, str] = {
    "lab": (
        "the lab reaches its operations through a MODULE (`usecases.lab_usecases.x`) instead of "
        "calling them on `usecases` directly, so the reader cannot see them. It is also the one "
        "'domain' that is not one: a developer's page over `shared/selectors/catalog.py`, which "
        "`fastapi/apps/deps.py` already documents as the deliberate exception it makes for it"
    ),
}

# Every WRITE reachable from one surface and not the other, as `domain.operation`, with why. Two
# kinds of entry live here and telling them apart is the whole point of writing the reason down:
# a DECISION, and a gap that is simply not audited. The second kind says so in those words — a
# reason that is really a guess is worse than none, because it closes the question.
_WRITE_ON_ONE_SURFACE: dict[str, str] = {
    # --- Decisions ------------------------------------------------------------------------------
    "auth.issue_token": (
        "DECISION. A token is for a client that has no cookie jar; a browser gets a session. The "
        "two halves of authentication genuinely belong to different surfaces, which is why the "
        "login pages set `user_id` in a signed cookie and never mint a token"
    ),
    "auth.revoke_token": "DECISION. The other half of `issue_token`, above",
    "blog.register": (
        "DECISION. The blog's JSON API carries its own `register`/`login` so a client can use it "
        "without the SSR demo; the pages reach the same use case through `apps/auth/`. It is a "
        "second DOOR to one operation, not a second operation"
    ),
    # BILLING'S FOUR, and they were on the NOT AUDITED list until two nets were read side by side.
    # `test_nav.py::test_billing_is_read_only_and_says_so_by_what_it_does_not_offer` asserts the
    # ABSENCE of a create, an update and a delete here, and says why in its own docstring — so that
    # nobody "completes" the section later out of a sense of symmetry, which would turn a deliberate
    # design into an accident nobody could tell from an omission.
    #
    # That is exactly what "NOT AUDITED" claimed had happened. Two nets asserting opposite things
    # about one domain, and the one with the argument written down wins: this was decided, and the
    # entries below now say so instead of inviting somebody to close them.
    #
    # The line the design draws is about MONEY BEING TYPED. An invoice is raised by an operation for
    # what the order came to, and settled by another; a form where a figure is retyped is the one
    # thing accounting must not offer. `subscribe` and `cancel_subscription` type no figure — and
    # they are still on this side of the line, because the section is read-only as a whole and half
    # a section that writes is worse than either.
    "billing.issue_invoice": (
        "DECISION. `settle` raises the invoice for what the order came to. A page would take the "
        "figure from a form, which is the one thing this domain keeps out of one"
    ),
    "billing.pay_invoice": (
        "DECISION. The other half of the same rule: an invoice is settled by an OPERATION, and "
        "`settle` is the one that takes the money"
    ),
    "billing.subscribe": (
        "DECISION. Billing's pages are read-only as a section, which its nav entry states and "
        "`test_nav.py` asserts by the actions it refuses to have"
    ),
    "billing.cancel_subscription": "DECISION. The other half of `subscribe`, above",
    # --- Not audited ----------------------------------------------------------------------------
    # EMPTY, and keeping the heading over nothing is the point: this is where a write goes when it
    # reaches one surface and nobody decided it should. The block being empty is a claim, and it is
    # the claim this file is for — every divergent write above is a decision with its reason next to
    # it, not a gap somebody stopped noticing.
    #
    # There were twelve. Each one came off by something being BUILT or by a reason being found, and
    # the two are worth telling apart:
    #
    #   * Two went the OTHER way — a page could correct and delete a stock pair and the API could
    #     not — and closed with a PATCH and a DELETE on the path the count already used.
    #   * `orders.attach_invoice` needed a selector before it needed a form: a page cannot offer a
    #     choice it has no cheap way to list, and listing a customer's invoices per subscription is
    #     the N+1 that the very page it sits on argues against.
    #   * `receive` and `ship` landed on the pair's DETAIL page, which is where a movement belongs
    #     and which cost the catalogue nothing.
    #   * Billing's four were not gaps at all. `test_nav.py` had asserted, with its reasons, that
    #     the section is read-only; this list said nobody had decided. Two nets contradicting each
    #     other about one domain, and the one with the argument written down won.
    #   * The last three — `create_sku`, `create_warehouse` and `reserve` — needed a page the
    #     catalogue did not have, so the catalogue grew one: `inventory.catalogue`, the second
    #     action in the whole demo to belong to a single domain. That was a decision about the
    #     PAGE TAXONOMY rather than about inventory, which is why it is written into `nav.py` and
    #     asserted in `test_nav.py` rather than settled quietly here.
}


def _divergent_writes(domain: str) -> set[str]:
    """The domain's writes reachable from exactly one of its two surfaces."""
    pages, api = ssr_operations(domain), api_operations(domain)
    return ((pages - api) | (api - pages)) & writing_operations(domain)


def test_every_domain_is_readable_or_says_why_not() -> None:
    """No domain drops out of this comparison in silence, which is the vacuous run per domain.

    A domain whose operations cannot be read contributes an empty set to both sides, matches
    perfectly and is never mentioned again.
    """
    unreadable = sorted(
        domain
        for domain in domains()
        if not ssr_operations(domain)
        and not api_operations(domain)
        and domain not in _UNREADABLE
    )

    assert unreadable == [], (
        f"nothing readable in {unreadable}: either the demo stopped calling its use cases the way "
        f"`operations.py` reads them, or the domain is genuinely empty. Add it to `_UNREADABLE` "
        f"with the reason, or fix the reader — an unmeasured domain is not a domain that agrees."
    )


def test_the_reader_can_tell_a_write_from_a_read() -> None:
    """That the write derivation found writes at all, which is the trap this one has of its own.

    Every assertion below intersects with `writing_operations`. If that ever returns nothing — the
    use cases stop calling `commit` on a name this reader recognises — every divergence becomes a
    read, the file goes green and stops asking its question.
    """
    empty = sorted(
        domain
        for domain in domains()
        if domain not in _UNREADABLE
        and api_operations(domain)
        and not writing_operations(domain)
    )

    assert empty == [], (
        f"no write found in {empty}, which cannot be right for a domain that answers at all: the "
        f"derivation in `operations.writing_operations` has stopped seeing the commits."
    )


def test_a_domain_with_pages_is_declared_or_compared() -> None:
    """Every domain is either API-only ON PURPOSE or has both surfaces held against each other.

    The middle state — a domain that lost its pages and nobody noticed — is the one this catches.
    """
    undeclared = sorted(
        domain
        for domain in domains()
        if domain not in _UNREADABLE
        and not ssr_operations(domain)
        and domain not in _API_ONLY
    )

    assert undeclared == [], (
        f"these answer only as JSON and nothing says that was the intention: {undeclared}. Add them "
        f"to `_API_ONLY` with the reason, or give them the pages the other domains have."
    )


@pytest.mark.parametrize("domain", [d for d in domains() if d not in _API_ONLY])
def test_a_write_reaches_both_surfaces_or_is_written_down(domain: str) -> None:
    """An operation that CHANGES data is reachable from the pages AND from the API, or it is named.

    This is the assertion the BFF claim rests on, and the one that stops the demos teaching a
    capability they only half show. A reader who has just placed an order through the pages and
    reaches for the endpoint that bills it should not discover it is not there — and the reverse,
    an endpoint with no screen, is the same failure seen from the other side.

    Reads are deliberately outside this: they diverge symmetrically and by shape, which the module
    docstring measures. It is the writes that are a capability.
    """
    unnamed = sorted(
        f"{domain}.{operation}"
        for operation in _divergent_writes(domain)
        if f"{domain}.{operation}" not in _WRITE_ON_ONE_SURFACE
    )

    assert unnamed == [], (
        f"these WRITE and are reachable from one surface only: {unnamed}. Either give the other "
        f"surface the operation, or add it to `_WRITE_ON_ONE_SURFACE` above — and say whether that "
        f"is a DECISION or that it is NOT AUDITED. The second is an honest thing to write; a "
        f"rationale you do not have is not."
    )


def test_no_entry_outlives_its_reason() -> None:
    """An entry disappears when the operation reaches both surfaces, or when it stops writing.

    Same bargain the rest of this repository's catalogues strike: a written reason has to expire
    when it is spent. Without this the catalogue becomes a description of the demo as it was on the
    day somebody last looked, which reads exactly like a description of the demo.
    """
    stale = sorted(
        entry
        for entry in _WRITE_ON_ONE_SURFACE
        if (domain := entry.split(".", 1)[0]) not in _UNREADABLE
        and entry.split(".", 1)[1] not in _divergent_writes(domain)
    )

    grown = sorted(domain for domain in _API_ONLY if ssr_operations(domain))

    assert stale == [], (
        f"these are recorded as reachable from one surface only and no longer are: {stale}. Strike "
        f"them off — a catalogue that keeps closed entries stops being read."
    )
    assert grown == [], (
        f"these are declared API-only and have grown pages: {grown}. The declaration in `_API_ONLY` "
        f"is now describing a decision that was reversed."
    )
