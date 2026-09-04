"""What can be CHECKED about the history tab's client half, and what plainly cannot.

The tab is the panel's only dynamic view: the server paints an empty skeleton and `assets/js/history.js`
fills it at runtime with the calls the page makes after the render. None of that runs in pytest —
there is no `fetch`, no `XMLHttpRequest` and no DOM here — so this file does NOT claim to test the
behaviour. It checks the MECHANICAL facts that hold the wiring together and that break silently:

- the module travels in the bundle at all, and after the module it depends on;
- the orchestrator mounts it (an unmounted module is a file nobody runs);
- every i18n key it declares exists in both languages, the same existence `test_i18n.py` checks for
  the keys the server paints — with the difference that these are painted by JavaScript, so the
  server-side scan cannot see them and they would go missing with nothing noticing.

Whether the wrappers actually observe a call, and whether they hand the application back exactly
what it would have got, is verified in a BROWSER against the demos. A test that greps this file for
`clone()` would be promising behaviour it cannot measure — a test that cannot deliver on its own
name, which is worse than no test because it manufactures confidence.
"""

from __future__ import annotations

import re
from importlib import resources

from snakeorm.debug.html import _PANEL_JS, render_report_html
from snakeorm.debug.record import QueryKind, QueryRecord
from snakeorm.debug.report import DebugReport

_JS = resources.files("snakeorm.debug") / "assets" / "js"


def _report() -> DebugReport:
    """A one-query report: enough for the panel to render its badge and its views."""
    record = QueryRecord(
        n=1,
        sql="SELECT 1",
        params=(),
        duration_ms=1.0,
        rows=1,
        kind=QueryKind.SELECT,
        origin=None,
    )
    return DebugReport.from_records([record], wall_ms=5.0)


def _source(name: str) -> str:
    """The text of one of the panel's JS modules."""
    return (_JS / name).read_text(encoding="utf-8")


def test_the_panel_bundle_ships_the_history_module() -> None:
    """The rendered panel carries `SnakeOrmHistory`: the tab's client half travels with the panel.

    The assets are INLINED (the panel is injected into somebody else's page and cannot fetch
    anything), so a module missing from the concatenation is a tab that renders and never fills.
    """
    assert "SnakeOrmHistory" in render_report_html(_report())


def test_the_bundle_defines_the_history_after_what_it_leans_on() -> None:
    """`history.js` comes after `panel.js` in the concatenation, because it uses what that defines.

    There is no runtime `import`: the modules share one scope by living in the same inlined
    `<script>`, so ORDER is the dependency mechanism. `history.js` reads `SnakeOrmPanel.safe`, and a
    `const` used before its declaration is a TDZ error that would take the whole bundle down —
    including the panel, in somebody else's page.
    """
    assert _PANEL_JS.index("const SnakeOrmPanel") < _PANEL_JS.index(
        "const SnakeOrmHistory"
    )
    assert _PANEL_JS.index("const SnakeOrmHistory") < _PANEL_JS.index(
        "const snakeOrmDebug"
    )


def test_the_orchestrator_mounts_the_history() -> None:
    """The orchestrator mounts the history, like it mounts the panel: a module nobody calls is dead.

    Wiring lives in `snake_orm_app.js` and nowhere else, which is why this is asserted there and not
    on the module itself.
    """
    assert "SnakeOrmHistory.mount" in _source("snake_orm_app.js")


def test_the_history_watches_the_two_browser_primitives() -> None:
    """The module names `fetch` and `XMLHttpRequest`, which are the two ways a page makes a call.

    HTMX goes through XHR and everything else through `fetch`. Watching the primitives covers
    callers this file has never heard of; watching a library's events would only ever find the
    libraries already listed.
    """
    source = _source("history.js")

    assert "window.fetch" in source
    assert "XMLHttpRequest.prototype" in source


def test_the_history_asks_the_sidecar_for_json() -> None:
    """The detail is fetched from `/__snake__/` as JSON, which is the shape the sidecar negotiates.

    A call whose report travelled in HEADERS has no body to read it out of; the token is the only
    way back to it, and asking for the panel page instead would mean parsing markup for data.
    """
    source = _source("history.js")

    assert "/__snake__/" in source
    assert "application/json" in source


_KEY_TABLE = re.compile(r"const KEY = \{(.*?)\};", re.DOTALL)
_KEY_VALUE = re.compile(r":\s*'([a-z0-9_]+)'")


def _declared_keys() -> list[str]:
    """The i18n keys `history.js` declares in its `KEY` table (its single list of painted texts)."""
    table = _KEY_TABLE.search(_source("history.js"))
    assert table, "the KEY table of history.js was not found"
    return sorted(set(_KEY_VALUE.findall(table.group(1))))


def _language_halves() -> tuple[str, str]:
    """The ES half and the EN half of `language.js`, split at the `[LANG.EN]` entry."""
    spanish, marker, english = _source("language.js").partition("[LANG.EN]: {")
    assert marker, "the EN block of language.js was not found"
    return spanish, english


def test_the_history_declares_the_keys_it_paints() -> None:
    """The `KEY` table is not empty: it is where the check below gets its list from.

    Without this, an emptied table would make the translation test pass by having nothing to check —
    green because it stopped looking, which is the exact shape of a test that fabricates confidence.
    """
    assert len(_declared_keys()) >= 5


def test_every_key_the_history_declares_is_translated_in_both_languages() -> None:
    """Each key in the `KEY` table has an ES entry AND an EN entry in `language.js`.

    `test_i18n.py` checks this for the keys the SERVER paints, by scanning the rendered HTML. These
    are painted by the client, from JavaScript, so that scan cannot see them: without this the
    history would be the one corner of a bilingual panel where a language can go missing unnoticed.
    """
    spanish, english = _language_halves()

    missing = [
        key
        for key in _declared_keys()
        if f"{key}:" not in spanish or f"{key}:" not in english
    ]

    assert missing == [], f"keys with no entry in both languages: {missing}"


_HISTORY_CARDS = ("calls", "queries", "db", "map", "slowest")
"""The aggregates the tab paints over its OWN list. `calls` is the unit the header does not have:
up there a request is THE request; down here they are many, and that is the whole difference."""


def test_the_history_tab_paints_its_own_metric_cards() -> None:
    """The tab carries a card per aggregate, with the hook the client writes the number into.

    The SERVER paints the skeleton (labels, tooltips, i18n keys) and the client only writes digits:
    that way the tab's texts go through the same translation check every other panel text does.
    """
    html = render_report_html(_report())

    assert "snk-hmetrics" in html
    for name in _HISTORY_CARDS:
        assert f'data-hm="{name}"' in html, name


def test_the_history_cards_reuse_the_panel_card_and_its_grid() -> None:
    """They are `snk-metrics`/`snk-m`, the SAME classes as the header: one visual language, not two.

    A second card class would drift from the first the day either one is restyled.
    """
    html = render_report_html(_report())
    start = html.index('class="snk-metrics snk-hmetrics"')

    assert 'class="snk-m"' in html[start : start + 2000]


def test_every_history_card_explains_itself() -> None:
    """Each card carries its own tooltip key: what it aggregates is not guessable from the label.

    They cannot reuse the header's tips — `db` up there is one request, down here it is the sum of
    many — so each has its own `h*_tip`, and `test_i18n` checks both languages have it.
    """
    html = render_report_html(_report())
    for name in _HISTORY_CARDS:
        assert f'data-tt="h{name}_tip"' in html, name


def test_the_partial_cards_carry_a_coverage_slot() -> None:
    """Every aggregate except `calls` has a slot for "3/5": how much of the list it is computed over.

    NOT EVERY ENTRY BRINGS THE SAME DATA — a JSON call carries the whole report, an HTMX one only
    what fits in `Server-Timing` — so a call can arrive with no count and no ms. A missing number is
    not a zero: summing zeros gives a total that looks exact and is false. The slot is where the
    card admits what it could not count. `calls` has none because it is always the whole list.
    """
    html = render_report_html(_report())

    assert 'data-hm-part="calls"' not in html
    for name in ("queries", "db", "map", "slowest"):
        assert f'data-hm-part="{name}"' in html, name
    assert 'data-tt="hpart_tip"' in html  # and the slot says what it means


def test_the_history_reads_the_mapping_slice_from_both_shapes() -> None:
    """The client takes the mapping from the report's `mapping_ms` OR from `Server-Timing`'s `map`.

    Two shapes because there are two kinds of entry, and the poor one is the common one: an HTMX
    fragment answers with headers and no body at all.
    """
    source = _source("history.js")

    assert "report.mapping_ms" in source
    assert "timed.map" in source


def test_the_badge_says_what_it_counts() -> None:
    """The FAB badge carries a tooltip key, because what it counts changed under the reader.

    It used to be the queries of the request that rendered the page; it now grows with every call
    the page makes afterwards, so it stops matching the report printed right beneath it. A number
    that disagrees with the one next to it has to be able to say why.
    """
    assert 'data-tt="badge_tip"' in render_report_html(_report())
