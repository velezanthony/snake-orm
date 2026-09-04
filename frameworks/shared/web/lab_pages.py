"""Which of the lab pager's TWO templates answers a request: the whole page, or the panel alone.

WHY THIS IS SHARED AND "IS THIS AN HTMX REQUEST?" IS NOT. The two look like one question and they
fall on opposite sides of the line this package draws.

Reading the headers is a fact about the REQUEST, and each demo already has an idiomatic way to do it:
Django asks `request.htmx`, which django-htmx's middleware puts there; Flask reads the headers off
`request`. Lifting THAT into a shared helper buys a `bool()` with a name on it, because the caller
still has to fetch the flags its own way — and a request, a URL or a response is precisely what
`shared.web` says it will never hold.

The RULE below is a different thing, and it is worth exactly one implementation:

- Which two templates the pager has. Both demos keep two sets of templates laid out identically
  (`test_demo_templates_match.py` makes that a fact), so both views choose between the same pair of
  paths. Written twice, that is two copies of one page's meaning — the shape `apps/lab/urls.py`
  opens by saying it is a correction of.
- WHEN the fragment is the right answer, which is not simply "htmx asked". On a history cache miss
  htmx re-requests the page it is going back to with `HX-Request: true` AND
  `HX-History-Restore-Request: true`, and swaps what comes back into the whole `<body>`. Answer that
  with the fragment and the back button replaces the page with a bare table. It is invisible until
  somebody presses Back after the cache has rolled over, and it would be found once per demo.
"""

from __future__ import annotations

# The whole page: shell, sidebar, intro and the panel inside it. What a browser navigating gets.
PAGINATION_PAGE = "lab/pagination/lab_pagination.html"

# The panel ALONE: the table and its prev/next. What HTMX swaps in, and it carries the swap target's
# own id so the next page turn has something to aim at.
PAGINATION_FRAGMENT = "lab/_pagination.html"


def pagination_template(*, htmx: bool, restoring_history: bool) -> str:
    """The template the lab's pager answers with, given the two things the request says about itself.

    Both flags come from the caller because both are read from headers, and headers are the demo's
    half of this. What is decided here is what they MEAN together.
    """
    return PAGINATION_FRAGMENT if htmx and not restoring_history else PAGINATION_PAGE
