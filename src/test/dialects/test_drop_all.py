"""Emptying a schema is an EMISSION of the dialect, like every other piece of DDL.

`fresh` wiped with `DROP TABLE ... CASCADE`, which is Postgres syntax and only Postgres syntax.
SQLite rejects the keyword outright, and MySQL refuses to drop a table another one still references.
So the one DESTRUCTIVE command in the CLI was the one that would fail halfway on two of the three
engines — the worst possible moment to discover a portability problem.

The keyword was never the interesting part. What each engine needs is a way to stop the foreign keys
from objecting while the tables come down, and each has its own: Postgres cascades per statement,
MySQL has a session switch, SQLite has a pragma. That is three answers to one question, which is
exactly what a dialect is for.

It goes in the Protocol rather than in a helper, so a fourth engine cannot be added without
answering it — the same reason `Cap` blows up at import time when a capability is left out.

SQLite's answer NAMED THE WRONG PRAGMA, and the tests below are the measurement. `PRAGMA
foreign_keys = OFF` does nothing inside a transaction, and `SQLiteDriver` opens one before the first
statement, so the two lines that bracketed the drops were dead weight claiming to be the thing that
made them work. What actually made them work was the ORDER the caller happened to pass, and the
caller derived it from how somebody had declared their models.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import pytest

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect, SnakeDialect
from snakeorm.drivers.sqlite import SQLiteDriver

_DIALECTS = (PostgresDialect(), MySQLDialect(), SQLiteDialect())

_PARENT = "drop_all_parent"
_CHILD = "drop_all_child"


def _seeded_sqlite() -> SQLiteDriver:
    """A live SQLite holding a referenced table and a referencing one, one row each.

    Through the project's OWN driver and not a bare `sqlite3` connection, because the two behave
    differently in exactly the way this file is about: `SQLiteDriver` arms the foreign keys at
    connect and opens a transaction before the first statement.
    """
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(f"CREATE TABLE {_PARENT} (id INTEGER PRIMARY KEY)", ())
    driver.execute(
        f"CREATE TABLE {_CHILD} (id INTEGER PRIMARY KEY, "
        f"parent_id INTEGER REFERENCES {_PARENT}(id))",
        (),
    )
    driver.execute(f"INSERT INTO {_PARENT} (id) VALUES (1)", ())
    driver.execute(f"INSERT INTO {_CHILD} (id, parent_id) VALUES (1, 1)", ())
    driver.commit()
    return driver


def _run(driver: SQLiteDriver, statements: Sequence[str]) -> None:
    """Runs a `drop_all_sql` batch the way the CLI does: one transaction, then a commit."""
    for statement in statements:
        driver.execute(statement, ())
    driver.commit()


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
def test_every_dialect_answers_how_to_empty_a_schema(dialect: SnakeDialect) -> None:
    """All three implement `drop_all_sql`, and all three quote the names they were given."""
    statements = dialect.drop_all_sql(("users", "posts"))

    assert statements, f"{type(dialect).__name__} returned nothing to run"
    joined = " ".join(statements)
    assert dialect.quote_ident("users") in joined
    assert dialect.quote_ident("posts") in joined


def test_sqlite_does_not_emit_the_cascade_it_cannot_parse() -> None:
    """SQLite gets no `CASCADE`: it is a syntax error there, verified against the engine itself."""
    statements = SQLiteDialect().drop_all_sql(("users",))

    assert not any("CASCADE" in statement for statement in statements)
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    for statement in statements:
        connection.execute(statement)  # it runs, which is the whole assertion
    remaining = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert remaining == []


def test_mysql_switches_the_foreign_keys_off_and_back_on() -> None:
    """MySQL cannot drop a referenced table, so the switch brackets the drops — and is restored.

    Leaving it off would hand back a session that silently accepts orphan rows, which is a worse
    state than the one the command was fixing.
    """
    statements = MySQLDialect().drop_all_sql(("users",))

    assert "FOREIGN_KEY_CHECKS=0" in statements[0].replace(" ", "")
    assert "FOREIGN_KEY_CHECKS=1" in statements[-1].replace(" ", "")


def test_sqlite_never_emits_the_pragma_its_own_driver_turns_into_a_no_op() -> None:
    """`PRAGMA foreign_keys = OFF` is measured inert here, so the dialect must not pretend with it.

    SQLite documents the pragma as a no-op inside a transaction, and `SQLiteDriver._ensure_tx` opens
    one before every statement that goes through the Protocol. The first half of this test is the
    measurement, not a quotation of the manual: the pragma is sent and the value still reads 1.

    A statement that does nothing is not free. It was the thing the docstring said made the drops
    work, so the real reason they worked went unwritten and unprotected.
    """
    driver = SQLiteDriver.connect(":memory:")
    try:
        driver.execute("PRAGMA foreign_keys = OFF", ())
        assert driver.fetch_all("PRAGMA foreign_keys", ())[0][0] == 1
    finally:
        driver.close()

    statements = SQLiteDialect().drop_all_sql(("users",))
    assert not any("PRAGMA foreign_keys" in statement for statement in statements)


def test_sqlite_drops_a_referenced_table_before_the_one_pointing_at_it() -> None:
    """The worst order still empties the schema: `drop_all_sql` owes order-independence.

    The referenced table goes FIRST here, which is the order that fails without help. Postgres
    (CASCADE) and MySQL (the session switch) already survive it — measured against both servers —
    and the Protocol promises the same from every dialect, so SQLite owes it too.
    """
    driver = _seeded_sqlite()
    try:
        _run(driver, SQLiteDialect().drop_all_sql((_PARENT, _CHILD)))
        remaining = driver.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table'", ()
        )
    finally:
        driver.close()

    assert remaining == []


def test_sqlite_empties_a_schema_whose_keys_form_a_cycle() -> None:
    """Two tables pointing at each other have NO drop order, and the wipe must still work.

    This is the case ordering cannot reach, so it is the one that justifies keeping a pragma at all.
    Postgres and MySQL both come through it today; SQLite does only if the statements it emits
    postpone the check to the COMMIT, which is what `PRAGMA defer_foreign_keys` is for.
    """
    driver = SQLiteDriver.connect(":memory:")
    try:
        driver.execute(
            "CREATE TABLE cyc_a (id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES cyc_b(id))",
            (),
        )
        driver.execute(
            "CREATE TABLE cyc_b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES cyc_a(id))",
            (),
        )
        driver.execute("INSERT INTO cyc_a (id, b_id) VALUES (1, NULL)", ())
        driver.execute("INSERT INTO cyc_b (id, a_id) VALUES (1, 1)", ())
        driver.execute("UPDATE cyc_a SET b_id = 1", ())
        driver.commit()

        _run(driver, SQLiteDialect().drop_all_sql(("cyc_a", "cyc_b")))
        remaining = driver.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table'", ()
        )
    finally:
        driver.close()

    assert remaining == []


def test_nothing_to_drop_emits_nothing() -> None:
    """An empty schema needs no statements — not even the ones that bracket the drops."""
    for dialect in _DIALECTS:
        assert dialect.drop_all_sql(()) == ()
