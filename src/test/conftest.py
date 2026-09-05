"""A test that skips in silence is worse than a test that does not exist.

The tests that talk to Postgres skip gracefully when there is no server, and that is FINE on the
laptop of someone who only wants to poke at the compiler. In CI it is exactly the opposite: there
the server has to be up, and a `skip` means the infrastructure failed and the suite covered it up.

This repo already paid for it once. A badly propagated `DB_PORT` in the devcontainer left **109
integration tests skipping** for who knows how long, with the suite reporting green. Nobody looks at
the `skipped` count; everybody looks at whether it says `passed`.

**The net triggers on the REASON for the skip, not on the folder.** The first version looked at a
list of directories (`integration`, `scenarios`) and missed two files in `test/migration` that also
need a server — precisely the ones about atomicity and data migrations, which are the ones it hurts
most not to run. A list of places has to be maintained and goes stale; the reason for the skip
travels with the test, so a new file in a new folder is covered without its author having to know
that this exists.

Turn it on with `SNAKEORM_REQUIRE_POSTGRES=true`. Without the variable, the usual behaviour.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest

from snakeorm.core.config import DB_ENV_KEYS, load_env
from test import session_db

NO_SERVER_REASON = "Postgres is not reachable"
"""The phrase with which the WHOLE repo announces that it is skipping for lack of Postgres.

A CONSTANT that gets imported, not a wording everybody agrees to spell the same. It was the second
for a long time — fifty-three files each with their own copy — and twenty of them had drifted to
"there is no Postgres available", which this file's check did not recognise. `test_ci_guard.py`
demands the NAME now, so there is nothing left to spell differently.
"""

NO_MYSQL_REASON = "MySQL is not reachable"
"""The same, for the MySQL server, which has its own variable and its own container."""

MYSQL_ENV_KEYS: tuple[str, ...] = (
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
)
"""The variables that point the suite at a MySQL. Written out rather than derived, because the ORM
package has no MySQL config to derive them FROM: `DB_ENV_KEYS` comes from `snakeorm.core.config`,
which builds a psycopg2 DSN and is Postgres by construction. These names are the ones the e2e tests
and `frameworks/shared/config.py` already read.
"""

_STRICT_BY_REASON: dict[str, tuple[str, tuple[str, ...]]] = {
    NO_SERVER_REASON: ("SNAKEORM_REQUIRE_POSTGRES", DB_ENV_KEYS),
    NO_MYSQL_REASON: ("SNAKEORM_REQUIRE_MYSQL", MYSQL_ENV_KEYS),
}
"""Per engine: which switch makes its absence a FAILURE, and which variables to go and look at.

ONE entry per engine and not one branch, and the two halves live together on purpose. They used to be
one table and a hardcoded sentence: whichever engine had gone missing, the failure told you to check
`DB_HOST, DB_PORT, ...`. So the first person to turn the MySQL switch on was sent to inspect the
connection of a database that was up, which is the worst thing a diagnostic can do — following it
proves everything is fine and teaches you nothing.

Postgres had a switch and the other engines did not, so the doctrine said three first-class engines
while the safety net covered one. The MySQL e2e tests skipped in green with the container up and
running, for months, because nothing existed to say otherwise. Adding an engine here is answering a
question; it used to be remembering one.
"""


def _connection_advice_for(reason: str) -> str:
    """Where to go looking when THIS engine is the one that was not there.

    Kept as a named function because the failure message is the only part of this file a person ever
    reads, and a message that names the wrong variables is worse than no message: it is confident.
    """
    entry = _STRICT_BY_REASON.get(reason)
    if entry is None:
        return "Check the database service and its connection variables."
    _, keys = entry
    return f"Check the service and its variables ({', '.join(keys)})."


_TRUE, _FALSE = "true", "false"
"""ONE spelling per side. Not `yes`, not `on`, not `1` — a boolean, written the way a boolean is.

Every synonym is another thing a reader has to know is equivalent, and past six of them the question
stops being "is it on?" and becomes "is MY word on the list?". That is precisely how this went wrong:
it was a blacklist —`0`, `false` and `no` meant off, ANYTHING else meant on— so
`SNAKEORM_REQUIRE_POSTGRES=off` read to a person as plainly off and switched the net ON, in silence.
The fix is not a longer list. A longer list has the same shape and only moves the edge.
"""


def _strict_mode(variable: str = "SNAKEORM_REQUIRE_POSTGRES") -> bool:
    """Is this switch on? Unset is off, `true`/`false` decide, anything else RAISES.

    THERE IS NO DEFAULT FOR A TYPO, and that is deliberate, because both defaults are wrong in the
    same way. Reading an unknown value as ON hides a switch somebody meant to turn off; reading it as
    OFF hides the very skips this net exists to surface. So the value is named back and the run
    stops — the same call `snake_cast` and `DB_BACKEND` already make, and for the same reason: a
    guess here is a wrong answer with nothing to show for it.
    """
    raw = os.environ.get(variable, "").strip().lower()
    if raw == "":
        return False
    if raw in (_TRUE, _FALSE):
        return raw == _TRUE
    raise ValueError(
        f"{variable}={raw!r} is not a boolean: write {_TRUE!r} or {_FALSE!r}, or leave it unset. "
        f"It is not guessed either way, and that is deliberate — reading it as on would hide a "
        f"switch you meant to turn off, and reading it as off would hide the very skips this net "
        f"exists to make loud."
    )


def pytest_configure(config: pytest.Config) -> None:
    """Reads every switch ONCE, before collection, so a bad value stops the run in second zero.

    WHAT THIS FIXES IS NOT A GATE THAT FAILED OPEN, and the distinction has to be written down
    because the first draft of it got this wrong. The net never let a typo disable it: measured,
    `SNAKEORM_REQUIRE_POSTGRES=ture` with the server DOWN raised and stopped the run. What the value
    could not do was pass unnoticed AND matter.

    The defect was WHEN and HOW the complaint arrived.

    WHEN: the hook below reads the switch only once something has actually skipped for want of a
    server — so with a healthy database the typo is invisible, and the day the database falls over
    you get told about your shell instead. That is the one moment you were owed a clear sentence
    about the DATABASE, and the gate spends it on itself.

    HOW: as an INTERNALERROR, because a `ValueError` raised inside `pytest_runtest_makereport` is an
    exception inside a hook. pytest stops dead there — no summary, no tally, no test named, and a
    traceback that points at the safeguard instead of at the environment that broke it. In a project
    whose doctrine is that the message IS the product, that is the worst available way of being
    right, and it is exactly what `frameworks/shared/tests` hit from the other direction.

    So the values are checked here, where pytest has a way of refusing a configuration: `UsageError`
    prints one clean `ERROR:` line per problem and exits with the CONFIGURATION code, before a single
    test is collected. The hook keeps reading lazily and that stays correct — by the time it runs,
    the value has already been proven to be a boolean.

    EVERY switch, walked off `_STRICT_BY_REASON` rather than named here. The gate that gets forgotten
    is the one belonging to the engine added last: that is precisely how MySQL ended up with a switch
    that CI never set. An engine added to the table is an engine validated here, for free.

    All the bad ones at once, too. Stopping at the first would make somebody fix one, run again and
    meet the other — a whole start-up paid per mistake, to be told something this run already knew.

    AND THE SECOND THING IT DOES is give this run a database of its own, for a reason of exactly the
    same shape: it has to happen before anything is collected, because by the time a fixture asks for
    a connection the name has already been read. `session_db.open_session()` is the whole of it.
    """
    problems = []
    for variable, _keys in _STRICT_BY_REASON.values():
        try:
            _strict_mode(variable)
        except ValueError as error:
            problems.append(str(error))
    if problems:
        raise pytest.UsageError(*problems)

    try:
        session_db.open_session()
    except session_db.SessionIdError as error:
        raise pytest.UsageError(str(error)) from None


def _reason_for(report: Any) -> str | None:
    """The MISSING-ENGINE reason behind this skip, or `None` if the skip is about something else.

    The distinction matters: a unit test may skip because the dialect does not support a
    capability, and turning that into a failure would be noise dressed up as rigour.
    """
    text = str(report.longrepr)
    return next(
        (reason for reason in _STRICT_BY_REASON if reason in text),
        None,
    )


def _skipped_for_lack_of_server(report: Any) -> bool:
    """Is this skip a 'there is no database' one? Kept as its own name because tests read it."""
    return _reason_for(report) is not None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: Any
) -> Generator[None, None, None]:
    """Turns into a FAILURE the skip of a test that in this environment had to run.

    Acting on the report and not on the execution is deliberate: the test already skipped and there
    is nothing to re-run. What has to be fixed is the verdict, the only thing anyone is going to read.
    """
    result = yield
    report = result.get_result()  # type: ignore[attr-defined]
    if not report.skipped:
        return
    reason = _reason_for(report)
    if reason is None:
        return
    variable, _ = _STRICT_BY_REASON[reason]
    if not _strict_mode(variable):
        return
    report.outcome = "failed"
    report.longrepr = (
        f"{item.nodeid} was SKIPPED for want of a database, and with {variable} active that is a "
        f"failure.\n\nOriginal reason: {report.longrepr}\n\n"
        f"A skip here does not mean the code is right: it means the database was not there and the "
        f"suite covered for it. {_connection_advice_for(reason)}"
    )


_CONNECTION_ENV = (
    "DATABASE_URL",
    "SNAKEORM_DSN",
    *dict.fromkeys(
        key for _variable, keys in _STRICT_BY_REASON.values() for key in keys
    ),
)
"""The variables that decide WHICH database the suite talks to.

Not a general environment guard: these are the ones whose leaking is invisible AND expensive. A
stray `PATH` is somebody else's problem; a stray `DB_HOST` sends every following test at a database
that is not there, and they SKIP rather than fail.

DERIVED from `_STRICT_BY_REASON`, which is the one place that says which engines have a gate. It
used to list `DB_ENV_KEYS` alone — the Postgres ones — while the catalogue has been three since
MySQL got its gate, and `MYSQL_ENV_KEYS` sits 170 lines above this in the same file. Written out by
hand, a fourth engine's variables go unwatched the day its gate appears, and they go unwatched
quietly, which is the failure this whole file exists to make impossible.
"""


@pytest.fixture(scope="session", autouse=True)
def _load_the_real_env_once() -> None:
    """The project's `.env` is read ONCE, before any test, so the baseline is stable.

    Without this the net below fires on something legitimate: the first test that reaches a real
    server calls `load_env()`, the real `DB_*` land in the process, and that reads as a change. It
    is not one — those are the values the suite is meant to run against, and loading them is
    idempotent.

    Pinning them up front turns "the environment changed" into a statement with only one meaning:
    somebody wrote something that was NOT the project's configuration.
    """
    load_env()


@pytest.fixture(autouse=True)
def _no_test_leaks_the_connection(request: pytest.FixtureRequest) -> Generator[None]:
    """A test leaves the connection variables exactly as it found them. Fails if it does not.

    `load_env()` writes into `os.environ` — that is its job — and `monkeypatch.delenv(key,
    raising=False)` on a key that is ABSENT records nothing to put back. Put the two together and a
    test that loads a `.env` full of made-up values leaves them in the process for good.

    Measured before this net existed: `test_dsn_resolution.py` left `DB_HOST='host_del_env'` and
    `DB_NAME='bd_del_env'` behind, so `test_e2e_postgres.py` passed on its own and SKIPPED when the
    two ran together. Thirteen tests against a real server turned green-by-absence, and the suite
    reported success either way.

    It survived on alphabetical luck. This net does not care about the order: it is autouse, so the
    leak is caught in the test that causes it and names that test, instead of being debugged in
    whatever ran afterwards.
    """
    before = {key: os.environ.get(key) for key in _CONNECTION_ENV}
    yield
    leaked = {
        key: (before[key], os.environ.get(key))
        for key in _CONNECTION_ENV
        if before[key] != os.environ.get(key)
    }
    assert leaked == {}, (
        f"{request.node.name} changed the connection environment and did not put it back: "
        f"{leaked}. Every test that follows will point at that database, and the ones needing a "
        f"real server SKIP instead of failing. Restore it (a plain snapshot in the fixture; "
        f"`monkeypatch.delenv` on an absent key registers nothing)."
    )
