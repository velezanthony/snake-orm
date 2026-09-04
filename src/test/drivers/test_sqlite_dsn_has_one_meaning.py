"""One SQLite DSN names ONE database, whichever door it goes through (bug #38).

Two places stripped the `sqlite:` scheme and disagreed: `sqlite:///tmp/x.db` was `/tmp/x.db` through
`from_dsn` and `tmp/x.db` through the driver. Neither raised, because both readings open a real
database — just not the same one.

Closed along two axes: only `from_dsn` translates, and the third slash is the URL's separator (three
slashes relative, four absolute — SQLAlchemy's documented rule). A relative path is NOT resolved to
absolute: that is documented SQLite usage, and deciding what the user meant is what this ORM avoids.

Cost: this MOVES a database for anyone spelling an absolute path with three slashes.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from snakeorm import SQLiteDriver
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.drivers.asyncsqlite import AsyncSQLiteDriver


@pytest.fixture
def workspace(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """An empty directory that is also the working directory, so a relative path lands in it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _name_of(dsn: str) -> str:
    """The database name `from_dsn` gets out of a SQLite DSN."""
    return SnakeConnectionConfig.from_dsn(dsn, SnakeBackend.SQLITE).name


# -- Axis 1: what a slash means --------------------------------------------------------------------


def test_three_slashes_name_a_relative_path() -> None:
    """The third slash is the SEPARATOR, not the path. This assertion used to say `/tmp/x.db`."""
    assert _name_of("sqlite:///tmp/x.db") == "tmp/x.db"


def test_four_slashes_name_an_absolute_path() -> None:
    """The fourth slash is the one that belongs to the path."""
    assert _name_of("sqlite:////tmp/x.db") == "/tmp/x.db"


def test_an_absolute_path_pasted_into_a_dsn_arrives_intact() -> None:
    """`f"sqlite:///{path}"` with an absolute path yields the four slashes by plain concatenation."""
    assert _name_of("sqlite:////var/data/app.db") == "/var/data/app.db"


def test_the_memory_spellings_are_untouched() -> None:
    """`:memory:` arrives in the authority, where no slash rule applies."""
    assert _name_of("sqlite://:memory:") == ":memory:"
    assert _name_of("sqlite://") == ":memory:"


def test_a_uri_dsn_still_keeps_its_query_string() -> None:
    """Regression on #37: the slash rule must not drop the query a `file:` URI lives on."""
    shared = "file:probe?mode=memory&cache=shared"

    assert _name_of(f"sqlite:///{shared}") == shared


# -- Axis 2: how many places translate -------------------------------------------------------------


def test_the_driver_refuses_a_dsn_instead_of_translating_it() -> None:
    """Leaving the driver able to strip a scheme leaves the second reading, ready to disagree again."""
    with pytest.raises(SnakeConfigError, match="from_dsn"):
        SQLiteDriver.connect("sqlite:///tmp/x.db")


def test_the_complaint_names_the_scheme_it_was_given() -> None:
    """Whoever hits this passed a DSN where a path goes; the fix is one function call away."""
    with pytest.raises(SnakeConfigError) as complaint:
        SQLiteDriver.connect("sqlite:///tmp/x.db")

    message = str(complaint.value)
    assert "sqlite:///tmp/x.db" in message
    assert "SnakeConnectionConfig.from_dsn" in message


def test_the_async_driver_refuses_it_too_because_it_opens_the_same_way() -> None:
    """The async twin delegates to the sync `connect`. Asserted so a future fork goes red here."""

    async def scenario() -> None:
        with pytest.raises(SnakeConfigError, match="from_dsn"):
            await AsyncSQLiteDriver.connect("sqlite:///tmp/x.db")

    asyncio.run(scenario())


def test_a_plain_path_is_still_just_a_path() -> None:
    """The half that must NOT move: without a scheme, nothing is inspected."""
    assert isinstance(SQLiteDriver.connect(":memory:"), SQLiteDriver)


def test_a_filename_that_merely_starts_with_the_word_sqlite_is_not_a_dsn(
    workspace: pathlib.Path,
) -> None:
    """The refusal keys on the SCHEME: `startswith("sqlite")` would reject an ordinary filename."""
    driver = SQLiteDriver.connect("sqlite_backup.db")
    driver.close()

    assert sorted(entry.name for entry in workspace.iterdir()) == ["sqlite_backup.db"]


# -- The two ends together -------------------------------------------------------------------------


def test_the_config_and_the_driver_open_THE_SAME_database(
    workspace: pathlib.Path,
) -> None:
    """The assertion neither end can make alone: each was self-consistent while they disagreed.

    Only looking at what appeared ON DISK says the user got the database they asked for. Under the
    old reading the driver got `/here.db` and this directory stayed empty.
    """
    config = SnakeConnectionConfig.from_dsn("sqlite:///here.db", SnakeBackend.SQLITE)
    assert config.name == "here.db"

    driver, _dialect = config.driver_and_dialect()
    try:
        driver.execute("CREATE TABLE probe (n INTEGER)", ())
        driver.commit()
    finally:
        driver.close()

    assert sorted(entry.name for entry in workspace.iterdir()) == ["here.db"]
