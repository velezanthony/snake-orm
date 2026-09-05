"""Tests that the ORM's connections speak UTC to the server.

The problem: `TIMESTAMPTZ` stores the instant, but it DISPLAYS it in the session's time zone. If
the server sits in `Europe/Madrid`, a `SELECT created_at` returns `14:30:00+02` for an instant
stored as `12:30 UTC`. The datum is correct; what you see does not look like it.

And that breaks something that does matter: being able to open the database and VERIFY at a glance
that the dates are right, by checking that the offset is `+00`. With the session time zone left to
whatever the server happens to carry, that glance says nothing — and worse, it says different
things on everybody's machine.

It also makes the `CURRENT_TIMESTAMP` of a WALL-CLOCK column deterministic: without pinning the
zone it would store the server's local time, which is a different value on every deployment.

It is pinned on the CONNECTION, not on the session, and without running a single statement:
`options=-c timezone=UTC` travels inside the DSN itself and libpq applies it at startup. Doing it
with a `SET TIME ZONE` would open a transaction, and `set_isolation()` demands to be the first
statement of its own — they would break each other.
"""

from __future__ import annotations

from snakeorm import SnakeBackend, SnakeConnectionConfig
from snakeorm.drivers.psycopg import with_utc_timezone


def test_the_postgres_dsn_asks_the_server_for_utc() -> None:
    """Verifies that the DSN the configuration assembles asks for the UTC time zone."""
    config = SnakeConnectionConfig(backend=SnakeBackend.POSTGRES, name="app")
    assert "options='-c timezone=UTC'" in config.postgres_dsn()


def test_a_bare_dsn_gets_the_option_added() -> None:
    """Verifies that a hand-written DSN also comes out with the time zone pinned.

    The configuration is not the only way in: whoever builds the driver with their own DSN deserves
    the same guarantee, or the behaviour would depend on which door you came through.
    """
    assert "timezone=UTC" in with_utc_timezone("host=localhost dbname=app")


def test_an_explicit_options_is_respected() -> None:
    """Verifies that an `options=` of your own is NOT trampled.

    Whoever writes their own startup options knows what they are doing, and overwriting them would
    be deciding for them. This is the escape hatch: the zone is pinned by default, not by decree.
    """
    suyo = "host=localhost dbname=app options='-c statement_timeout=5000'"
    assert with_utc_timezone(suyo) == suyo


def test_the_mysql_connection_asks_for_utc_too() -> None:
    """Verifies that MySQL gets its equivalent (`SET time_zone`) when the connection opens.

    The mechanism changes —MySQL has no libpq `options`— but the guarantee is the same, or the
    contract would be worth something different per engine, which is exactly what this project is
    after.
    """
    config = SnakeConnectionConfig(backend=SnakeBackend.MYSQL, name="app")
    kwargs = config._mysql_kwargs()  # noqa: SLF001
    assert "+00:00" in str(kwargs.get("init_command", ""))
