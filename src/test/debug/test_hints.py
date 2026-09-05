"""Tests for the index HINTS in the panel: they travel inside the report and get painted if any.

The middleware computes `(table, column)` with the advisor and puts them into the `DebugReport`; the
panel paints a box only when this page filtered by a column without an index.
"""

from __future__ import annotations

from snakeorm.debug.html import render_report_html
from snakeorm.debug.record import QueryKind, QueryRecord
from snakeorm.debug.report import DebugReport


def _record() -> QueryRecord:
    """Any old record (the content does not matter for these tests)."""
    return QueryRecord(
        n=1, sql="SELECT 1", params=(), duration_ms=1.0, rows=1, kind=QueryKind.SELECT
    )


def test_panel_renders_index_hints_with_duration() -> None:
    """With hints, the panel paints the box with `table.column` and the duration that justifies it."""
    report = DebugReport.from_records([_record()]).with_index_hints(
        (("posts", "author_id", 500.0),)
    )
    html = render_report_html(report)
    assert 'class="snk-hints"' in html  # the ELEMENT (not the CSS selector)
    assert "posts.author_id" in html
    assert "500 ms" in html  # the duration that triggered it
    assert 'data-t="hint_title"' in html


def test_no_hints_section_when_empty() -> None:
    """With no hints (everything fast/indexed), the box is NOT painted (even though the CSS defines it)."""
    html = render_report_html(DebugReport.from_records([_record()]))
    assert 'class="snk-hints"' not in html


def test_envelope_includes_index_hints_with_duration() -> None:
    """The JSON envelope exposes the hints as `table.column (Xms)`."""
    report = DebugReport.from_records([_record()]).with_index_hints(
        (("posts", "author_id", 500.0),)
    )
    assert report.to_dict()["index_hints"] == ["posts.author_id (500ms)"]
