"""The access ledger: the first page the auth domain has ever had, and what it must not print.

TWO THINGS ARE ASSERTED HERE AND THEY ARE BOTH ABOUT HONESTY. The first is the redaction: a token's
secret never reaches the shape a template walks, the same way the DTO next door refuses it, because a
redaction that holds on one surface and not the other holds on neither.

THE SECOND IS THAT THE PAGE COUNTS AN EXPIRED TOKEN, and this file asserts it ON PURPOSE. `active_of`
filters on `revoked` and has never looked at `expires_at`, while `active_tokens` claimed in its
docstring to answer "neither revoked nor expired" — a promise the query does not keep, which is the
exact failure shape this repository names over and over. The fixture below therefore carries a token
whose expiry has gone by, and the assertion pins what the code DOES rather than what the sentence
said. Writing it the other way round would have made a test out of a wish, and green.

`shared/usecases/auth_usecases.py::active_tokens` carries the argument for correcting the wording
instead of the filter: widening it changes what `/api/auth/users/{id}/tokens/active` answers on
seeded data, and that is a decision about the domain rather than about a sentence. When somebody
takes it, this test goes red and names the line — which is what it is for.
"""

from __future__ import annotations

from datetime import timedelta

from snakeorm import SnakeSession, SnakeUtc

from shared.models import ApiToken, LoginSession, User
from shared.viewmodels import auth_viewmodels as viewmodels


def _world(session: SnakeSession) -> int:
    """One person with three tokens — live, revoked, expired — and one open session."""
    user = session.add(User(username="ada", email="ada@example.com", password_hash="x"))
    now = SnakeUtc.now()
    session.add(
        ApiToken(
            token="live-secret",
            label="laptop",
            revoked=False,
            user_id=user.id,
            expires_at=now + timedelta(days=30),
        )
    )
    session.add(
        ApiToken(
            token="revoked-secret",
            label="old laptop",
            revoked=True,
            user_id=user.id,
            expires_at=now + timedelta(days=30),
        )
    )
    session.add(
        ApiToken(
            token="expired-secret",
            label=None,
            revoked=False,
            user_id=user.id,
            expires_at=now - timedelta(days=1),
        )
    )
    session.add(
        LoginSession(
            user_id=user.id,
            ip="10.0.0.5",
            user_agent="a browser",
            last_seen_at=now,
        )
    )
    session.commit()
    return user.id


def test_the_ledger_marks_the_rows_the_second_query_came_back_with(
    session: SnakeSession,
) -> None:
    """Three tokens — standing, revoked, expired — and the expired one counts as not revoked.

    That last clause is the measurement, not an oversight of this test. `active_tokens` asks only
    about `revoked`, so the expired token is in its answer and the ledger marks it; the page says
    "not revoked" for exactly this reason. If somebody widens the filter to look at `expires_at`,
    this line goes red and points at the two words on the page that have to change with it.
    """
    user_id = _world(session)

    ledger = viewmodels.access_ledger(session, user_id)

    assert (ledger["token_count"], ledger["not_revoked_count"]) == (3, 2)
    assert [(t["label"], t["not_revoked"]) for t in ledger["tokens"]] == [
        ("laptop", True),
        ("old laptop", False),
        ("", True),
    ]


def test_the_secret_never_reaches_the_page(session: SnakeSession) -> None:
    """A token's value is not a field of this shape, and it cannot become one by accident.

    Asserted by NAME and over the whole row rather than by comparing to a string: the failure being
    guarded against is somebody adding a field, and a check for one particular key would not see it.
    """
    user_id = _world(session)

    ledger = viewmodels.access_ledger(session, user_id)

    for token in ledger["tokens"]:
        assert "token" not in token
        assert "live-secret" not in token.values()


def test_the_sessions_are_flattened_to_what_a_row_prints(
    session: SnakeSession,
) -> None:
    """The other half of authentication: where a browser came from and when it was last seen."""
    user_id = _world(session)

    ledger = viewmodels.access_ledger(session, user_id)

    assert [(s["ip"], s["user_agent"]) for s in ledger["sessions"]] == [
        ("10.0.0.5", "a browser")
    ]


def test_somebody_who_holds_nothing_gets_three_empty_lists(
    session: SnakeSession,
) -> None:
    """No `Failure` and no probe: an empty ledger is an answer, and a cheaper one than a 404."""
    _world(session)

    ledger = viewmodels.access_ledger(session, 9999)

    assert (ledger["tokens"], ledger["sessions"]) == ([], [])
    assert (ledger["token_count"], ledger["not_revoked_count"]) == (0, 0)
