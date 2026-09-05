"""`snake_session(name)` opens against the engine the connection DECLARES, not always Postgres.

It wired `SnakeBackend.POSTGRES` in by hand while `dsn_for` resolved any DSN at all, so the one
convenience the guide puts on its own page could only ever reach one of the three engines. Its own
docstring says it delegates the pairing "instead of assembling the pair here", because "two
composition roots are one too many" — and then named the engine itself, which is half the pair.

Nothing in 324 test files called it, which is why nobody noticed: it is documented API with no
exercise behind it.

The engine is READ, never guessed:

1. `SNAKEORM_BACKEND_<NAME>` (or `DB_BACKEND` for the default connection), which always wins.
2. the DSN's own scheme — `postgresql://`, `mysql://`, `sqlite://` — because a scheme is a
   declaration and reading it is not divination.
3. Postgres, when the DSN carries no scheme at all: that shape (`host=x dbname=y`) IS libqp
   keyword syntax and no other engine speaks it. A derivation, not a fallback.
"""

from __future__ import annotations

import pytest

from snakeorm.connection import SnakeBackend
from snakeorm.core.config import backend_name_for
from snakeorm.core.exceptions import SnakeConfigError


def test_the_scheme_of_the_dsn_names_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DSN that announces its engine is believed: no environment variable needed."""
    esperado = {
        "postgresql://u:p@h/db": SnakeBackend.POSTGRES,
        "postgres://u:p@h/db": SnakeBackend.POSTGRES,
        "mysql://u:p@h/db": SnakeBackend.MYSQL,
        "sqlite:///tmp/x.db": SnakeBackend.SQLITE,
    }
    for dsn, backend in esperado.items():
        monkeypatch.setenv("SNAKEORM_DSN_ANALYTICS", dsn)
        assert backend_name_for("analytics") == backend.value, f"failed for {dsn}"


def test_a_libpq_dsn_with_no_scheme_is_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`host=x dbname=y` is Postgres's own keyword syntax; no other engine writes one.

    That is why it is a derivation and not a blind default: the shape already said it.
    """
    monkeypatch.setenv(
        "SNAKEORM_DSN_LEGACY", "host=db.example dbname=ventas user=postgres"
    )

    assert backend_name_for("legacy") == SnakeBackend.POSTGRES.value


def test_the_declared_variable_beats_the_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit `SNAKEORM_BACKEND_<NAME>` wins: saying it out loud always beats inferring it."""
    monkeypatch.setenv("SNAKEORM_DSN_MIRROR", "postgresql://u:p@h/db")
    monkeypatch.setenv("SNAKEORM_BACKEND_MIRROR", "mysql")

    assert backend_name_for("mirror") == SnakeBackend.MYSQL.value


def test_an_unknown_engine_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo does NOT fall back to Postgres: it says what it read and what the three are.

    The demos already learned this one the hard way — their own config notes that a `postgress`
    with one extra `s` brought the app up on SQLite, talking to the wrong database in silence.
    """
    monkeypatch.setenv("SNAKEORM_DSN_TYPO", "postgresql://u:p@h/db")
    monkeypatch.setenv("SNAKEORM_BACKEND_TYPO", "postgress")

    with pytest.raises(SnakeConfigError) as error:
        backend_name_for("typo")

    message = str(error.value)
    assert "postgress" in message and "mysql" in message and "sqlite" in message


def test_it_opens_a_real_session_on_the_file_the_dsn_names(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`snake_session("archivo")` over a SQLite DSN opens THAT file, not one named after the alias.

    The end-to-end half, and the one that was impossible: the function hard-wired
    `SnakeBackend.POSTGRES`, so this call opened a psycopg connection against a path.

    Asserting the FILE and not just the dialect, because the first version of this test checked
    `isinstance(session.dialect, SQLiteDialect)` and passed while the session was writing to a file
    called `archivo` in the working directory — the alias, handed over where the PATH belongs. A
    dialect check cannot tell those two apart, and an assertion that cannot fail on the bug it was
    written for is the exact shape this repository keeps finding in its own tests.
    """
    from pathlib import Path

    from snakeorm.dialects import SQLiteDialect
    from snakeorm.session import snake_session

    fichero = Path(str(tmp_path)) / "demo.db"
    monkeypatch.setenv("SNAKEORM_DSN_ARCHIVO", f"sqlite:///{fichero}")

    session = snake_session("archivo")

    assert isinstance(session.dialect, SQLiteDialect)
    assert fichero.exists(), "it opened some other file than the one the DSN names"
    assert not Path("archivo").exists(), "it used the ALIAS as a path"


def test_a_mysql_dsn_becomes_the_pieces_that_driver_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`mysql://u:p@h:3307/ventas` is taken apart: PyMySQL takes loose arguments, not a DSN string.

    Each engine wants the connection said in its own shape — psycopg reads a DSN, SQLite wants a
    path, PyMySQL wants keyword arguments — so a DSN has to be TRANSLATED, and translating it in
    one place is what keeps a driver from ever being joined to another engine's dialect.
    """
    from snakeorm.connection import SnakeBackend, SnakeConnectionConfig

    config = SnakeConnectionConfig.from_dsn(
        "mysql://root:secreta@db.example:3307/ventas", SnakeBackend.MYSQL
    )

    assert (config.host, config.port, config.user, config.name) == (
        "db.example",
        "3307",
        "root",
        "ventas",
    )
    assert config.password == "secreta"
