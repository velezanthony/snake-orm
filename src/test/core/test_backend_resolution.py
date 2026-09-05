"""A DSN with an UNKNOWN scheme is refused, not quietly read as Postgres.

`backend_name_for` contradicted itself fifteen lines apart. It refuses an unknown `DB_BACKEND` with
the reason written out — "falling back means talking to another database without saying so" — and
then ends with `_BACKEND_NAMES.get(scheme, "postgres")`, which falls back for exactly the same kind
of typo.

And `.get(..., "postgres")` cannot tell the two cases apart. The docstring promises "Postgres, when
the DSN carries NO scheme", which is the legitimate case: a libpq keyword/value string like
`host=x dbname=y`. An unknown scheme is a different thing entirely, and `sqlite3://` or `mysqli://`
—`sqlite3` being the name of the Python module, and an alias `contrib/config.py` accepts elsewhere—
came out as Postgres.

This is the ONE function that decides which engine you are talking to. Same class of typo, two
opposite treatments, in the place where guessing costs the most.

A regex for the scheme rather than `split("://")`: a password containing `://` would otherwise be
read as one.
"""

from __future__ import annotations

import pytest

from snakeorm.core.config import backend_name_for
from snakeorm.core.exceptions import SnakeConfigError


def test_a_dsn_with_no_scheme_is_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """The libpq keyword/value form has no scheme, and that is not an error.

    It is the case the fallback existed for, and the one that has to keep working.
    """
    monkeypatch.setenv("SNAKEORM_DSN_PLAIN", "host=127.0.0.1 dbname=snakeorm_db")

    assert backend_name_for("plain") == "postgres"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "mysql", "sqlite"])
def test_a_known_scheme_answers_its_engine(
    monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    """The floor: the schemes that ARE known keep resolving."""
    monkeypatch.setenv("SNAKEORM_DSN_KNOWN", f"{scheme}://user@host/db")

    assert backend_name_for("known") in {"postgres", "mysql", "sqlite"}


@pytest.mark.parametrize("scheme", ["sqlite3", "mysqli", "postgressql"])
def test_an_unknown_scheme_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    """A typo in the scheme blows up naming what it read, like its sibling fifteen lines above.

    `sqlite3` is the sharpest of the three: it is the name of the Python module, and
    `contrib/config.py` accepts it as an ENGINE alias — so a user who wrote it here was being
    consistent with the other half of the ORM and got Postgres.
    """
    monkeypatch.setenv("SNAKEORM_DSN_TYPO", f"{scheme}://user@host/db")

    with pytest.raises(SnakeConfigError, match=scheme):
        backend_name_for("typo")


def test_the_refusal_lists_the_schemes_it_knows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It says what IS accepted, because the reader's next question is always that one."""
    monkeypatch.setenv("SNAKEORM_DSN_TYPO2", "mysqli://user@host/db")

    with pytest.raises(SnakeConfigError) as caught:
        backend_name_for("typo2")

    assert "sqlite" in str(caught.value)
    assert "mysql" in str(caught.value)


def test_a_password_containing_a_scheme_separator_is_not_read_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`split("://")` would take a password with `://` in it for the scheme.

    Reading the scheme with the RFC 3986 shape stops a legal password from deciding which engine the
    ORM believes it is talking to — which would be the same failure this file is about, arriving
    through a value the user never thought of as configuration.
    """
    monkeypatch.setenv("SNAKEORM_DSN_ODD", "postgres://user:p%3A%2F%2Fss@host/db")

    assert backend_name_for("odd") == "postgres"
