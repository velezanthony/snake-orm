"""`export_report`: the ONE call the three web adapters make, and where the channel is checked.

It lives here and not in `contrib/deliver.py` on purpose. `plan_delivery` is a PURE function that
answers `(headers, envelope)` — two things that modify the response — and `Delivery` is exactly that
pair. Sending bytes over the network is neither, and widening that dataclass to hold an I/O side
effect would dissolve the reason `deliver.py` exists. So this is shared the way `index_advice`
already is: one function, called from all three adapters right after `report.with_request(...)`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakeorm.debug.channel import SnakeDebugChannel
from snakeorm.debug.otel.exporter import current_exporter

if TYPE_CHECKING:
    from snakeorm.debug.report import DebugReport


def export_report(report: DebugReport, channels: frozenset[SnakeDebugChannel]) -> None:
    """Queue the report as spans when the `otel` channel is on; do nothing at all when it is not.

    With the channel off the whole cost is one frozenset membership test: no exporter is built, no
    thread is started and `opentelemetry` is never imported.
    """
    if SnakeDebugChannel.OTEL not in channels:
        return
    current_exporter().submit(report)
