"""An empty parameter list must reach each DBAPI in the shape that library calls "no parameters".

`adapt_params` returned `tuple(...)`, so with no parameters it handed back `()`. Three of the four
DBAPIs this project drives treat `()` as "here are your parameters, now re-read the SQL as a format
template", and only `None` means "there are none". So any statement carrying a literal `%` — which
is every one the migration runner emits, since DDL cannot be parametrised — blew up before it ever
reached the server.

Measured on this machine, and the answers do NOT agree, which is why this is a per-driver flag and
not a blanket `or None`:

    psycopg 3   ()  -> ProgrammingError: only '%s', '%b', '%t' are allowed as placeholders
                None -> fine
    PyMySQL     ()  -> TypeError: not enough arguments for format string
                None -> fine
    sqlite3     ()  -> fine
                None -> ProgrammingError: parameters are of unsupported type

sqlite3 is the one that makes the naive fix wrong: it REFUSES `None`. A driver has to answer for
itself, which is exactly the reasoning `native_arrays` already carries in this same function.

What this closes is the EMPTY case. A `%` alongside real parameters is still the caller's business —
that is why `MOD` is not in the capability catalogue.
"""

from __future__ import annotations

import pytest

from snakeorm.sql.adapt import adapt_params


def test_no_parameters_becomes_none_where_the_driver_reformats() -> None:
    """psycopg and PyMySQL re-read the SQL as a template unless the argument is `None`."""
    assert adapt_params((), native_arrays=True, percent_formatting=True) is None
    assert adapt_params((), native_arrays=False, percent_formatting=True) is None


def test_no_parameters_stays_an_empty_tuple_where_none_is_refused() -> None:
    """sqlite3 rejects `None` outright, so for it the empty tuple IS the right answer.

    This is the half a blanket `or None` gets wrong, and it fails loudly rather than subtly — which
    is the only reason it would have been caught at all.
    """
    assert adapt_params((), native_arrays=False, percent_formatting=False) == ()


@pytest.mark.parametrize("percent_formatting", [True, False])
def test_real_parameters_are_never_turned_into_none(percent_formatting: bool) -> None:
    """The floor: only the EMPTY case changes. A statement with values keeps its tuple.

    Without this, "return None when there are no parameters" could be implemented as "return None"
    and every other assertion here would still hold.
    """
    adapted = adapt_params(
        (1, "x"), native_arrays=True, percent_formatting=percent_formatting
    )

    assert adapted == (1, "x")


def test_every_driver_answers_the_question_for_itself() -> None:
    """`percent_formatting` has no default, and that is deliberate.

    Same reasoning `native_arrays` already carries in this function: a new driver has to ANSWER,
    and answering wrong shows up immediately. With a default, the driver that forgot would inherit
    another library's behaviour — and here the two possible answers are "blows up on a literal
    percent" and "blows up on every statement".
    """
    with pytest.raises(TypeError, match="percent_formatting"):
        adapt_params((), native_arrays=True)  # type: ignore[call-arg]
