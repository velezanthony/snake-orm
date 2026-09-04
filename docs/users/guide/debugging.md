# Debugging: seeing the SQL the ORM runs

Wrap the driver with `CaptureDriver` and you can count and see every statement:

```python
from snakeorm import PostgresDialect, SnakeQuery, SnakeSession
from snakeorm.debug import CaptureDriver, assert_queries

session = SnakeSession(CaptureDriver(driver), PostgresDialect())

with assert_queries(2):                                  # fails unless there are exactly 2
    session.all(SnakeQuery(Maker).include(Maker.trucks))  # 1 root + 1 select-in, no N+1
```

For async, wrap with `AsyncCaptureDriver` instead; everything below is the same — see
[Async](../engines/async.md) for the session that goes with it.

That 1 + 1 holds **up to the placeholder ceiling**: the select-in binds one per parent, so past the
engine's limit (65,535 on Postgres/MySQL, 32,766 on SQLite) it splits into batches and there are more
than 2 statements.

The **core** (`snakeorm.debug`) is framework-agnostic; the **adapters** (`snakeorm.contrib`) plug it
into FastAPI, Flask or Django.

## Asking the engine for its plan: `explain()`

Counting statements tells you HOW MANY. `explain()` tells you what the engine is going to do with
one of them, and it does not run it:

```python
for line in session.explain(SnakeQuery(Widget).filter(Widget.stock == 0)):
    print(line)

# Postgres  -> Seq Scan on widgets  (cost=0.00..16.25 rows=2 width=134)
# SQLite    -> 2 0 0 SCAN widgets
# MySQL     -> 1 SIMPLE widgets ALL ... Using where
```

The lines come back as the ENGINE writes them, and that is a decision rather than laziness: Postgres
answers one column, SQLite four and MySQL about a dozen, and they share no field. A common shape
over the three would be invented, not measured.

It costs one extra round trip and the values still travel as parameters. `AsyncSession` has the same
method with the same contract.

## Inspecting the report

```python
from snakeorm.debug import capture_queries

with capture_queries() as collector:
    session.all(SnakeQuery(Maker))

report = collector.report()
print(report.summary)   # "1 queries · 0.3ms · 0 duplicates"
print(report.to_text())  # a table aligned for the terminal
print(report.slowest())  # the slowest QueryRecord, or None
print(report.warnings)   # one line per duplicated group, naming its file:line
for group in report.duplicates():
    print(f"{group.sql} ran {group.count} times at {group.location}")
```

`capture_queries()` only collects what goes through a `CaptureDriver`. Without the wrap the report
comes back empty.

The report carries what the ORM noticed; what it can SHOUT — and which of those stop you — is listed
in [Errors and warnings](../reference/api/errors.md).

## Turning it on for a request: `SNAKE_ORM_DEBUG`

You choose which DELIVERIES you want by composing a set of **channels**:

```bash
SNAKE_ORM_DEBUG=envelope             # one channel
SNAKE_ORM_DEBUG=ssr,envelope,timing  # several; the order does not matter
SNAKE_ORM_DEBUG=                     # empty = off
```

Or typed, in Python config:

```python
from snakeorm.debug import SnakeDebugChannel

SNAKE_ORM_DEBUG = frozenset({
    SnakeDebugChannel.ENVELOPE,
    SnakeDebugChannel.TIMING,
})
```

A `frozenset`, not a list: no duplicates. An unknown channel **fails at startup**, never silently
leaving you without debug.

## The channels

| Channel | What it delivers | For whom |
|-------|-------------|-----------|
| `envelope` | A `snakeorm` block inside the response JSON | Postman / no tooling |
| `timing` | The `Server-Timing` header (W3C) | Browser + devtools |
| `sidecar` | A token + panel at `/__snake__/{token}` (the report as JSON with `Accept: application/json`) | Anyone, API apps included |
| `ssr` | The HTML panel injected into the page | Django / Flask with templates |
| `otel` | Observability spans | Production (Jaeger/Grafana) |

The channel **is** the switch: put `envelope` in `SNAKE_ORM_DEBUG` and it comes on every JSON
response — no query param, no extra flag. Drop the channel and the response goes out clean.

## Plugging it into the framework — one line

=== "FastAPI"

    ```python
    from snakeorm.contrib import SnakeDebugASGI

    app = SnakeDebugASGI(asgi_app, production=False)
    ```

=== "Flask"

    ```python
    from snakeorm.contrib import SnakeDebugWSGI

    app.wsgi_app = SnakeDebugWSGI(app.wsgi_app, production=False)
    ```

=== "Django"

    ```python
    # settings.py
    MIDDLEWARE = [
        # ...
        "snakeorm.contrib.SnakeDebugMiddleware",
    ]
    ```

The adapter applies only the channels that make sense in its framework: `ssr` in an API app is a no-op
that gets **warned** at startup, not silently swallowed.

## The `envelope` shape

The debug hangs off a `snakeorm` key — **without corrupting the shape**:

```jsonc
// An OBJECT response keeps its keys; `snakeorm` is added as a sibling:
{
  "id": 7,
  "email": "ana@x.com",
  "snakeorm": {
    "summary": "3 queries · 1.2ms · 0 duplicates",
    "request": { "method": "GET", "path": "/users/7", "status": 200, "at": "2026-08-27T10:30:00+00:00" },
    "warnings": [],
    "queries": [
      { "n": 1, "ms": 0.4, "sql": "SELECT ... WHERE id = $1", "params": [7], "rows": 1 }
    ]
  }
}

// An ARRAY response (where you can't add a key) is wrapped under `data`:
{ "data": [ { "id": 1 }, { "id": 2 } ], "snakeorm": { "summary": "1 queries · 0.3ms · 0 duplicates" } }
```

## Tuning the middleware: `SnakeDebugConfig`

```python
from snakeorm.contrib import SnakeDebugASGI
from snakeorm.debug import SnakeDebugConfig

config = SnakeDebugConfig(
    advise_min_ms=10.0,   # index advisor: ignore anything faster
    csp_nonce=APP_NONCE,  # one value for the whole process; see below
)

app = SnakeDebugASGI(asgi_app, config=config)
```

`advise_min_ms` feeds the index advisor, whose findings the panel paints and `report.index_hints`
exposes. `SnakeDebugWSGI` and the Django middleware take the same `config=`. What it advises, you
declare on the model: see [Indexes and constraints](indexes-and-constraints.md).

**The nonce is for a strict CSP.** The panel is a `<template>` plus an inline `<script type="module">`.
Under `script-src 'self'` the browser blocks that script and the panel simply doesn't appear — no
server error, nothing in the page. Declare the nonce here and put the same value in your own CSP
header; the three adapters carry it into the panel's `<script>`. With no nonce the output is
unchanged.

**Per response, only under Django.** A `csp_nonce` in the config is ONE value for the whole process,
and a strict CSP wants a fresh one per response. Django is the only adapter with a request object to
ask: with [django-csp](https://django-csp.readthedocs.io/) mounted, `request.csp_nonce` is read and
**wins** over the config's — nothing to declare. WSGI and ASGI have no per-request seam for this
(neither `environ` nor `scope` carries a nonce convention), so there the config's value is the one
that ships.

## The `otel` channel: spans for a real tracer

`otel` is the only channel meant for **production**, and the only one whose reader is a tool instead
of a person. The other four hand the debug back through the response — a panel, a JSON block, a
header, a token. This one goes out sideways, over OTLP/HTTP, to infrastructure you already run.

Install the extra and point it at your collector:

```bash
pip install "snakeorm[otel]"

export SNAKE_ORM_DEBUG=otel
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_SERVICE_NAME=my-app
```

Those are the **standard** OpenTelemetry variables, not a spelling of our own: if you have configured
any other exporter, they are already set. Without them the spans go to `http://localhost:4318/v1/traces`,
which is the port a local Jaeger publishes.

The extra pulls in `opentelemetry-api` and nothing else — no SDK. It buys the one thing that cannot
be reimplemented: reading the span your application already has open, so ours hang off it. The OTLP
export itself is stdlib.

### The shape of a trace

One root span for the request, one `CLIENT` child per query, and the aggregates in both places:

| what | where it lands |
|------|----------------|
| the SQL | `db.query.text` on each child |
| the engine | `db.system.name` (`postgresql` / `mysql` / `sqlite`) |
| the table and the verb | `db.collection.name`, `db.operation.name` |
| the schema | `db.namespace` — SnakeORM emits `"public"."users"`, and the two halves stay apart |
| the span's name | `db.query.summary` — `SELECT orders`, never the whole statement |
| rows | `db.response.returned_rows` |
| the call site | `code.file.path`, `code.line.number`, `code.function.name` |
| N+1, counts, warnings, index hints | `snakeorm.*` on the ROOT, as attributes **and** as events |

A query span is named after its summary and NOT after its SQL, and that is what carries the
timeline: Jaeger renders row badges only for `http.*` tags, so a database span's row is its name and
nothing else. A span called `SELECT api_tokens` reads at a glance; one called after the whole
statement is an unreadable line. The `http.*` attributes on the ROOT do become badges — the method
and the status show up beside the request's name.

The children are what make Jaeger's **Trace Statistics** useful: group by `code.line.number` and the
line firing five hundred queries comes out with its share of the cost, in two clicks. That is the
same `(sql, origin)` grouping the panel already computes, re-derived by the backend and with the cost
split the panel does not give.

The root carries `snakeorm.has_n_plus_one`, which is searchable **between** traces: "show me every
request with an N+1" is a question neither the panel nor a single blob span can answer.

### Where the middleware goes, and the three spell it differently

Our spans hang off the application's only while its server span is still **open**. If our middleware
is the outer one, that span has already closed by the time we deliver the report, and the traces come
out detached. **Nothing fails when you get this wrong** — the spans arrive, just loose — so it is
worth checking once:

| framework | the outermost is | so OpenTelemetry goes |
|-----------|------------------|-----------------------|
| Django | the **first** entry of `MIDDLEWARE` | **above** `SnakeDebugMiddleware` |
| Flask | the **last** `app.wsgi_app = ...` assignment | **after** `SnakeDebugWSGI` |
| FastAPI | the **last** `app.add_middleware(...)` call | **after** `SnakeDebugASGI` |

Django reads the opposite way round to the other two, which is exactly why it is written down.

### What travels, and what does not

**The SQL travels; the parameters do not.** The convention collects the *parametrised* text by
default, "because parametrising is a strong signal from the user that anything sensitive is in the
values" — and SnakeORM never interpolates a value into a statement, so `db.query.text` cannot carry
user data by construction. The values are opt-in, one key at a time, and there is **no environment
variable** for them: it takes a line of code, because an environment variable is precisely the switch
somebody flips by accident.

**The export never happens on the request's thread.** Measured against localhost, exporting in line
adds ~210 ms to a request of 503 queries; on the async path that blocks the whole event loop. So the
report goes into a bounded queue and a worker posts it. A full queue drops and counts; an unreachable
collector warns **once**, naming the endpoint, and never raises into your request.

**It degrades three ways and none of them break.** With an OpenTelemetry provider active, our root
hangs off the application's span. With the library installed but no provider, and with the library
not installed at all, our root becomes the request's server span and the trace stands on its own.

## Security: never in production

Three channels **expose SQL and parameters**: `ssr`, `envelope` and `sidecar`. Even if they're in
`SNAKE_ORM_DEBUG`, in production they're **disabled**: the config says what you want, the environment
says what's allowed. In Django the gate is tied to `settings.DEBUG`; in FastAPI/Flask, to the
middleware's `production=` parameter.

**And nothing is guessed.** If one of the three is on and nothing has declared the environment, the
middleware refuses to start:

```text
SnakeConfigError: These debug channels hand the SQL to whoever asked (ssr) and nothing
declares whether this is production. Set SNAKE_ORM_PRODUCTION=true|false, or pass
production=True/False.
```

`otel` is **not** on that list, and the omission is deliberate. What makes the other three risky is
not what they carry but **who receives it**: they hand the debug back to the client through the HTTP
response — and `ssr` is the widest of them, because it paints the panel into the page with the
parameter values already substituted into the SQL. `otel` goes out sideways, to a collector the operator already runs — and production is the
only place a tracing channel is worth having. Dropping it there would be declaring it dead.
