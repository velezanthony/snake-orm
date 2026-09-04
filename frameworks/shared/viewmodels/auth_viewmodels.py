"""auth view models: the access ledger of one person — the tokens they hold and the sessions open.

THIS DOMAIN HAD NEVER HAD A SCREEN, and it looked as though it had. `django/apps/auth/views.py` and
`flask/apps/auth/urls.py` serve the login and the registration, so read by PACKAGE the domain has
pages; followed to the definition, those pages are `shared/usecases/blog_usecases.py::login` and
`::register`, and the auth domain proper — API tokens and login sessions — reached exactly nothing
in HTML. `test_the_page_and_the_api_reach_one_usecase.py` is the net that could see it, because it
joins on the module that holds the `def` rather than on two identifiers that look alike.

WHAT THIS PAGE IS AND WHAT IT IS NOT. It READS. Minting a token and revoking one stay on the JSON
surface, and that is a decision this repository already argued and both catalogues already quote: a
token is for a client with no cookie jar, a browser gets a signed session, so the two halves of
authentication genuinely belong to different surfaces. Nothing here reverses it — a ledger you can
read is not a mint — and the day somebody puts an "issue" button on this screen, `_BY_DESIGN` is the
entry they have to argue with first.

WHY BOTH TOKEN READS ARE ON ONE PAGE, which is the question a reviewer should ask. `tokens_of_user`
is the ledger — everything ever issued — and `active_tokens` is a DIFFERENT query with a `WHERE` of
its own. The page prints "3 of 7 not revoked" and marks the rows, and it can only do that from the
two answers: deriving the second set from the first in Python would put a second copy of the
domain's definition of "still usable" in a layer whose whole job is to print what it was given.

AND THE PAGE SAYS "NOT REVOKED" RATHER THAN "STILL VALID", WHICH IS NOT A NICETY. `active_of` filters
on `revoked` alone and has never looked at `expires_at`, though both callers above it used to claim
it did — `shared/usecases/auth_usecases.py::active_tokens` now documents the gap where a reader will
find it. So a token past its expiry is counted here, and the wording is what stops this screen from
repeating a promise the query does not keep. The day the filter grows the second condition, this
paragraph and the two words on the page are what change with it.
"""

from __future__ import annotations

from typing import TypedDict

from snakeorm import SnakeSession

from shared.usecases import auth_usecases as usecases


class TokenRow(TypedDict):
    """One API token WITHOUT its secret: what it is for, when it was minted and its state.

    The value is never here, for the reason the DTO next door gives: a screen that printed the
    secret would be a hole rather than a demo, and the redaction has to hold on both surfaces or it
    holds on neither.
    """

    token_id: int
    label: str
    revoked: bool
    created_at: str
    expires_at: str
    not_revoked: bool


class SessionRow(TypedDict):
    """One login session: where it came from and when it was last seen."""

    session_id: int
    ip: str
    user_agent: str
    created_at: str
    last_seen_at: str


class AccessLedger(TypedDict):
    """One person's access: every token with the un-revoked ones marked, and every open session."""

    user_id: int
    tokens: list[TokenRow]
    token_count: int
    not_revoked_count: int
    sessions: list[SessionRow]


def access_ledger(session: SnakeSession, user_id: int) -> AccessLedger:
    """The tokens and sessions of one person. THREE statements, and none of them per row.

    `not_revoked` is a membership test against the ids the ENGINE answered with, not a condition
    re-checked here. That is the rule this layer keeps everywhere: the second query is what defines
    the set, and this function marks the rows it already has rather than owning a second copy of the
    definition. It is also why the field is called what the query filters on — see the module
    docstring, and the gap it names.

    No `Failure` and no probe that the person exists. Three empty lists is what "this user holds
    nothing" looks like, and it is also what "there is no such user" looks like — which is an honest
    answer to a hand-edited URL and one statement cheaper than a nicer one.
    """
    tokens = usecases.tokens_of_user(session, user_id)
    standing = {token.id for token in usecases.active_tokens(session, user_id)}
    return {
        "user_id": user_id,
        "tokens": [
            {
                "token_id": token.id,
                "label": token.label or "",
                "revoked": token.revoked,
                "created_at": token.created_at.isoformat(),
                "expires_at": token.expires_at.isoformat(),
                "not_revoked": token.id in standing,
            }
            for token in tokens
        ],
        "token_count": len(tokens),
        "not_revoked_count": len(standing),
        "sessions": [
            {
                "session_id": login.id,
                "ip": login.ip,
                "user_agent": login.user_agent or "",
                "created_at": login.created_at.isoformat(),
                "last_seen_at": login.last_seen_at.isoformat(),
            }
            for login in usecases.sessions_of_user(session, user_id)
        ],
    }
