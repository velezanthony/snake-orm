"""The OTLP/HTTP JSON body: the ~60 lines of stdlib that stand in for the whole SDK.

The shape is protobuf's JSON mapping, which is picky in ways plain JSON is not, and each pickiness
is a 400 from the collector rather than a wrong picture:

- A 64-bit field travels as a STRING (`startTimeUnixNano`, `intValue`). A JSON number loses
  precision above 2^53, and a Unix nanosecond is well past that.
- Every attribute is a `{key, value}` pair with the value TAGGED by type.
- An absent parent is an ABSENT field, not an empty one.
"""

from __future__ import annotations

import json

from snakeorm.debug.otel.spans import AttributeValue, SnakeSpan, SpanEvent

SCOPE_NAME = "snakeorm"
"""Who produced these spans. It is how a reader tells ours from the application's own."""

SERVICE_NAME_KEY = "service.name"
"""The resource attribute Jaeger lists in its Service dropdown."""


def otlp_payload(
    spans: tuple[SnakeSpan, ...], *, service_name: str
) -> dict[str, object]:
    """The complete `resourceSpans` document for one export, ready to be serialised."""
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [_attribute(SERVICE_NAME_KEY, service_name)]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": SCOPE_NAME},
                        "spans": [_span(span) for span in spans],
                    }
                ],
            }
        ]
    }


def encode_payload(payload: dict[str, object]) -> bytes:
    """The bytes the POST sends. Compact and UTF-8: nothing here is read by a person."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def _span(span: SnakeSpan) -> dict[str, object]:
    """One span in OTLP's JSON shape, omitting the parent when there is none."""
    encoded: dict[str, object] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "name": span.name,
        "kind": int(span.kind),
        "startTimeUnixNano": str(span.start_unix_nano),
        "endTimeUnixNano": str(span.end_unix_nano),
        "attributes": [_attribute(key, value) for key, value in span.attributes],
    }
    if span.parent_span_id:
        encoded["parentSpanId"] = span.parent_span_id
    if span.events:
        encoded["events"] = [_event(event) for event in span.events]
    return encoded


def _event(event: SpanEvent) -> dict[str, object]:
    """One span event: its instant, its name and its own attributes."""
    return {
        "name": event.name,
        "timeUnixNano": str(event.time_unix_nano),
        "attributes": [_attribute(key, value) for key, value in event.attributes],
    }


def _attribute(key: str, value: AttributeValue) -> dict[str, object]:
    """A `{key, value}` pair with the value tagged by its type."""
    return {"key": key, "value": _value(value)}


def _value(value: AttributeValue) -> dict[str, object]:
    """Tag a value with its OTLP type.

    `bool` is checked FIRST on purpose: in Python it is a subclass of `int`, so the obvious order
    ships every `True` as the integer `1` and the flag stops being a flag in the backend's index.
    """
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, tuple):
        return {"arrayValue": {"values": [{"stringValue": item} for item in value]}}
    return {"stringValue": value}
