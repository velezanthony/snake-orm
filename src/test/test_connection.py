"""Tests for the CENTRALISED connection config (`SnakeConnectionConfig`).

It is the object that crowns the connection config of ANY framework: the binders (Django, Flask,
FastAPI) translate their native config into THIS. The `backend` picks driver AND dialect PAIRED UP,
so the user cannot get them out of sync (the classic bug of wiring SQLiteDriver to PostgresDialect).
"""

from __future__ import annotations

from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.dialects import SQLiteDialect
from snakeorm.drivers.base import SnakeDriver
from snakeorm.session import SnakeSession


def test_backend_pairs_driver_and_dialect() -> None:
    """The `backend` returns driver and dialect PAIRED UP: crossing SQLite with Postgres is impossible."""
    config = SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
    driver, dialect = config.driver_and_dialect()
    assert isinstance(dialect, SQLiteDialect)
    # And the driver works: it creates, inserts and reads over the same in-memory connection.
    driver.execute("CREATE TABLE t (id INTEGER)", ())
    driver.execute("INSERT INTO t (id) VALUES (1)", ())
    assert driver.fetch_all("SELECT id FROM t", ()) == [(1,)]


def test_open_returns_a_session() -> None:
    """`open()` assembles the full session (driver + dialect) in a single call."""
    config = SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
    session = config.open()
    assert isinstance(session, SnakeSession)
    session.close()


def test_open_applies_the_wrap() -> None:
    """`open(wrap=)` runs the driver through the wrap: the seam for wrapping it (CaptureDriver, pool, ...)."""
    seen: list[SnakeDriver] = []

    def wrap(driver: SnakeDriver) -> SnakeDriver:
        seen.append(driver)
        return driver

    config = SnakeConnectionConfig(backend=SnakeBackend.SQLITE, name=":memory:")
    session = config.open(wrap=wrap)
    assert len(seen) == 1  # the wrap received the raw driver
    session.close()


def test_postgres_dsn_from_pieces() -> None:
    """The pieces (host/port/user/password/name) assemble into the Postgres DSN, without the user."""
    config = SnakeConnectionConfig(
        backend=SnakeBackend.POSTGRES,
        name="app",
        host="db",
        port="5433",
        user="postgres",
        password="secret",
    )
    dsn = config.postgres_dsn()
    assert "host=db" in dsn
    assert "dbname=app" in dsn
    assert "port=5433" in dsn
    assert "user=postgres" in dsn
    assert "password=secret" in dsn


def test_every_backend_declares_its_opentelemetry_name() -> None:
    """The `backend` answers what OpenTelemetry calls the engine (`db.system.name`).

    It lives HERE because `SnakeBackend` is the one place engine identity is written down, next to
    the driver/dialect pairing. Deriving it anywhere else —from the driver's class, from the SQL's
    placeholders— would be a second spelling of the same fact, and a decorated driver hides its
    class anyway.
    """
    assert SnakeBackend.POSTGRES.db_system_name == "postgresql"
    assert SnakeBackend.MYSQL.db_system_name == "mysql"
    assert SnakeBackend.SQLITE.db_system_name == "sqlite"


def test_no_backend_is_left_without_a_name() -> None:
    """EVERY member answers, so a fourth engine cannot arrive with a silent hole in its telemetry."""
    assert all(backend.db_system_name for backend in SnakeBackend)
