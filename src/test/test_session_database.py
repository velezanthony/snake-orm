"""The rules `session_db` decides a database name by, asked without a server in the way.

Everything here is a pure function of strings and PIDs, which is why it lives outside `integration/`:
the naming rule, the refusals, and — the one that authorises a `DROP DATABASE` — how a name is
judged abandoned. The proof that two runs actually land in two different databases needs a real
server and lives in `integration/test_session_database_isolation.py`.

WHAT THE EXPECTED VALUES ARE WRITTEN OUT FOR. They are spelled here rather than derived from
`session_db`, so a change made to the rule still has to be a change somebody meant. A test that
computes its expectation the same way the code does agrees with any answer, including the wrong one.
"""

from __future__ import annotations

import os
import re

import pytest

from test import session_db


def test_a_name_with_no_session_is_the_name_itself() -> None:
    """No session id, no suffix — and that is the case a dev server and a `psql` live in.

    It is the default and it has to stay the default. If this ever started inventing an id, `make
    flask-dev` would come up on an empty database every restart and the seeded demo would look
    broken, which is a worse failure than the one being prevented because it happens to people who
    were not running tests at all.
    """
    assert session_db.scoped("snakeorm_db", None) == "snakeorm_db"


def test_a_session_id_lands_at_the_end_behind_two_underscores() -> None:
    """`snakeorm_db` + `41287` is `snakeorm_db__s41287`, spelled out.

    TWO underscores, because every base name in this repository already contains one:
    `snakeorm_db`, `shared_operations`, `django_demo`. With a single one, `_s12` would be
    indistinguishable from a name somebody meant, and the sweeper is allowed to DROP what it
    recognises.
    """
    assert session_db.scoped("snakeorm_db", "41287") == "snakeorm_db__s41287"


def test_two_sessions_never_get_the_same_name() -> None:
    """Different ids, different databases. The whole mechanism is this one line being true."""
    assert session_db.scoped("snakeorm_db", "1") != session_db.scoped(
        "snakeorm_db", "2"
    )


def test_a_scoped_name_says_which_session_it_belongs_to() -> None:
    """The rule read backwards, which is the only way the sweeper can tell whose database it is."""
    assert session_db.session_of("snakeorm_db__s41287") == "41287"


@pytest.mark.parametrize(
    "name", ["snakeorm_db", "django_demo", "shared_operations", "postgres", "s41287"]
)
def test_a_name_nobody_scoped_belongs_to_nobody(name: str) -> None:
    """A plain database name answers `None`, and that answer is what keeps it alive.

    These are the names on the server that somebody created on purpose. Everything downstream of
    this function ends in a `DROP DATABASE`, so the interesting direction is not that it recognises
    its own names — it is that it refuses to recognise anybody else's.
    """
    assert session_db.session_of(name) is None


@pytest.mark.parametrize(
    "session", ["", " ", "no-hyphens", "no.dots", "a" * 33, "acentuación", "a b"]
)
def test_an_id_that_cannot_go_in_a_database_name_is_refused_by_name(
    session: str,
) -> None:
    """A bad id STOPS the run and says what it was. It is never trimmed into something legal.

    Quietly stripping the character it did not like would hand somebody a database whose name they
    never wrote, and they would then go looking for the one they did — the same reason
    `SNAKEORM_REQUIRE_POSTGRES` refuses `off` instead of translating it. Thirty-three characters is
    over the ceiling: a database name has 63 in Postgres and 64 in MySQL, and the base has to fit too.
    """
    with pytest.raises(session_db.SessionIdError, match=re.escape(repr(session))):
        session_db.scoped("snakeorm_db", session)


def test_the_refusal_names_the_variable_the_value_came_from() -> None:
    """Whoever reads it is looking at a stopped run and a variable they thought was fine.

    Naming the value back proves it was READ; naming `SNAKEORM_SESSION_ID` is what lets them fix it
    without going to find this file.
    """
    with pytest.raises(session_db.SessionIdError) as refusal:
        session_db.scoped("snakeorm_db", "not valid")

    assert session_db.SESSION_VARIABLE in str(refusal.value)


# ---- Applying the rule twice ---------------------------------------------------------------------
#
# `open_session` writes the finished name back into `os.environ`, so a CHILD process reads a name
# that is already marked and runs the rule over it a second time. Marking twice produced
# `snakeorm_db__s41287__s41287` and sent every child to a database of its own — with the whole suite
# green (3095 passed, 24 skipped), because nothing anywhere compared the two names. It was found by
# looking at the SERVER. These are the cases that would have found it in a tenth of a second.


def test_marking_a_name_this_run_already_marked_changes_nothing() -> None:
    """Applied twice with the SAME id, the answer is the same name. Not a longer one.

    The property is idempotence and the value of writing it out is that the broken answer,
    `snakeorm_db__s41287__s41287`, is a perfectly plausible-looking database name. Nothing about it
    reads as wrong until you notice a run is not where its parent is.
    """
    once = session_db.scoped("snakeorm_db", "41287")

    assert session_db.scoped(once, "41287") == "snakeorm_db__s41287"
    assert session_db.scoped(session_db.scoped(once, "41287"), "41287") == once


def test_marking_a_name_that_carries_ANOTHER_session_is_refused() -> None:
    """A foreign mark STOPS the run instead of nesting or replacing. Both of those are wrong.

    The two cases only look alike. This run's own mark means the name has been through here already.
    Somebody else's means this process is holding a name from an environment that is not its own —
    and nesting invents a third database nobody owns, while replacing steals a name from a run that
    may still be alive.

    It is not hypothetical: `test_session_database_isolation` simulated "another run" by clearing
    the session id and leaving the marked `DB_NAME` behind, and this is what told it that no real
    run can be in that state.
    """
    with pytest.raises(session_db.SessionIdError, match="already carries session"):
        session_db.scoped("snakeorm_db__s999", "41287")


def test_the_refusal_names_BOTH_sessions() -> None:
    """Whoever reads it needs the name they found and the run they are — the fix is knowing both."""
    with pytest.raises(session_db.SessionIdError) as refusal:
        session_db.scoped("snakeorm_db__s999", "41287")

    assert "'999'" in str(refusal.value)
    assert "'41287'" in str(refusal.value)


def test_a_double_mark_is_still_recognisable_afterwards() -> None:
    """The databases the bug left behind can still be identified, which is how they get collected.

    `.+` is greedy, so `snakeorm_db__s41287__s41287` answers with the LAST mark. That is what lets
    the sweep treat one as an ordinary orphan and drop it, instead of it needing a person and a
    `psql`. Written down because it is the difference between a bug that left rubbish and a bug that
    left rubbish nothing can see.
    """
    assert session_db.session_of("snakeorm_db__s41287__s41287") == "41287"
    assert session_db.session_of("snakeorm_db__s7__s7__s7") == "7"
    assert session_db.is_orphan("snakeorm_db__s4194303__s4194303")


def test_the_dsn_rewrite_is_idempotent_too() -> None:
    """`scoped_dsn` had the twin defect and is fixed by the same rule, not by a second one.

    It goes through `scoped`, so proving it here is proving that it delegates rather than repeating
    the concatenation itself — which is the only way the two could ever disagree again.
    """
    once = session_db.scoped_dsn("dbname=snakeorm_analytics", "7")

    assert once == "dbname=snakeorm_analytics__s7"
    assert session_db.scoped_dsn(once, "7") == once


def test_a_dsn_carrying_another_session_is_refused_as_well() -> None:
    """The refusal travels through the DSN form too: one rule, two spellings of the same name."""
    with pytest.raises(session_db.SessionIdError, match="already carries session"):
        session_db.scoped_dsn("dbname=snakeorm_analytics__s999", "7")


def test_every_variable_open_session_writes_is_published() -> None:
    """`REWRITTEN` names them all, so undoing the rewrite is possible without guessing a list.

    A process that wants to look like a FRESH run has to clear every one of them; clearing a subset
    leaves names marked with an id that is no longer there, which is the state the refusal above
    exists to catch. Derived from the table rather than written out, so the variable added last is
    not the one somebody forgets.
    """
    assert session_db.SESSION_VARIABLE in session_db.REWRITTEN
    assert session_db.ANALYTICS_DSN_VARIABLE in session_db.REWRITTEN
    for variable, _fallback in session_db.SCOPED_NAME_VARIABLES:
        assert variable in session_db.REWRITTEN


# ---- Who may be swept ---------------------------------------------------------------------------


def test_a_database_owned_by_a_live_process_is_not_an_orphan() -> None:
    """The PID of the process asking is alive by definition, so its own database survives.

    This is the case that matters most and the cheapest one to get wrong: a sweep that collected
    live sessions would be strictly worse than no sweep, because it would cause exactly the failure
    it was written to prevent, from inside the mechanism meant to prevent it.
    """
    mine = session_db.scoped("snakeorm_db", str(os.getpid()))

    assert not session_db.is_orphan(mine)


def test_a_database_owned_by_a_process_that_is_gone_is_an_orphan() -> None:
    """A PID nothing is running under is a database nobody is coming back for.

    PID 1 is `init` and always alive, so the dead one is chosen at the far end of the range: on Linux
    the default ceiling is 4194304, and 4194303 is above what any of these `pytest` processes will
    have been given.
    """
    abandoned = session_db.scoped("snakeorm_db", "4194303")

    assert session_db.is_orphan(abandoned)


@pytest.mark.parametrize("name", ["snakeorm_db", "postgres", "shared_operations"])
def test_a_database_nobody_scoped_is_never_an_orphan(name: str) -> None:
    """The server's real databases are invisible to the sweep. This is the guard on the sweep."""
    assert not session_db.is_orphan(name)


def test_a_hand_written_session_id_is_never_swept() -> None:
    """`SNAKEORM_SESSION_ID=spike` survives every sweep, and the asymmetry is honest.

    Only a PID has a heartbeat; there is nothing to ask about a word. Whoever pins an id owns its
    database, which is usually why they pinned one. The default id is a PID precisely so that the
    common case is collectable without anybody arranging it.
    """
    assert not session_db.sweepable("spike")
    assert not session_db.is_orphan(session_db.scoped("snakeorm_db", "spike"))
    assert session_db.sweepable("41287")


# ---- The DSN of the second named connection -----------------------------------------------------


@pytest.mark.parametrize(
    ("dsn", "expected"),
    [
        (
            "host=127.0.0.1 port=5434 user=postgres dbname=snakeorm_analytics",
            "host=127.0.0.1 port=5434 user=postgres dbname=snakeorm_analytics__s7",
        ),
        (
            "postgresql://postgres@127.0.0.1:5434/snakeorm_analytics",
            "postgresql://postgres@127.0.0.1:5434/snakeorm_analytics__s7",
        ),
    ],
    ids=["keyword", "url"],
)
def test_the_named_connection_follows_its_run_too(dsn: str, expected: str) -> None:
    """`SNAKEORM_DSN_ANALYTICS` is scoped as well, in either form libpq accepts.

    It is the one surface the `DB_NAME` rewrite cannot reach, because its database is spelled inside
    a whole DSN instead of in a variable of its own. Left alone it would have been one shared table
    —`shop_visits`, dropped and recreated by `test_full_flow_e2e`— under a mechanism claiming to
    have closed the sharing, which is worse than a hole nobody claimed to have closed.
    """
    assert session_db.scoped_dsn(dsn, "7") == expected


def test_a_dsn_that_names_no_database_stops_the_run() -> None:
    """An unreadable DSN raises instead of being handed back untouched.

    Passing it through would be this whole module's failure wearing a helpful face: the run carries
    on, quietly sharing the one database nobody thought to check, with nothing anywhere saying so.
    """
    with pytest.raises(session_db.SessionIdError, match="names no database"):
        session_db.scoped_dsn("host=127.0.0.1 port=5434", "7")


def test_a_dsn_with_no_session_is_left_exactly_as_it_was() -> None:
    """No session, no rewrite — including for a DSN this could not have parsed anyway."""
    assert session_db.scoped_dsn("host=127.0.0.1", None) == "host=127.0.0.1"
