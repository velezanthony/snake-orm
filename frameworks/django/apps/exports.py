"""The CSV download, written ONCE for every domain that has an export. It streams, and it has to.

`shared/viewmodels` hands the web layer a `CsvExport` whose `rows` is a GENERATOR over
`session.iterate()` — a read that walks a result without ever holding it whole. That is the entire
subject of the `export` page in the plan's taxonomy, and it is the one property of a read that is
invisible in the answer: a handler that did `list(export.rows)` would send the same bytes, in the
same order, and would have thrown away the only thing the page was for. Every content assertion
would still pass. So this module exists to make the streaming path the easy one — the two export
views call it and neither gets a chance to write the `list()`.

**THE SESSION IS OURS AND NOT THE REQUEST'S, and that is the whole design of this file.**
`apps.blog.middleware.SnakeSessionMiddleware` commits and CLOSES `request.snake_session` in a
`finally` as soon as the view returns. A streaming body is produced AFTER that: WSGI pulls
`streaming_content` once the middleware chain has unwound, so the first row of the export would be
asked for from a session that was closed several frames ago. That is the classic failure of a
streamed export, and it does not show up until the data is big enough for laziness to matter —
`list()` in the view hides it, which is exactly why `list()` is so tempting.

So the export opens its OWN session, from the same `settings.DATABASES` the middleware reads, and
the generator below owns its lifetime: the session is closed in a `finally` that runs whether the
download finished or the browser walked away half way through. `CsvExport.rows` is typed a
`Generator` and not an `Iterator` for that second case specifically — an abandoned download has to
be able to tear the cursor down, and only a generator can be told to.

`django_session` is imported straight from the ORM's Django adapter rather than through some layer
of ours, because that is what it is: the piece that turns Django's native config into a session, and
the middleware next door reaches for the same function. A second wrapper would be a second answer to
"how does this demo open a session".
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Generator

from django.http import StreamingHttpResponse

from snakeorm import SnakeSession
from snakeorm.contrib.django import django_session

from shared.viewmodels.inventory_viewmodels import CsvExport


class _Echo:
    """A file-like object that writes nowhere and hands the line back instead.

    `csv.writer` is the only thing in the standard library that knows how a value has to be quoted,
    escaped and terminated, and it insists on writing to a file. Giving it one whose `write` RETURNS
    the line turns `writerow` into "format this row as CSV text" — which is the documented way of
    building a streamed CSV in Django, and the alternative is hand-rolling the quoting rules for
    every column that might contain a comma, a quote or a newline. A SKU called `Widget, 3"` is not
    a hypothetical; it is a row a person typed into the create form.
    """

    def write(self, value: str) -> str:
        """Returns the line rather than storing it: the caller is the one who does something with it."""
        return value


def _stream(export: CsvExport, session: SnakeSession) -> Generator[str, None, None]:
    """The header, then the rows AS THEY ARRIVE, and then the session goes back whatever happened.

    The `finally` is the contract of this module and it has two jobs, not one. Closing the generator
    tears down the cursor when a browser abandons the download half way — Django closes the response,
    Python throws `GeneratorExit` in here, and the connection is not left holding a result set until
    the garbage collector gets round to it. Closing the session hands the connection back, which is
    the half nothing else in this demo does for us: this session is not the request's, so no
    middleware is going to close it.

    The header goes out before the first row is asked for, which is what makes a download of a
    million rows start instantly instead of after the query finishes. That is also why `CsvExport`
    keeps it separate from the rows rather than yielding it as the first of them.
    """
    writer = csv.writer(_Echo())
    try:
        yield writer.writerow(export.header)
        for row in export.rows:
            yield writer.writerow(row)
    finally:
        export.rows.close()
        session.close()


def csv_download(build: Callable[[SnakeSession], CsvExport]) -> StreamingHttpResponse:
    """A `CsvExport` as a streamed download, over a session that lives as long as the body does.

    It takes a FUNCTION and not an export, because the session has to exist before the export can be
    built and has to be handed to the generator afterwards; a caller passing an export would have to
    own that session itself, in every view, which is the duplication this module removes.

    The build runs eagerly, here, and that is deliberate: `iterate` refuses a query it cannot stream
    — a to-many `include`, for one — and the refusal has to land on the view that made the mistake,
    with a 500 and a traceback, rather than three lines into a response whose status has already
    been sent as 200. If it does raise, the session is closed on the way out; nothing else would.
    """
    session = django_session()
    try:
        export = build(session)
    except Exception:
        session.close()
        raise
    response = StreamingHttpResponse(
        _stream(export, session), content_type="text/csv; charset=utf-8"
    )
    # `attachment` and the name the view model chose. The name lives in `shared` on purpose: a file
    # called `export.csv` in one demo and `stock.csv` in another is the drift the whole shared layer
    # was added to stop, one storey down.
    response["Content-Disposition"] = f'attachment; filename="{export.filename}"'
    return response
