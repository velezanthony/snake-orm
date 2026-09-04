"""The traffic export, and the TWO economies it is made of — which are easy to mistake for one.

`visits` is the volume table: millions of rows at the seeded scales, carrying a `user_agent` that no
column of this file prints. Exporting it needs both halves and neither does the other's job:

- `iterate()` keeps the row COUNT out of memory. A million visits never exist as a million objects,
  and the first byte goes out before the query has finished;
- `only()` keeps the row WIDTH off the wire. A browser string is around a hundred bytes, so over ten
  million rows it is a gigabyte read off the disk, pushed through the socket and decoded into Python
  in order to be discarded.

BOTH ARE INVISIBLE IN THE ANSWER, which is why they get a file. A view model that walked the stream
into a list, or a query that brought whole rows, would write the same bytes in the same order and
every assertion about CONTENT would pass. So the content half here is the small half; the load-bearing
assertions are the SHAPE of the SQL and the shape of the execution.

AND THE NARROWING IS ENFORCED BY THE ORM RATHER THAN BY THIS FILE. A column left out carries a
sentinel and RAISES when read — it does not come back as `None` — so the day the header grows a fifth
name the writer fails loudly instead of filling a file with empty strings. That refusal is asserted
here because it is the reason `only()` is safe to use on a page at all.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator

import pytest
from snakeorm import SnakeSession, SnakeUtc
from snakeorm.core.exceptions import SnakeColumnNotLoaded
from snakeorm.debug import capture_queries

from shared.models import Post, Visit
from shared.selectors import engagement_selectors as selectors
from shared.usecases import engagement_usecases as usecases
from shared.viewmodels import engagement_viewmodels as viewmodels


def _visits(session: SnakeSession, post_id: int, how_many: int) -> None:
    """Rows on the volume table, each one carrying the wide column the file does not print."""
    for index in range(how_many):
        session.add(
            Visit(
                post_id=post_id,
                ip=f"10.0.0.{index + 1}",
                user_agent="Mozilla/5.0 (a browser string nobody prints)",
                visited_at=SnakeUtc.now(),
            )
        )
    session.commit()


def _a_post(session: SnakeSession) -> int:
    """The id of a seeded post, to hang the visits off."""
    from snakeorm import SnakeQuery

    return session.all(SnakeQuery(Post).limit(1))[0].id


def test_the_query_names_the_columns_the_file_has_and_no_others(
    session: SnakeSession,
) -> None:
    """The SELECT is three columns plus the key, and the browser string is not among them."""
    sql, _ = selectors.visits_to_export(1).to_sql(session.dialect)

    assert "user_agent" not in sql
    assert '"ip"' in sql and '"visited_at"' in sql and '"post_id"' in sql
    # The primary key comes back whether it was named or not: an instance with no identity could not
    # be matched, refreshed or written back, so it is not something `only()` is allowed to drop.
    assert '"id"' in sql


def test_reading_the_column_that_was_left_out_raises(seeded: SnakeSession) -> None:
    """THE REASON `only()` IS SAFE HERE. A deferred name is not `None`; it is a refusal.

    Without the sentinel the descriptor would fall through to the column's default and the writer
    would put empty strings in a file nobody would ever question. A wrong answer with no error is
    the one outcome this ORM does not produce.
    """
    post_id = _a_post(seeded)
    _visits(seeded, post_id, 2)

    # The LAST of the stream: the seeder has already spread visits over the history and the export is
    # ordered oldest first, so the two written here are the two at the end. Taking the first would be
    # asserting about a row this test did not write.
    last = list(usecases.stream_visits(seeded, post_id=post_id))[-1]

    assert last.ip == "10.0.0.2"
    with pytest.raises(SnakeColumnNotLoaded, match="user_agent"):
        last.user_agent


def test_the_export_hands_back_a_generator_and_has_run_nothing(
    seeded: SnakeSession,
) -> None:
    """Built, not executed: nothing has reached the database when the export is returned.

    The type-level half proves little on its own —`iter(list(...))` is a generator too— but zero
    statements after building cannot be faked by a list: a view model that had materialised would
    already have fired its SELECT by the time it returned.
    """
    post_id = _a_post(seeded)
    _visits(seeded, post_id, 5)

    with capture_queries() as collector:
        export = viewmodels.visits_export(seeded, post_id=post_id)

    assert isinstance(export.rows, Generator)
    assert inspect.isgenerator(export.rows)
    assert list(collector.report().records) == []


def test_consuming_three_rows_reads_three(seeded: SnakeSession) -> None:
    """THE ASSERTION THE FEATURE EXISTS FOR, and the only one a materialising export fails.

    `CaptureDriver` notes a streamed statement when the cursor is done and records how many rows were
    CONSUMED. A view model that built a list would have consumed all thirty to do it, so the number
    in the record is the difference between the two implementations, measured from outside.
    """
    post_id = _a_post(seeded)
    _visits(seeded, post_id, 30)
    export = viewmodels.visits_export(seeded, post_id=post_id)

    with capture_queries() as collector:
        taken = [next(export.rows) for _ in range(3)]
        export.rows.close()

    assert len(taken) == 3
    streamed = [
        record for record in collector.report().records if "visits" in record.sql
    ]
    assert [record.rows for record in streamed] == [3]


def test_the_header_names_exactly_what_a_row_carries(seeded: SnakeSession) -> None:
    """Four columns in the header and four cells in a row: the file cannot go out of step with itself.

    It is the pair that decides what the query may leave behind, so a fifth column added to one and
    not the other is either a header naming nothing or a value with no name over it.
    """
    post_id = _a_post(seeded)
    _visits(seeded, post_id, 1)
    export = viewmodels.visits_export(seeded, post_id=post_id)

    row = next(export.rows)
    export.rows.close()

    assert len(row) == len(viewmodels.VISIT_EXPORT_HEADER)
    assert row[1] == str(post_id)


def test_the_filter_narrows_the_query_and_not_the_writer(seeded: SnakeSession) -> None:
    """`post_id` reaches the WHERE. Filtering while writing would read every visit to discard most."""
    post_id = _a_post(seeded)
    _visits(seeded, post_id, 3)

    sql, params = selectors.visits_to_export(post_id).to_sql(seeded.dialect)

    assert "WHERE" in sql
    assert post_id in params


def test_the_export_is_bounded_by_nothing(session: SnakeSession) -> None:
    """No `LIMIT`, deliberately: a bounded export is a page of results wearing a download's name.

    It is also what keeps the two tests above honest — over a bounded query they would pass without
    the export ever having had to stream.
    """
    sql, _ = selectors.visits_to_export().to_sql(session.dialect)

    assert "LIMIT" not in sql
