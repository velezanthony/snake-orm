"""Tests for the ORIGIN capture: the record knows which file/line/function the query came from.

It is the information Django Debug Toolbar gives: not just WHICH query ran, but WHO fired it, so the
code to blame for the extra calls can be found. They are captured by skipping the ORM's INTERNAL
frames (just as DDT skips the framework's): the first frame of user code is the origin.
"""

from __future__ import annotations

from snakeorm.debug.collector import capture_queries
from snakeorm.debug.html import render_report_html
from snakeorm.debug.origin import capture_origin
from snakeorm.debug.record import QueryKind, QueryOrigin, QueryRecord
from snakeorm.debug.report import DebugReport


def _record_with_origin() -> QueryRecord:
    """A record with a known origin (file/line/function), to test the render and the envelope."""
    return QueryRecord(
        n=1,
        sql="SELECT 1",
        params=(),
        duration_ms=1.0,
        rows=1,
        kind=QueryKind.SELECT,
        origin=QueryOrigin(file="/proj/app/views.py", line=42, function="list_posts"),
    )


def test_add_records_origin_of_caller() -> None:
    """`collector.add` stores the origin: the file and the function of the code that fired the query."""
    with capture_queries() as collector:
        collector.add(
            sql="SELECT 1", params=(), duration_ms=1.0, rows=1, kind=QueryKind.SELECT
        )
    record = collector.report().records[0]
    assert record.origin is not None
    assert record.origin.file == __file__
    assert record.origin.function == "test_add_records_origin_of_caller"
    assert record.origin.line > 0


def test_capture_origin_skips_orm_internal_frames() -> None:
    """`capture_origin` returns the first USER frame, not one internal to the `snakeorm` package."""
    origin = capture_origin()
    assert origin is not None
    assert origin.file == __file__
    assert "snakeorm" not in origin.function


def _helper_that_captures() -> object:
    """Helper: it captures the origin from HERE to prove it points at this function, not at the test one."""
    return capture_origin()


def test_capture_origin_points_to_immediate_user_frame() -> None:
    """The origin is the user frame CLOSEST to the query (here, the helper that fired it)."""
    origin = _helper_that_captures()
    assert origin is not None
    assert getattr(origin, "function") == "_helper_that_captures"


def test_panel_renders_origin() -> None:
    """The panel paints the query's ORIGIN: file:line and the function that fired it."""
    html = render_report_html(DebugReport.from_records([_record_with_origin()]))
    assert "views.py:42" in html
    assert "list_posts" in html


def test_envelope_includes_origin() -> None:
    """The JSON envelope exposes every query's origin (file, line, function)."""
    payload = DebugReport.from_records([_record_with_origin()]).to_dict()
    queries = payload["queries"]
    assert isinstance(queries, list)
    assert queries[0]["origin"] == {
        "file": "/proj/app/views.py",
        "line": 42,
        "function": "list_posts",
    }


def test_envelope_origin_is_none_without_frame() -> None:
    """With no origin resolved, the envelope leaves it explicitly at `None` (it does not break the JSON)."""
    record = QueryRecord(
        n=1, sql="SELECT 1", params=(), duration_ms=1.0, rows=1, kind=QueryKind.SELECT
    )
    payload = DebugReport.from_records([record]).to_dict()
    queries = payload["queries"]
    assert isinstance(queries, list)
    assert queries[0]["origin"] is None
