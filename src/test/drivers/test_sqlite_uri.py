"""A `file:` DSN is opened as a URI, and an ordinary path is still an ordinary path.

`sqlite3.connect` only reads a connection string as a URI when it is passed `uri=True`, and this
driver did not pass it. So `file:cache?mode=memory&cache=shared` — the standard spelling of a shared
in-memory database — was taken as a FILENAME, and SQLite created a file called exactly that,
question mark and ampersands included. It did not fail: it opened the WRONG database and carried on,
which is the worst way for this to go wrong, and the reason it went unnoticed is that everything
downstream works — it is a real database, just not the one that was asked for.

It escaped as far as a commit. `src/test/drivers/test_pool_returns_a_clean_connection.py` asked for
a shared in-memory database, got an 8 KB file in the repository root, and nothing anywhere said so.
The first test below is the assertion that was missing: with a URI in memory, NO FILE MAY APPEAR.

MEASURED before changing anything, because the reasonable fear is that `uri=True` breaks ordinary
paths. It does not. SQLite reads the string as a URI only if it begins with `file:`; anything else
is a literal filename, `?` and all — checked here with `weird?name.db`, which still becomes a file
with a question mark in its name. So the fix is unconditional: no flag, no heuristic, no guessing
about what the caller meant.

What DOES change, and is written down rather than discovered later: a malformed `file:` DSN now
RAISES instead of quietly creating a file named after the mistake. That is the point.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from snakeorm import SQLiteDriver
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.drivers.asyncsqlite import AsyncSQLiteDriver

_SHARED = "file:snakeorm_uri_probe?mode=memory&cache=shared"


@pytest.fixture
def workspace(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """An empty directory that is also the working directory, so a relative path lands in it.

    Both halves matter: the tests below assert on what the directory CONTAINS, and a driver that
    wrote its stray file into the repository root instead would leave this one empty and pass.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _written(directory: pathlib.Path) -> list[str]:
    """The names of the files sitting in the directory, sorted."""
    return sorted(entry.name for entry in directory.iterdir())


def test_a_uri_in_memory_dsn_writes_no_file_at_all(workspace: pathlib.Path) -> None:
    """THE assertion that was missing. A database in memory must leave nothing behind.

    Not "the file has the right name" — no file. Checking the name would have passed on the broken
    driver too, because the name it wrote was exactly the DSN.
    """
    driver = SQLiteDriver.connect(_SHARED)
    driver.execute("CREATE TABLE probe (n INTEGER)", ())
    driver.commit()
    driver.close()

    assert _written(workspace) == [], (
        "a database asked for IN MEMORY left a file behind: the DSN was read as a filename"
    )


def test_two_connections_to_the_same_uri_share_the_database(
    workspace: pathlib.Path,
) -> None:
    """What the URI BUYS, and not just what it stops doing.

    `cache=shared` is the whole reason to spell a DSN this way: two connections to the same name are
    the same database. On the broken driver they were two connections to one FILE, which shares data
    too — so the file test above proves the bug is gone and this one proves the feature arrived.
    """
    first = SQLiteDriver.connect(_SHARED)
    first.execute("CREATE TABLE shared_probe (n INTEGER)", ())
    first.execute("INSERT INTO shared_probe VALUES (7)", ())
    first.commit()

    second = SQLiteDriver.connect(_SHARED)
    try:
        assert second.fetch_all("SELECT n FROM shared_probe", ()) == [(7,)]
    finally:
        second.close()
        first.close()
    assert _written(workspace) == []


def test_an_ordinary_path_is_still_an_ordinary_path(workspace: pathlib.Path) -> None:
    """The half that must NOT move: a relative path still becomes that file."""
    driver = SQLiteDriver.connect("plain.db")
    driver.execute("CREATE TABLE probe (n INTEGER)", ())
    driver.commit()
    driver.close()

    assert _written(workspace) == ["plain.db"]


def test_a_path_with_a_question_mark_is_not_mistaken_for_a_uri(
    workspace: pathlib.Path,
) -> None:
    """The case that decides whether the fix can be unconditional, and it says it can.

    A filename with a `?` in it looks like a URI to a person and is not one to SQLite: the rule is
    the `file:` prefix and nothing else. If this were mistaken for a URI, the fix would need a flag
    or a heuristic about what the caller meant, and both are how a connection string ends up with
    two meanings.
    """
    driver = SQLiteDriver.connect("weird?name.db")
    driver.execute("CREATE TABLE probe (n INTEGER)", ())
    driver.commit()
    driver.close()

    assert _written(workspace) == ["weird?name.db"]


def test_memory_still_means_memory(workspace: pathlib.Path) -> None:
    """`:memory:` is not a URI and never was: it keeps working and writes nothing."""
    driver = SQLiteDriver.connect(":memory:")
    driver.execute("CREATE TABLE probe (n INTEGER)", ())
    driver.commit()
    driver.close()

    assert _written(workspace) == []


def test_the_driver_refuses_the_scheme_instead_of_stripping_it(
    workspace: pathlib.Path,
) -> None:
    """THE SAME TEST, INVERTED. It asserted that the driver stripped the prefix "for convenience",
    and that convenience WAS bug #38 — a second place translating a DSN, disagreeing in silence.

    The property it protected moved to the one door; see `test_sqlite_dsn_has_one_meaning.py`.
    """
    with pytest.raises(SnakeConfigError, match="from_dsn"):
        SQLiteDriver.connect(f"sqlite:///{_SHARED}")

    assert _written(workspace) == []


def test_the_async_driver_gets_the_same_fix_because_it_opens_the_same_way(
    workspace: pathlib.Path,
) -> None:
    """The asynchronous twin, which is where half a fix would have shown up.

    `AsyncSQLiteDriver.connect` delegates to the synchronous `SQLiteDriver.connect` inside the
    adapter's thread rather than calling `sqlite3.connect` itself, so there is ONE place where a
    connection is opened and one place to fix. That is a property worth asserting rather than
    reading: the day somebody gives the async driver its own `connect`, this goes red instead of
    the bug coming back on one colour only.
    """

    async def scenario() -> None:
        driver = await AsyncSQLiteDriver.connect(_SHARED)
        await driver.execute("CREATE TABLE async_probe (n INTEGER)", ())
        await driver.commit()
        await driver.close()

    asyncio.run(scenario())

    assert _written(workspace) == []


def test_a_malformed_uri_now_raises_instead_of_writing_its_own_name(
    workspace: pathlib.Path,
) -> None:
    """The behaviour that CHANGES, asserted so it is a decision and not a surprise.

    `file:y?mode=nonsense` used to produce a file called `file:y?mode=nonsense` and no complaint.
    Now SQLite reads it, does not recognise the access mode and says so. Louder is the whole point:
    the old outcome was a working connection to a database nobody meant to open.

    An UNKNOWN parameter is a different case and is not asserted as an error, because SQLite ignores
    it — `file:x?bogus=1` opens `x`. That is the engine's rule, not this driver's, and pinning it
    down here would be this repository asserting somebody else's behaviour it does not control.
    """
    import sqlite3

    with pytest.raises(sqlite3.OperationalError, match="access mode"):
        SQLiteDriver.connect("file:broken?mode=nonsense")

    assert _written(workspace) == []


# -- The other end: the DSN that arrives in an environment variable ------------------------------


def test_the_connection_config_keeps_the_uris_query_string() -> None:
    """`SnakeConnectionConfig.from_dsn` must not drop what makes a URI a URI.

    THE SAME BUG AT THE OTHER END, and it survived the driver's fix. `from_dsn` takes the DSN apart
    with `urlsplit` and rebuilt the database name out of `netloc` and `path` alone — so
    `sqlite:///file:cache?mode=memory&cache=shared` arrived at the driver as `/file:cache`, with the
    query GONE and a leading slash where the scheme used to be. That is not a URI any more, so the
    driver reads it as a filename and tries to create `/file:cache` at the root of the filesystem.

    Two ends have to agree here and only one of them was fixed by passing `uri=True`. This is the
    path `snake_session(...)` and every `SNAKEORM_DSN_*` variable travel down, which is the one a
    user is most likely to write a URI into — it is the only place a connection is spelled as a
    single string.

    THE SCHEME IS REQUIRED, and it is checked here rather than left to be rediscovered: a bare
    `file:cache?mode=memory` never reaches this branch at all, because `backend_name_for` splits the
    DSN on `://` and a string without one falls through to Postgres. So `sqlite:///file:...` is not
    one of two spellings — it is the spelling.
    """
    config = SnakeConnectionConfig.from_dsn(f"sqlite:///{_SHARED}", SnakeBackend.SQLITE)

    assert config.name == _SHARED


def test_a_path_dsn_counts_its_slashes() -> None:
    """The half that DID move, and this docstring was what defended the bug: it claimed the leading
    slash was "part of the PATH". It is the URL's separator. Three slashes relative, four absolute.
    """
    assert (
        SnakeConnectionConfig.from_dsn("sqlite:///tmp/x.db", SnakeBackend.SQLITE).name
        == "tmp/x.db"
    )
    assert (
        SnakeConnectionConfig.from_dsn("sqlite:////tmp/x.db", SnakeBackend.SQLITE).name
        == "/tmp/x.db"
    )
    assert (
        SnakeConnectionConfig.from_dsn("sqlite://:memory:", SnakeBackend.SQLITE).name
        == ":memory:"
    )


def test_the_config_opens_a_shared_memory_database_end_to_end(
    workspace: pathlib.Path,
) -> None:
    """The two ends together: a URI DSN in, a shared in-memory database out, no file written.

    The assertion the two above cannot make on their own. `from_dsn` could keep the string intact
    and the driver could still read it as a filename, or the other way round; only running the pair
    says the connection a user actually gets is the one they asked for.
    """
    config = SnakeConnectionConfig.from_dsn(f"sqlite:///{_SHARED}", SnakeBackend.SQLITE)
    driver, dialect = config.driver_and_dialect()
    try:
        driver.execute("CREATE TABLE config_probe (n INTEGER)", ())
        driver.commit()
    finally:
        driver.close()

    assert type(dialect).__name__ == "SQLiteDialect"
    assert _written(workspace) == []
