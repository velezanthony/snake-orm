"""One `CsvExport` turned into a Flask response that WRITES AS IT READS, and never before.

`shared/viewmodels` hands the web layer a `CsvExport` whose `rows` is a generator over
`session.iterate()`: nothing has been executed when it arrives, and the statement is fed a row at a
time by the cursor. Everything in this module exists to keep that true across the one boundary the
shared tests cannot see. They watch the VIEW MODEL — `shared/tests/test_exports_stream.py` proves
that reading 3 rows out of 30 makes the driver consume exactly 3 — and a `list()` written in a route
would leave every one of those assertions green while the page went back to holding the whole table
in memory before writing its first byte. So the response is built here, once, for both domains that
have an export.

ONE module for the two and not a copy in each, which is the opposite of the call the view models
make (they stay two code paths over two tables on purpose). The difference is that this file holds no
domain knowledge at all: it is the WSGI mechanics of streaming, and those mechanics have exactly two
subtleties, both of which are silent when got wrong.

**THE SESSION HAS TO CHANGE HANDS, and `stream_with_context` is NOT what does it.** [measured] The
request's session is opened by a `before_app_request` hook and closed by `teardown_app_request`, and
Flask pops the request context —which is what runs teardown— as soon as `wsgi_app` has the response
object. A streamed body is produced after that, so a bare generator gets asked for its first row by a
cursor whose session has already been closed and whose connection has already gone back to the pool.
The obvious fix is the documented one, and on Flask 3.1 it does not work: `stream_with_context`
pushes the contexts LAZILY —its generator yields a sentinel first and only enters `with app_ctx,
req_ctx:` when the body is actually pulled— so teardown has already run by then. It was tried here
and the export died with `psycopg2.InterfaceError: connection already closed`, which is the same
error you get with no wrapper at all. What it restores is `g` and `request`; what it cannot restore
is a session somebody else has closed.

So the session is TAKEN OFF the request instead. `g.pop("session")` leaves the teardown hook with
nothing to close —it already reads `g.pop("session", None)`— and hands ownership to the stream, which
closes it on the way out. That is deliberate and it is why this helper does the popping rather than
taking a session as an argument: a caller who passed `g.session` without popping it would rebuild the
exact bug, and there would be nothing to notice until a download died.

**The closing is written TWICE, and both are needed.** A streamed body ends two ways and different
machinery runs for each. Consumed to the end, the generator's own `finally` fires. Closed early —a
cancelled download, a client that hung up— the WSGI server calls `close()` on the response, which is
what `call_on_close` is for, and a generator that was never started runs no `finally` at all. Both
paths are covered because `close()` on a pooled driver is idempotent by contract ("returning it twice
would hand it to two users at once"). And the belt matters as much as the braces here:
`SnakeDebugWSGI` consumes the body with `b"".join(...)` and never calls `close()` on it, so under the
demo's own debug middleware the `call_on_close` half never fires.

**NOTHING IS ACCUMULATED, including by the writer.** `csv.writer` wants a file-like object, and the
obvious `io.StringIO` grows without bound because nothing ever empties it. `_Echo` is the standard
answer: a `write` that returns its argument instead of storing it turns `writerow` into "format this
one row and give it back", so the peak memory of an export is one row, whatever the table holds.
Quoting and escaping still come from `csv`, which is the point of not formatting the line by hand — a
SKU called `Bolt, 3"` is a real name and a naive `",".join` writes a broken file for it.

One thing this module cannot do anything about, and it is worth writing down rather than
rediscovering: that same buffering in `SnakeDebugWSGI` means the bytes reach the client in one piece
however carefully they were produced, for as long as the panel is on. What survives is the shape of
the EXECUTION — the database is still read a row at a time — and with the panel off the path is lazy
end to end. The test that guards the streaming calls the view below the middleware for exactly that
reason.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator

from flask import Response, g

from snakeorm import SnakeSession

from shared.viewmodels.inventory_viewmodels import CsvExport


class _Echo:
    """A file-like object whose `write` hands the text straight back instead of keeping it.

    This is what makes `csv.writer` a FORMATTER rather than a buffer: `writerow` returns whatever
    `write` returned, so one call becomes one finished line and nothing is retained between calls.
    """

    def write(self, value: str) -> str:
        """Return the line the writer just formatted, storing nothing."""
        return value


def _csv_lines(export: CsvExport, session: SnakeSession) -> Iterator[str]:
    """The header, then the rows, each one formatted as it arrives from the cursor.

    The header goes out FIRST and before the row generator is touched, which is what lets a client
    start parsing while the database is still reading — and what makes an export of a table nobody
    has written to a valid CSV with one line in it rather than an empty download.

    The `finally` closes the stream BEFORE the session, and the order is the point: closing the row
    generator is what tears down the server-side cursor and lets the driver record the statement,
    while closing the session hands the connection back. Doing it the other way round would return a
    connection that still has an open cursor on it.
    """
    writer = csv.writer(_Echo())
    try:
        yield writer.writerow(export.header)
        for row in export.rows:
            yield writer.writerow(row)
    finally:
        export.rows.close()
        session.close()


def csv_response(export: CsvExport) -> Response:
    """A `CsvExport` as a downloadable, STREAMED `text/csv` response. IT TAKES THE SESSION WITH IT.

    Calling this ENDS the request's ownership of `g.session`: the session is popped, so the teardown
    hook finds nothing to close, and the stream closes it when the download finishes or is abandoned.
    Nothing may touch the session after this call — which is why the two views that use it call it
    last, on the `return` line, with the export already built.

    `Content-Disposition` carries the filename the view model chose rather than one invented here:
    the layer that knows what the rows are is the layer that knows what to call the file, and a name
    written into a route would be a second answer that drifts from the first.

    There is deliberately no `Content-Length`. It could only be computed by generating the whole file
    first, which is the one thing this response exists not to do — so the body goes out chunked and
    the browser shows a download of unknown size instead of a page that hangs while the server counts.
    """
    session: SnakeSession = g.pop("session")
    response = Response(
        _csv_lines(export, session),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
        },
    )
    response.call_on_close(session.close)
    return response
