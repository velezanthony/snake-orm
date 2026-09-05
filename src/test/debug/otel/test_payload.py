"""The OTLP/HTTP JSON body: the ~60 lines of stdlib that replace the whole SDK.

The shape is protobuf's JSON mapping, so it is picky in ways JSON alone is not: a 64-bit field
travels as a STRING (`startTimeUnixNano`, `intValue`), every attribute is a `{key, value}` pair with
the value tagged by type, and an absent parent is an ABSENT field rather than an empty one. Getting
any of those wrong is a 400 from the collector, not a wrong picture.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from snakeorm.debug.otel import (
    AttributeValue,
    SnakeSpan,
    SpanEvent,
    SpanKind,
    encode_payload,
    otlp_payload,
)


def _span(
    *,
    kind: SpanKind = SpanKind.CLIENT,
    parent_span_id: str = "",
    attributes: tuple[tuple[str, AttributeValue], ...] = (),
    events: tuple[SpanEvent, ...] = (),
) -> SnakeSpan:
    """A minimal span, with whatever a test needs to vary on top."""
    return SnakeSpan(
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id=parent_span_id,
        name="SELECT orders",
        kind=kind,
        start_unix_nano=1_700_000_000_000_000_000,
        end_unix_nano=1_700_000_000_002_000_000,
        attributes=attributes,
        events=events,
    )


def _resource(payload: Mapping[str, object]) -> dict[str, object]:
    """The single `resourceSpans` entry of the payload."""
    entries = cast("list[dict[str, object]]", payload["resourceSpans"])
    return entries[0]


def _first_span(payload: Mapping[str, object]) -> dict[str, object]:
    """Dig the single span out of the `resourceSpans` / `scopeSpans` nesting."""
    scopes = cast("list[dict[str, object]]", _resource(payload)["scopeSpans"])
    spans = cast("list[dict[str, object]]", scopes[0]["spans"])
    return spans[0]


def test_the_service_name_rides_on_the_resource() -> None:
    """`service.name` is what Jaeger lists in its Service dropdown: it goes on the resource."""
    payload = otlp_payload((_span(),), service_name="flask-demo")
    resource = cast("dict[str, object]", _resource(payload)["resource"])

    assert resource["attributes"] == [
        {"key": "service.name", "value": {"stringValue": "flask-demo"}}
    ]


def test_the_scope_names_the_instrumentation() -> None:
    """The scope says WHO produced the spans, which is how a reader tells ours from the app's."""
    scopes = cast(
        "list[dict[str, object]]",
        _resource(otlp_payload((_span(),), service_name="x"))["scopeSpans"],
    )
    scope = cast("dict[str, object]", scopes[0]["scope"])

    assert scope["name"] == "snakeorm"


def test_the_timestamps_travel_as_strings() -> None:
    """A 64-bit integer is a STRING in protobuf's JSON mapping; a number loses precision past 2^53."""
    span = _first_span(otlp_payload((_span(),), service_name="x"))

    assert span["startTimeUnixNano"] == "1700000000000000000"
    assert span["endTimeUnixNano"] == "1700000000002000000"


def test_an_orphan_span_omits_the_parent_field() -> None:
    """No parent means the field is ABSENT: an empty `parentSpanId` is not the same as none."""
    span = _first_span(otlp_payload((_span(),), service_name="x"))

    assert "parentSpanId" not in span


def test_a_parented_span_names_its_parent() -> None:
    """With a parent, `parentSpanId` carries its hex id and Jaeger draws one tree."""
    span = _first_span(
        otlp_payload((_span(parent_span_id="c" * 16),), service_name="x")
    )

    assert span["parentSpanId"] == "c" * 16


def test_each_attribute_type_gets_its_own_tag() -> None:
    """String, int, double, bool and string array each map to their own OTLP value tag."""
    attributes: tuple[tuple[str, AttributeValue], ...] = (
        ("db.query.text", "SELECT 1"),
        ("code.line.number", 48),
        ("snakeorm.db_ms", 12.5),
        ("snakeorm.has_n_plus_one", True),
        ("snakeorm.warnings", ("one", "two")),
    )
    span = _first_span(otlp_payload((_span(attributes=attributes),), service_name="x"))

    assert span["attributes"] == [
        {"key": "db.query.text", "value": {"stringValue": "SELECT 1"}},
        {"key": "code.line.number", "value": {"intValue": "48"}},
        {"key": "snakeorm.db_ms", "value": {"doubleValue": 12.5}},
        {"key": "snakeorm.has_n_plus_one", "value": {"boolValue": True}},
        {
            "key": "snakeorm.warnings",
            "value": {
                "arrayValue": {
                    "values": [{"stringValue": "one"}, {"stringValue": "two"}]
                }
            },
        },
    ]


def test_a_bool_is_not_encoded_as_an_int() -> None:
    """`bool` is a subclass of `int` in Python: tagged in the wrong order, `False` ships as `0`."""
    span = _first_span(
        otlp_payload((_span(attributes=(("flag", False),)),), service_name="x")
    )

    assert span["attributes"] == [{"key": "flag", "value": {"boolValue": False}}]


def test_the_events_carry_their_own_instant_and_attributes() -> None:
    """An event is what gives an aggregate a ROW on the timeline: time, name and its own attributes."""
    event = SpanEvent(
        name="snakeorm.warning",
        time_unix_nano=1_700_000_000_000_000_000,
        attributes=(("snakeorm.warning", "the same SQL ran 500 times"),),
    )
    span = _first_span(otlp_payload((_span(events=(event,)),), service_name="x"))

    assert span["events"] == [
        {
            "name": "snakeorm.warning",
            "timeUnixNano": "1700000000000000000",
            "attributes": [
                {
                    "key": "snakeorm.warning",
                    "value": {"stringValue": "the same SQL ran 500 times"},
                }
            ],
        }
    ]


def test_the_span_kind_travels_as_its_number() -> None:
    """OTLP spells the kind as an enum number: SERVER is 2, CLIENT 3, INTERNAL 1."""
    span = _first_span(otlp_payload((_span(kind=SpanKind.SERVER),), service_name="x"))

    assert span["kind"] == 2


def test_the_body_is_valid_json_bytes() -> None:
    """`encode_payload` gives the bytes the POST sends, and they parse back into the same payload."""
    payload = otlp_payload((_span(),), service_name="x")
    body = encode_payload(payload)

    assert json.loads(body) == payload
