"""INTEGRATION: `iterate()` over 150,000 rows, with memory MEASURED and not assumed.

The unit tests check that `iterate()` calls `fetch_iter` and not `fetch_all`. That verifies the
INTENTION, which is what a double can verify. The promise, however, is about memory, and memory
can only be measured.

And there is a very concrete reason not to trust it: the NAMED cursor. Without a name, psycopg2
brings the WHOLE result into client memory even if you call `fetchmany`. The code would still pass
every unit test —it calls `fetch_iter`, it asks a thousand at a time— and would not save a single
byte. The streaming would be a perfectly tested illusion.

About the instrument, which cost a failed attempt and deserves to be written down: the first
version of this file measured with `tracemalloc` and passed GREEN with the cursor sabotaged on
purpose. The thing is that `tracemalloc` counts PYTHON allocations, while the extra result psycopg2
brings over lives in C memory, where it does not reach. It measured exactly the only thing that
does not change. So here it is measured in two ways, and neither is a heuristic:

1. POSTGRES IS ASKED. A server cursor is a portal, and portals show up in `pg_cursors`. Either it
   is there or it is not; there is no room for interpretation.
2. The RESIDENT memory of the process —which does include the C buffer— is compared between walking
   and materializing. In SEPARATE processes, because `ru_maxrss` is the high-water mark of the whole
   life of the process: measuring both things in the same one would give the larger of the two,
   twice.

It skips gracefully if there is no Postgres.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_auto,
    snake_model,
    snake_str,
)
from snakeorm.migration import emit_create_table
from snakeorm.registry import registry
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

# Above the 100,000 the plan asked for, and with text on every row: with just an integer the
# saving would show less and the test would be easier than the promise deserves.
_ROWS = 150_000

# The portals opened by `fetch_iter`. The `%%` is doubled because psycopg2 reads the `%` as its
# parameter marker and, undoubled, blows up with an `IndexError` that never mentions the LIKE.
_PORTALS = "SELECT name FROM pg_cursors WHERE name LIKE 'snake_stream%%'"

# It runs in a SEPARATE process to measure its resident memory without the contamination of the
# other mode nor of pytest itself. It declares its model here because a subprocess does not inherit
# the registry.
_METER = """
import sys

from snakeorm import (PostgresDialect, PsycopgDriver, SnakeColumn, SnakeModel, SnakeQuery,
                      SnakeSession, snake_auto, snake_model, snake_str)

def resident():
    # Second field of /proc/self/statm: resident pages. It is measured INSIDE the process and by
    # DIFFERENCE, because comparing the peak of two separate processes did not come out reproducible:
    # the interpreter's floor varied between runs more than the thing being measured.
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * 4096 // 1024

@snake_model(table="it_events")
class Event(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    tag: SnakeColumn[str] = snake_str()

mode, dsn = sys.argv[1], sys.argv[2]
session = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())
before = resident()
peak = 0
rows = 0
if mode == "all":
    # The result is HELD while measuring: `len(session.all(...))` releases the list before there is
    # anything to look at, and then what gets measured is the hole it leaves, not the peak it hit.
    result = session.all(SnakeQuery(Event))
    peak = resident() - before
    rows = len(result)
else:
    limit = 10 if mode == "break" else None
    for _ in session.iterate(SnakeQuery(Event), chunk=1000):
        rows += 1
        # Sampled DURING: on leaving the loop the cursor is already closed and the buffer freed, so
        # measuring afterwards would give zero even with the streaming broken.
        if rows % 5000 == 0 or rows == limit:
            peak = max(peak, resident() - before)
        if limit is not None and rows >= limit:
            break
print(rows, peak)
"""


@snake_model(table="it_events")
class Event(SnakeModel):
    """Deliberately wide row: an `id` and a text label per event."""

    id: SnakeColumn[int] = snake_auto()
    tag: SnakeColumn[str] = snake_str()


@pytest.fixture(scope="module")
def driver() -> Iterator[PsycopgDriver]:
    """Driver against Postgres with `it_events` seeded with 150,000 rows.

    The seeding goes in ONE statement with `generate_series`: 150,000 round-trip INSERTs would take
    longer than everything this file wants to measure, and what is being tested is the READ.
    """
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    table = registry.table_of(Event)
    assert table is not None
    connection.execute("DROP TABLE IF EXISTS it_events CASCADE", ())
    connection.execute(emit_create_table(table, PostgresDialect()), ())
    connection.execute(
        "INSERT INTO it_events (tag) "
        "SELECT 'event-' || n FROM generate_series(1, %s) AS n",
        (_ROWS,),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute("DROP TABLE IF EXISTS it_events CASCADE", ())
        connection.commit()
        connection.close()


def _resident(mode: str) -> tuple[int, int]:
    """Rows read and KB of resident memory that mode ADDS, measured inside the subprocess.

    It is measured by difference and within the SAME process, not by comparing the maximum of two.
    It cost one attempt: the interpreter floor (~32-41 MB depending on the run) varied between
    processes more than what was meant to be measured, and the same sabotaged `iterate()` gave
    9,592 KB in one batch and 0 in another. An instrument that does not repeat is not an instrument.
    """
    output = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _METER, mode, dsn()],
        capture_output=True,
        text=True,
        check=True,
    )
    rows, peak = output.stdout.split()
    return int(rows), int(peak)


def test_iterate_walks_every_row(driver: PsycopgDriver) -> None:
    """Checks that the streaming delivers ALL the rows, not a chunk.

    It goes first on purpose: an `iterate()` that left half behind would spend half the memory and
    would make any measurement below pass with honours. Without this, measuring the saving is
    measuring how cheap it is to do the job badly.
    """
    session = SnakeSession(driver, PostgresDialect())

    assert sum(1 for _ in session.iterate(SnakeQuery(Event))) == _ROWS


def test_the_server_really_holds_a_cursor_while_streaming(
    driver: PsycopgDriver,
) -> None:
    """Checks, by ASKING POSTGRES, that the cursor belongs to the SERVER, not to the client.

    It is the verification that admits no interpretation: a server cursor is a portal and portals
    show up in `pg_cursors`. Without the name, psycopg2 would make a client cursor, would bring the
    150,000 rows in one go and there would be no portal here — even though the rest of the code
    looked identical.

    And it shows up ONLY while iterating: if it were still alive at the end, it would be a resource
    leak on the server, which is the price of a badly closed streaming.
    """
    session = SnakeSession(driver, PostgresDialect())
    assert driver.fetch_all(_PORTALS, ()) == []

    rows = session.iterate(SnakeQuery(Event), chunk=1000)
    next(iter(rows))
    during = driver.fetch_all(_PORTALS, ())

    assert len(during) == 1, "there is no portal open: the cursor is not the server's"


def test_iterate_uses_a_fraction_of_the_resident_memory_that_all_needs(
    driver: PsycopgDriver,
) -> None:
    """Checks BY MEASURING that walking 150,000 rows does not cost what materializing them does.

    RESIDENT memory is measured, and in a separate process per mode. Both things are necessary:
    resident because the buffer psycopg2 would bring over lives in C and `tracemalloc` does not see
    it (the first version of this test used it and passed green with the cursor sabotaged); and in
    separate processes because `ru_maxrss` is the high-water mark of the WHOLE life of the process,
    so measuring both modes in the same one would return the larger of the two, twice.

    Measured in this repo: walking the 150,000 rows costs ~676 KB and materializing them ~39,288 KB,
    some 58 times more. With the cursor sabotaged by hand —nameless, that is, client-side— the read
    climbs to ~10,064 KB and this test turns red, which is the proof that it measures something.

    The bar stays at 10x, deliberately loose: a threshold glued to the measurement turns any change
    in psycopg2 or in the interpreter into a red that points at no error at all.
    """
    rows_streaming, peak_streaming = _resident("iterate")
    rows_materialized, peak_materialized = _resident("all")

    assert rows_streaming == rows_materialized == _ROWS
    assert peak_streaming * 10 < peak_materialized, (
        f"iterate() reached {peak_streaming:,} KB resident and all() {peak_materialized:,} KB: "
        f"the streaming is not saving memory. Suspect the NAMED cursor — without it psycopg2 "
        f"fetches the whole result even when asked for it a thousand at a time."
    )


def test_breaking_early_does_not_pay_for_the_rest(driver: PsycopgDriver) -> None:
    """Checks that cutting out with `break` does not bring the 150,000 rows anyway.

    It is the other half of the promise, and the most used one: look for something and stop as soon
    as it shows up. With a disguised `fetch_all`, reading ten rows would cost exactly the same as
    reading them all, and only the memory of the process gives it away.

    Measured: ten rows cost ~480 KB against the ~39,288 KB of walking the whole thing. With the
    client cursor they climb to ~9,880 KB — you pay for the full result to look at ten rows.
    """
    rows_break, peak_break = _resident("break")
    _, peak_whole = _resident("all")

    assert rows_break == 10
    assert peak_break * 10 < peak_whole, (
        f"breaking after 10 rows reached {peak_break:,} KB y recorrerlo entero a "
        f"{peak_whole:,} KB: the break is paying for the whole result."
    )
