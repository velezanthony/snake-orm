"""Reading the trace context the APPLICATION already has open, if it has one.

This is the ONLY thing `opentelemetry-api` is needed for, and it is the only thing that cannot be
reimplemented: a process-wide context variable owned by a library we do not control. Everything else
in this channel —the payload, the HTTP POST, the queue— is stdlib.

It degrades three ways and none of them raises: no library installed, no provider active, or a
provider that misbehaves. All three give `None`, which turns our span into a loose root instead of a
child.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TraceContext:
    """The active span, in the hex form OTLP/JSON wants: 32 characters of trace, 16 of span."""

    trace_id: str
    span_id: str


def active_context() -> TraceContext | None:
    """The application's active span, or `None` if there is none to hang off.

    `ImportError` is the expected path for an application that never installed the extra, so it is
    caught rather than guarded with a flag. The broad catch underneath is deliberate too: a
    telemetry read has no business turning into a 500.
    """
    try:
        from opentelemetry import trace

        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return None
        return TraceContext(
            trace_id=format(span_context.trace_id, "032x"),
            span_id=format(span_context.span_id, "016x"),
        )
    except Exception:
        return None
