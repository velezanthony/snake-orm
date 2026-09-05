"""The `otel` channel: the debug report as OpenTelemetry spans, over OTLP/HTTP.

It is the one delivery meant for PRODUCTION, and the only one whose consumer is a tool rather than a
person. Its audience is `OPERATOR`: it goes out sideways to infrastructure the operator already
runs, instead of riding on the response. That is why it is NOT in `RISKY_CHANNELS`: putting it there
would drop it exactly where it justifies existing.

Riding on the response is NOT what makes a channel risky — `timing` rides it and is harmless. What
decides it is whether the requester ends up holding the SQL, which is what `ChannelAudience` asks.

What travels is the parametrised SQL and never the values. The convention collects `db.query.text`
by default "because parametrising is a strong signal from the user that anything sensitive is in
the values", and SnakeORM never interpolates. The values are opt-in, key by key, from code.

Four pieces:

- `context` — the only thing `opentelemetry-api` is for: is a span already open, and which.
- `summary` — `db.query.summary`, which NAMES the span (`SELECT orders`, not the whole SQL).
- `spans`   — the pure mapping from a `DebugReport` to the hybrid shape.
- `payload` / `exporter` — OTLP's JSON and the background queue that posts it.
"""

from snakeorm.debug.otel.context import TraceContext as TraceContext
from snakeorm.debug.otel.context import active_context as active_context
from snakeorm.debug.otel.exporter import DEFAULT_ENDPOINT as DEFAULT_ENDPOINT
from snakeorm.debug.otel.exporter import DEFAULT_SERVICE_NAME as DEFAULT_SERVICE_NAME
from snakeorm.debug.otel.exporter import ENDPOINT_ENV_KEY as ENDPOINT_ENV_KEY
from snakeorm.debug.otel.exporter import OtelExporter as OtelExporter
from snakeorm.debug.otel.exporter import SERVICE_NAME_ENV_KEY as SERVICE_NAME_ENV_KEY
from snakeorm.debug.otel.exporter import (
    TRACES_ENDPOINT_ENV_KEY as TRACES_ENDPOINT_ENV_KEY,
)
from snakeorm.debug.otel.exporter import Transport as Transport
from snakeorm.debug.otel.exporter import current_exporter as current_exporter
from snakeorm.debug.otel.exporter import endpoint_from_env as endpoint_from_env
from snakeorm.debug.otel.exporter import post_json as post_json
from snakeorm.debug.otel.exporter import service_name_from_env as service_name_from_env
from snakeorm.debug.otel.exporter import set_exporter as set_exporter
from snakeorm.debug.otel.payload import SCOPE_NAME as SCOPE_NAME
from snakeorm.debug.otel.payload import encode_payload as encode_payload
from snakeorm.debug.otel.payload import otlp_payload as otlp_payload
from snakeorm.debug.otel.report import export_report as export_report
from snakeorm.debug.otel.spans import CODE_FILE_PATH as CODE_FILE_PATH
from snakeorm.debug.otel.spans import CODE_FUNCTION_NAME as CODE_FUNCTION_NAME
from snakeorm.debug.otel.spans import CODE_LINE_NUMBER as CODE_LINE_NUMBER
from snakeorm.debug.otel.spans import DB_COLLECTION_NAME as DB_COLLECTION_NAME
from snakeorm.debug.otel.spans import DB_NAMESPACE as DB_NAMESPACE
from snakeorm.debug.otel.spans import DB_OPERATION_NAME as DB_OPERATION_NAME
from snakeorm.debug.otel.spans import (
    DB_QUERY_PARAMETER_PREFIX as DB_QUERY_PARAMETER_PREFIX,
)
from snakeorm.debug.otel.spans import DB_QUERY_SUMMARY as DB_QUERY_SUMMARY
from snakeorm.debug.otel.spans import DB_QUERY_TEXT as DB_QUERY_TEXT
from snakeorm.debug.otel.spans import (
    DB_RESPONSE_RETURNED_ROWS as DB_RESPONSE_RETURNED_ROWS,
)
from snakeorm.debug.otel.spans import DB_SYSTEM_NAME as DB_SYSTEM_NAME
from snakeorm.debug.otel.spans import SNAKEORM_HAS_N_PLUS_ONE as SNAKEORM_HAS_N_PLUS_ONE
from snakeorm.debug.otel.spans import AttributeValue as AttributeValue
from snakeorm.debug.otel.spans import IdSource as IdSource
from snakeorm.debug.otel.spans import RandomIds as RandomIds
from snakeorm.debug.otel.spans import SnakeSpan as SnakeSpan
from snakeorm.debug.otel.spans import SpanEvent as SpanEvent
from snakeorm.debug.otel.spans import SpanKind as SpanKind
from snakeorm.debug.otel.spans import monotonic_epoch_ns as monotonic_epoch_ns
from snakeorm.debug.otel.spans import spans_from_report as spans_from_report
from snakeorm.debug.otel.summary import QuerySummary as QuerySummary
from snakeorm.debug.otel.summary import summarise as summarise
