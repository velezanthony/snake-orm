"""Which working session this process belongs to, and what that does to a database name.

WHY THE DEMOS NEED THIS AT ALL. Every suite in this repository points at the same two containers.
`shared/tests` drops and recreates twenty-nine tables once per run and TRUNCATEs them before every
single test; the three apps do `drop_all` and migrate at boot. Two runs at a time and one of them is
emptying tables the other is mid-way through reading — and because the seed is deterministic, the
counts often still add up. A suite going green over a schema somebody else rebuilt underneath it is
the failure mode this repository has already met in its loud form (`DuplicateTable`,
`DeadlockDetected`); the quiet form is the one worth spending a file on.

THE RULE, AND WHY IT LIVES IN A LEAF. With `SNAKEORM_SESSION_ID` set, every database, schema and
SQLite file this side provisions carries it: `flask_demo` becomes `flask_demo__s41287`. With it
UNSET there is no suffix and nothing changes — which is what keeps `make flask-dev` pointing at the
database you seeded yesterday. The suites set it; the servers do not.

This module imports `os` and `re` and NOTHING else, and that is a requirement rather than a
coincidence: `frameworks/django/config/settings.py` has to apply the same rule, and it runs before
`django.setup()`. Pulling `shared.config` in there would drag the whole domain graph and the ORM into
Django's settings import. One rule, one file, no weight.

IT IS A DELIBERATE COPY of `src/test/session_db.py`, for the reason this repository has already
written down once for the strict-gate parser: `test` is importable in the ORM's run only because
`pythonpath = ["src"]` puts it there, and hatchling keeps it out of the wheel on purpose. The demos
exist to show what somebody gets from the PUBLISHED package, so they may not reach into the ORM's
test tree. What stops the copy from drifting is
`shared/tests/test_both_sides_name_the_session_database_alike.py`, which reaches the other half by
PATH — a thing a test may do and the layout may not — and asks both the same questions.
"""

from __future__ import annotations

import os
import re

SESSION_VARIABLE = "SNAKEORM_SESSION_ID"
"""The one variable that says which run this is. Unset means no isolation, which is a valid answer."""

MARK = "__s"
"""What separates a base name from a session id. TWO underscores, and that is not decoration.

Every base name on this side already contains a single one — `flask_demo`, `shared_operations` — so
`_s12` would be indistinguishable from a name somebody meant. The other half of this rule authorises
a `DROP DATABASE`, and it may only drop what it can recognise beyond argument.
"""

_ID_PATTERN = re.compile(r"\A[A-Za-z0-9]{1,32}\Z")
"""Letters and digits, at most thirty-two. Narrow because the id ends up inside DDL and inside a
filename: a hyphen would force quoting, a dot would read as a schema or an extension, and anything
longer risks the 63-character identifier ceiling Postgres enforces and MySQL mirrors at 64."""

_SCOPED_PATTERN = re.compile(
    rf"\A(?P<base>.+){re.escape(MARK)}(?P<session>[A-Za-z0-9]{{1,32}})\Z"
)
"""The same rule read backwards, so a name can be asked which session it already belongs to."""


class SessionIdError(ValueError):
    """An id that cannot become part of a database name. Raised rather than trimmed to fit."""


def validated(session: str) -> str:
    """The id, or a refusal that names it back. There is no repair, and that is the point.

    Quietly stripping the character it did not like would hand back a database with a name the person
    never wrote, and they would then go looking for the one they did.
    """
    if not _ID_PATTERN.match(session):
        raise SessionIdError(
            f"{SESSION_VARIABLE}={session!r} cannot go in a database name: use between 1 and 32 "
            f"letters or digits, and nothing else. It is not trimmed to fit — you would be handed a "
            f"database with a name you never wrote."
        )
    return session


def session_of(name: str) -> str | None:
    """The session id inside a marked name, or `None` if the name belongs to nobody.

    The inverse of `scoped`, and the only way it can tell "already done" apart from "done by
    somebody else". `.+` is greedy, so a name that was marked twice by the bug this file records
    answers with the LAST mark — which is what lets the ORM's sweep recognise those leftovers and
    collect them instead of leaving them for a person to find.
    """
    match = _SCOPED_PATTERN.match(name)
    return match.group("session") if match else None


def scoped(name: str, session: str | None) -> str:
    """`name` as this run sees it. With no session, the name itself: no session, no isolation.

    A pure function of two strings, which is what lets a test hold it against the ORM's copy without
    a server, an environment or a process in the way.

    IT IS IDEMPOTENT, AND IT WAS NOT, AND THE ORM's COPY IS WHERE THAT COST WAS PAID. There, the
    finished name is written back into `os.environ`, so a child process reads a name that is already
    marked; applied twice, it answered `snakeorm_db__s41287__s41287` and the child quietly stopped
    sharing its parent's database. **The whole suite stayed green through it — 3095 passed, 24
    skipped** — because nothing anywhere compared the two names.

    This side derives rather than rewriting, so it could not produce that name today. The rule is
    the same anyway, and deliberately: the two halves are held together by
    `test_both_sides_name_the_session_database_alike.py`, and a copy that is "correct for now
    because of how its callers happen to work" is a copy that goes wrong the first time a caller
    changes.

    A MARK BELONGING TO ANOTHER SESSION IS A REFUSAL, not a second suffix, and the two cases only
    look alike. Meeting this run's own mark means the name has already been through here — nothing
    to do. Meeting somebody else's means this process is holding a name from an environment that is
    not its own, and the only two ways to carry on are both wrong: nesting the marks invents a third
    database nobody owns, and replacing it steals a name that belongs to a run that may well be
    alive. So it stops and says whose name it found.
    """
    if session is None:
        return name
    validated(session)
    carried = session_of(name)
    if carried == session:
        return name
    if carried is not None:
        raise SessionIdError(
            f"{name!r} already carries session {carried!r} and this run is {session!r}. That is an "
            f"inherited name from somebody else's environment, not a name to mark again: nesting "
            f"the marks would invent a third database nobody owns, and replacing it would steal "
            f"one that may still be in use. Find out where {name!r} came from."
        )
    return f"{name}{MARK}{session}"


def current() -> str | None:
    """The session this process belongs to, or `None` when it belongs to none.

    READ AND NEVER INVENTED. If this defaulted to the PID, every `flask run` and every `manage.py
    runserver` would come up on a brand-new empty database and the seeded demo would look broken.
    Opening a session is `claim()`, and only a test harness calls it.
    """
    raw = os.environ.get(SESSION_VARIABLE)
    return None if raw is None else validated(raw.strip())


def claim() -> str:
    """Opens a session for this process unless one was inherited, and returns its id.

    Called by the thing that RUNS a suite — a `conftest.py`, or `manage.py` on its way into
    `test` — so that nobody running the suite has to export anything for the isolation to happen.

    `setdefault` and not an assignment, because a suite is regularly a child process: `make
    frameworks-test` and CI both start one from another, and a child that reclaims the id would point
    at a database its parent is not using. Inheriting is the correct answer for a child.
    """
    return validated(os.environ.setdefault(SESSION_VARIABLE, str(os.getpid())))
