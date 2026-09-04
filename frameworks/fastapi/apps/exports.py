"""One streamed CSV, written as it is read, for the ASGI demo. The asynchronous half of the pair.

`django/apps/exports.py` and `flask/apps/exports.py` do this for the two synchronous demos and argue
the mechanics at length; everything they say about `_Echo` and about the session outliving the
handler holds here word for word. What is different is the COLOUR, and the difference is not
cosmetic: the rows arrive from an `async for` over `AsyncSession.iterate()`, so the body is an async
generator and the container the other two pass around — `CsvExport`, whose `rows` is a synchronous
`Generator` — cannot hold it.

So this module takes the header, the filename and the row stream as three arguments rather than one
object. The header and the filename still come from `shared/viewmodels/engagement_viewmodels.py`,
which is the half that must not differ between the three demos; what is local is only the plumbing.

THE SESSION IS NOT THE REQUEST'S, for the same reason it is not in the other two demos and one more
of its own. A `StreamingResponse` body is pulled by the server after the endpoint has returned, and
`get_session` closes the pooled connection in its `finally` — so a generator reading from it would be
asking a connection that has already gone back to the pool, and worse, one that may already have been
handed to another task. The caller opens a session of its own and this module closes it, whether the
download finished or the client walked away.

THE ROWS ARE TYPED AN `AsyncGenerator` AND NOT AN `AsyncIterator`, and the difference is `aclose`.
A download the browser abandons half way has to be able to tear the cursor down, and a plain async
iterator has no way to say so — the connection would stay held until the object was collected. It is
the same call `CsvExport.rows` makes on the synchronous side, for the same reason and in the same
words: typing the field as what it really IS is what lets the `finally` below close it.

NOTHING IS ACCUMULATED. `csv.writer` insists on a file-like object and the obvious `io.StringIO`
grows without bound; `_Echo` returns each formatted line instead of storing it, so the peak memory of
an export is one row whatever the table holds. Quoting and escaping still come from `csv`, which is
the point of not joining commas by hand.
"""

from __future__ import annotations

import csv
from collections.abc import AsyncGenerator, AsyncIterator

from fastapi.responses import StreamingResponse

from snakeorm import AsyncSession


class _Echo:
    """A file-like object whose `write` hands the text straight back instead of keeping it."""

    def write(self, value: str) -> str:
        """Return the line the writer just formatted, storing nothing."""
        return value


async def _lines(
    session: AsyncSession,
    header: tuple[str, ...],
    rows: AsyncGenerator[tuple[str, ...], None],
) -> AsyncIterator[str]:
    """The header, then the rows AS THEY ARRIVE, and then the connection goes back regardless.

    The header goes out before the first row is asked for, which is what makes a download of a
    million rows start instantly instead of after the query has finished. The `finally` closes the
    row stream before the session, and the order is the point: closing the stream tears the cursor
    down, closing the session hands the connection back, and doing it the other way round would
    return a connection with an open cursor on it.
    """
    writer = csv.writer(_Echo())
    try:
        yield writer.writerow(header)
        async for row in rows:
            yield writer.writerow(row)
    finally:
        await rows.aclose()
        await session.close()


def csv_download(
    session: AsyncSession,
    *,
    filename: str,
    header: tuple[str, ...],
    rows: AsyncGenerator[tuple[str, ...], None],
) -> StreamingResponse:
    """A streamed `text/csv` download that owns `session` until the body ends.

    There is deliberately no `Content-Length`: it could only be computed by generating the whole file
    first, which is the one thing this response exists not to do.
    """
    return StreamingResponse(
        _lines(session, header, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
