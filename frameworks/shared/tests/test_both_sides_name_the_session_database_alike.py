"""The rule that gives a run its own database is written TWICE, and this pins the two together.

`src/test/session_db.py` owns it for the ORM's suite and `shared/session.py` owns it for the demos.
They have to agree on every character, because they name databases on the SAME server: if one side
spells `snakeorm_db__s41287` and the other `shared_operations-s41287`, then the sweeper — which lives
on the ORM's side and recognises names by shape — stops seeing the demos' leftovers. Nothing goes
red. The disks just fill up, quietly, which is the only failure mode nobody has a test for.

WHY THERE ARE TWO COPIES AT ALL is the same answer this repository already wrote down for the strict
gate's parser: `test` is importable in the ORM's run only because `pythonpath = ["src"]` puts it
there, and hatchling keeps it out of the wheel on purpose. The demos exist to show what somebody gets
from the PUBLISHED package, so `shared/session.py` may not reach into the ORM's test tree. On top of
that, `shared/session.py` has a second constraint the ORM's copy does not: `django/config/settings.py`
imports it before `django.setup()`, so it may not pull in anything heavier than `os` and `re`.

So the copy stays and this file makes it answerable. It reaches the other half by PATH — a thing a
test may do and the layout may not — and asks both the same questions: the same variable, the same
mark, the same names out, the same refusals.

WHAT IS DELIBERATELY *NOT* SHARED, so nobody "fixes" it: the two halves do different things with an
ABSENT id. The ORM's suite CLAIMS one in `pytest_configure`, because a pytest run is always a test
run. This side only READS one, because `shared/config.py` is the same module `make flask-dev` goes
through, and a dev server that claimed a session would come up on an empty database on every
restart. `claim()` exists here too, and only a test harness calls it.
"""

from __future__ import annotations

import importlib.util
import pathlib
from collections.abc import Callable
from types import ModuleType

import pytest

from shared.session import MARK, SESSION_VARIABLE, SessionIdError, current, scoped

_ORM_SESSION_DB = (
    pathlib.Path(__file__).resolve().parents[3] / "src" / "test" / "session_db.py"
)
"""The ORM suite's copy, as a FILE. Four levels up: tests -> shared -> frameworks -> the repo."""


def _load_orm_half() -> ModuleType:
    """Imports the ORM's copy by path, under a name of its own.

    By path and not by `import`, because there is no import that reaches it from here — which is the
    whole reason the rule is duplicated. Reading it is side-effect free: the module defines
    constants and functions, opens no connection and touches no environment.
    """
    spec = importlib.util.spec_from_file_location("orm_session_db", _ORM_SESSION_DB)
    assert spec is not None and spec.loader is not None, (
        f"{_ORM_SESSION_DB} is not there. It is the reference this file compares against; if it "
        f"moved, this comparison has to follow it rather than disappear."
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ORM = _load_orm_half()

_orm_scoped: Callable[[str, str | None], str] = _ORM.scoped
"""The ORM's rule, bound to a typed name: everything off a module object is `Any` otherwise."""

_ORM_VARIABLE: str = _ORM.SESSION_VARIABLE
_ORM_MARK: str = _ORM.MARK


def test_the_two_halves_read_the_same_variable() -> None:
    """Both sides ask `SNAKEORM_SESSION_ID`, so one exported value covers the whole repository.

    It goes first because everything else here depends on it. Two rules driven by two variables
    would agree perfectly on their names and still put the ORM's suite and the demos in different
    sessions — and `make frameworks-test`, which starts one run from inside another, is exactly where
    that would show up as two databases where there should be one.
    """
    assert SESSION_VARIABLE == _ORM_VARIABLE, (
        f"the demos read {SESSION_VARIABLE!r} and the ORM's suite reads {_ORM_VARIABLE!r}. One of "
        f"the two is switched by a variable nobody sets, and an unset session id means no isolation."
    )


def test_the_two_halves_use_the_same_mark() -> None:
    """`__s` on both sides, because the sweeper recognises leftovers by that exact shape.

    The sweep lives on the ORM's side and walks every database on the server, the demos' included.
    A mark that drifted here would not break the demos: it would make their abandoned databases
    invisible to the only thing that collects them, in green, for ever.
    """
    assert MARK == _ORM_MARK


@pytest.mark.parametrize(
    ("name", "session", "expected"),
    [
        ("snakeorm_db", "41287", "snakeorm_db__s41287"),
        ("shared_operations", "41287", "shared_operations__s41287"),
        ("django_demo", "7", "django_demo__s7"),
        ("flask", "7", "flask__s7"),
        ("snakeorm_db", None, "snakeorm_db"),
    ],
    ids=["orm", "shared", "django", "sqlite-file", "no-session"],
)
def test_the_two_halves_produce_the_same_name(
    name: str, session: str | None, expected: str
) -> None:
    """The same base and the same id give the same name on both sides — spelled out, not derived.

    The expected column is written here rather than computed from either half, so two copies that
    change together still have to change into something somebody meant. Two halves agreeing on the
    wrong answer is the one state a comparison test on its own cannot see.

    The `sqlite-file` case is not decoration: on SQLite a FILE is what the other engines call a
    database, and it goes through this same rule so that "one database per run" holds on three
    engines instead of two.
    """
    assert scoped(name, session) == expected
    assert _orm_scoped(name, session) == expected


@pytest.mark.parametrize(
    "session", ["", " ", "no-hyphens", "no.dots", "a" * 33, "acentuación", "a b"]
)
def test_the_two_halves_refuse_the_same_ids(session: str) -> None:
    """An id that cannot go in a database name stops BOTH sides, rather than being trimmed to fit.

    Refusing on one side and repairing on the other would be worse than either: the same exported
    value would give the ORM's suite a stopped run and the demos a database with a name nobody wrote.
    """
    with pytest.raises(SessionIdError):
        scoped("snakeorm_db", session)
    with pytest.raises(ValueError):  # noqa: PT011 - the ORM's own subclass, loaded by path
        _orm_scoped("snakeorm_db", session)


@pytest.mark.parametrize("session", ["", "no-hyphens", "a b"])
def test_the_two_halves_say_the_same_sentence_back(session: str) -> None:
    """Refusing alike is not enough: the two have to refuse with the SAME words.

    This project has already paid for the other shape of it — one complaint explained in two wordings
    across the sync/async seam, with a test that compared the SQL and let the message through for
    months — and answered it by comparing the message too. Whoever reads this one is looking at a
    stopped run and a variable they were sure was fine; the sentence is all they get.
    """
    with pytest.raises(SessionIdError) as here:
        scoped("snakeorm_db", session)
    with pytest.raises(ValueError) as there:  # noqa: PT011 - the ORM's own subclass
        _orm_scoped("snakeorm_db", session)

    assert str(here.value) == str(there.value)


# ---- Applying the rule twice, which is where the ORM's copy was measured to be wrong -------------


@pytest.mark.parametrize("session", ["41287", "7", "spike"])
def test_both_halves_are_idempotent(session: str) -> None:
    """Marking a name this run already marked changes nothing, on either side.

    THE ORM's COPY WAS NOT, and it is the most expensive thing in this mechanism's history. There the
    finished name is written back into `os.environ`, so a child process re-marked it and landed in
    `snakeorm_db__s41287__s41287` — its own database, not its parent's. The whole suite stayed green
    (3095 passed, 24 skipped) because nothing compared the two names; it was found on the SERVER.

    This side derives rather than rewriting, so it cannot produce that name with today's callers. It
    is pinned here anyway: a copy that is only correct because of how its callers happen to work goes
    wrong the first time a caller changes, and this file exists so that neither half has to be
    trusted to stay lucky.
    """
    once = scoped("flask_demo", session)

    assert scoped(once, session) == once
    assert _orm_scoped(once, session) == once
    assert once == f"flask_demo{MARK}{session}"


def test_both_halves_refuse_a_name_carrying_ANOTHER_session() -> None:
    """A foreign mark stops BOTH sides. Nesting invents a database; replacing steals one."""
    with pytest.raises(SessionIdError, match="already carries session"):
        scoped("flask_demo__s999", "41287")
    with pytest.raises(ValueError, match="already carries session"):  # noqa: PT011 - the ORM's subclass
        _orm_scoped("flask_demo__s999", "41287")


def test_both_halves_say_the_same_sentence_about_a_foreign_mark() -> None:
    """And they refuse it with the SAME words, like every other refusal these two share."""
    with pytest.raises(SessionIdError) as here:
        scoped("flask_demo__s999", "41287")
    with pytest.raises(ValueError) as there:  # noqa: PT011 - the ORM's subclass
        _orm_scoped("flask_demo__s999", "41287")

    assert str(here.value) == str(there.value)


# ---- And that the rule is actually APPLIED, not merely agreed on --------------------------------


def test_this_suite_is_running_on_a_database_of_its_own() -> None:
    """The database these tests provision carries THIS run's session id.

    Everything above compares two rules; this asks whether either of them was used. Without it the
    whole file could pass with `conftest.py` having quietly stopped calling `claim()` — the two
    halves still agreeing perfectly about a suffix nobody appends, and every run back to sharing
    `shared_operations` with no test anywhere the wiser.
    """
    from shared.tests.conftest import POSTGRES_DATABASE

    session = current()

    assert session is not None, (
        "this run has no session id, so `claim()` in conftest.py did not happen and the twenty-nine "
        "tables below are being dropped and recreated in a database every other run shares."
    )
    assert POSTGRES_DATABASE.endswith(f"{MARK}{session}"), (
        f"this suite is pointed at {POSTGRES_DATABASE!r}, which does not carry this run's session "
        f"({session}). Two runs at once are about to TRUNCATE each other's rows between tests."
    )


@pytest.mark.parametrize("framework", ["django", "flask", "fastapi"])
def test_each_demo_gets_a_database_of_its_own_too(framework: str) -> None:
    """The three apps carry the session as well, on whichever engine the `.env` picked.

    Asked through `connection_config`, which is what the demos actually connect with, so the answer
    covers the Postgres name, the MySQL name and the SQLite FILE without this test having to know
    which one is in play. On SQLite a file IS the database, and leaving it out would make "one
    database per run" a promise that held on two engines out of three.
    """
    from shared.config import connection_config

    session = current()
    assert session is not None

    assert f"{MARK}{session}" in connection_config(framework).name
