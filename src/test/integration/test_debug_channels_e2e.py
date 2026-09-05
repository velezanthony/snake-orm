"""The debug panel over the THREE engines: what it captures, and what it says the engine is.

The channels were held up by tests over a fake driver and a Postgres session. That checks the shape
of the report and nothing about the engine underneath — and the engine is not incidental here: the
`system` a record carries is what a tracer groups spans by, and it is DECLARED by the backend enum
rather than sniffed from the SQL, precisely because no statement distinguishes MySQL from MariaDB.

So this asks the question the shape tests cannot: over a real session on each engine, does the
collector capture the statements, and does every record name the right system?
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeBackend,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.debug import (
    CaptureDriver,
    capture_queries,
    render_report_html,
    render_report_page,
)
from snakeorm.debug.otel.spans import spans_from_report
from snakeorm.drivers.base import SnakeDriver
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]

_SYSTEM = {
    "postgres": SnakeBackend.POSTGRES.db_system_name,
    "mysql": SnakeBackend.MYSQL.db_system_name,
    "sqlite": SnakeBackend.SQLITE.db_system_name,
}


@snake_model(table="dbg_widgets")
class Widget(SnakeModel):
    """Something to read, so the collector has statements to record."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=50)


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three sessions, each wrapped in the capture driver the frameworks actually ship."""

    def wrap(engine: str, driver: SnakeDriver) -> SnakeDriver:
        return CaptureDriver(driver, system=_SYSTEM[engine])

    with three_sessions([Widget], wrap=wrap) as sessions:
        for session in sessions.values():
            session.add(Widget(id=1, name="tuerca"))
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_collector_records_what_ran_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Inside a scope the statements are recorded; the count is the panel's whole product."""
    session = engines[engine]

    with capture_queries() as collector:
        session.all(SnakeQuery(Widget))
        session.count(SnakeQuery(Widget))

    assert collector.report().count == 2, (
        f"{engine}: the collector did not record both statements"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_every_record_names_the_engine_it_ran_on(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The `system` is DECLARED, and this is what makes declaring it worth the trouble.

    A tracer groups by it, so a wrong one silently merges two databases into one service. It cannot
    be sniffed from the SQL: no statement tells MySQL and MariaDB apart.
    """
    session = engines[engine]

    with capture_queries() as collector:
        session.all(SnakeQuery(Widget))

    systems = {record.system for record in collector.report().records}
    assert systems == {_SYSTEM[engine]}, (
        f"{engine}: the records name {systems} instead of {_SYSTEM[engine]!r}"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_outside_a_scope_nothing_is_recorded_and_nothing_breaks(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The null check is what makes the capture driver free in production.

    With no scope open it delegates straight through, so a session left wrapped by accident costs
    nothing — which is the only reason wrapping by default is defensible at all.
    """
    session = engines[engine]

    rows = session.all(SnakeQuery(Widget))

    assert [row.name for row in rows] == ["tuerca"]

    with capture_queries() as collector:
        pass

    assert collector.report().count == 0


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_three_shapes_of_the_report_answer_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """One report, three readers: the envelope dict, the text, and the Server-Timing header.

    They are asserted together because they are three views of ONE object: a change that feeds one
    and starves another is exactly the drift that having three of them invites.
    """
    session = engines[engine]

    with capture_queries() as collector:
        session.all(SnakeQuery(Widget))
    report = collector.report()

    envelope = report.to_dict()
    assert envelope["count"] == 1
    assert "dbg_widgets" in report.to_text()
    assert "db;dur=" in report.to_server_timing()


# -- The renderers, fed from a report built on each engine -----------------------------------------


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_ssr_panel_renders_from_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The HTML panel is self-contained, and it has to survive whatever SQL the engine produced.

    Not a shape test: the report is real, built from statements a real engine ran, so the quoting
    each dialect uses travels into the markup that gets escaped.
    """
    session = engines[engine]

    with capture_queries() as collector:
        session.all(SnakeQuery(Widget))

    html = render_report_html(collector.report())

    assert "dbg_widgets" in html
    assert "<script" in html, "the panel must ship its own behaviour, with no CDN"


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_sidecar_page_is_a_whole_document_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The sidecar serves a COMPLETE document, because nothing else on the page frames it."""
    session = engines[engine]

    with capture_queries() as collector:
        session.all(SnakeQuery(Widget))

    page = render_report_page(collector.report())

    # Case-insensitive on purpose: the page emits `<!doctype html>` in lower case, and asserting
    # the spelling instead of the FACT would be this test having an opinion about style.
    assert page.lstrip().lower().startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")
    assert "dbg_widgets" in page


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_otel_spans_carry_the_engine_they_ran_on(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """One CLIENT child per statement, and each names its `db.system.name`.

    That attribute is what a tracer groups a service by, so getting it wrong merges two databases
    into one in the UI — a failure that looks like a graph rather than an error.
    """
    session = engines[engine]

    with capture_queries() as collector:
        session.all(SnakeQuery(Widget))

    spans = spans_from_report(collector.report())
    children = spans[1:]

    assert children, f"{engine}: no child span for the statement that ran"
    for span in children:
        # `attributes` is a tuple of PAIRS and not a dict: the span is frozen and ordered, which is
        # what lets it be hashed and compared. Reading it means building the mapping here.
        attributes = dict(span.attributes)
        assert attributes["db.system.name"] == _SYSTEM[engine]
