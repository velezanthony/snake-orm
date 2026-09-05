"""The gate that turns a silent skip into a failure is written TWICE, and this pins the two together.

`src/test/conftest.py` owns it for the ORM's suite and `shared/tests/conftest.py` owns it for this
one. They are two pytest runs with two roots and nothing importable between them, so the hook is
written out on both sides — that part is explained where it happens and is not what this file is
about.

WHAT THIS FILE IS ABOUT is that the PARSER was copied too, and a copy drifts. It already did: the
ORM's side was fixed to refuse `off` and this one still read it as ON, so somebody switching the net
off in the way that reads plainly off switched it on, in silence, on the only suite that proves the
concurrency operations. Nobody found out from a test; there was none to find out from.

Sharing the source was looked at and refused on the layout: `test` is importable in the ORM's run
only because `pythonpath = ["src"]` puts it there, and hatchling keeps it out of the wheel on
purpose. Pointing this suite at the ORM's test tree would mean the demos — which exist to show what
somebody gets from the PUBLISHED package — no longer build on the published package alone.

So the copy stays and this file makes it answerable. It reaches the ORM's parser by PATH, which is
something a test may do and the layout may not, and then asks both halves the same questions: the
same switch name, the same phrase, the same accepted values, the same refusals, and the same
sentence back.

**AND IT NEVER WRITES `SNAKEORM_REQUIRE_POSTGRES`. THAT IS THE POINT OF HOW IT IS BUILT.** The first
version of this file drove both parsers by `monkeypatch.setenv` on that very variable, which looked
obvious and killed the session: `conftest.py`'s hook reads the switch on EVERY report of EVERY test,
so it read `'1'` while this file was mid-parametrize, raised, and pytest died with an INTERNALERROR
that named the gate and blamed the environment. `make frameworks-test-shared` failed with the
database up and the port right.

A test may not mutate the global state the live net is reading over its shoulder. So the parser here
takes its value as an ARGUMENT and this file passes strings to it, and the ORM's — which still goes
to the environment itself, and whose file is not this suite's to edit — is pointed at a probe
variable no net anywhere reads. If somebody ever "simplifies" this back to setting the real switch,
this paragraph is what they owe an answer to.
"""

from __future__ import annotations

import importlib.util
import pathlib
from collections.abc import Callable
from types import ModuleType

import pytest

from shared.tests.conftest import (
    _FALSE,
    _STRICT_VARIABLE,
    _TRUE,
    NO_SERVER_REASON,
    _strict_from_value,
)

_ORM_CONFTEST = (
    pathlib.Path(__file__).resolve().parents[3] / "src" / "test" / "conftest.py"
)
"""The ORM suite's conftest, as a FILE. Four levels up: tests -> shared -> frameworks -> the repo."""

_PROBE_VARIABLE = "SNAKEORM_REQUIRE_POSTGRES_PARSER_PROBE"
"""The name this file points the ORM's parser at, and it is deliberately NOT the real switch.

The ORM's `_strict_mode` takes the variable NAME as its argument — it is tabulated by engine over
there — so it can be asked what it thinks of a string without that string ever landing on a switch
somebody's net is watching. Nothing reads this name: not the hook in this suite, not the ORM's, not
CI. It exists for the length of one parametrized case and is restored by `monkeypatch`.
"""


def _load_orm_conftest() -> ModuleType:
    """Imports the ORM's conftest by path, under a name of its own.

    By path and not by `import`, because there is no import that reaches it from here — which is the
    whole reason the parser is duplicated in the first place. Under a name of its own so pytest's
    own copy of that module, in its own run, is never the thing being touched.

    Reading it is side-effect free: the module defines constants, functions and one hook, and
    registering a hook is something the plugin manager does, not something importing does.
    """
    spec = importlib.util.spec_from_file_location("orm_suite_conftest", _ORM_CONFTEST)
    assert spec is not None and spec.loader is not None, (
        f"{_ORM_CONFTEST} is not there. The ORM suite's gate is the reference this file compares "
        f"against; if the file moved, this comparison has to follow it rather than disappear."
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ORM = _load_orm_conftest()

_orm_strict_mode: Callable[[str], bool] = _ORM._strict_mode
"""The ORM's parser, bound to a typed name: everything off a module object is `Any` otherwise."""

_ORM_SWITCH_BY_REASON: dict[str, tuple[str, tuple[str, ...]]] = _ORM._STRICT_BY_REASON
_ORM_NO_SERVER_REASON: str = _ORM.NO_SERVER_REASON
_ORM_TRUE: str = _ORM._TRUE
_ORM_FALSE: str = _ORM._FALSE


def _orm_verdict(value: str | None, monkeypatch: pytest.MonkeyPatch) -> bool:
    """What the ORM's parser makes of `value`, asked through the probe variable.

    The ORM's half reads the environment itself and its file is not this suite's to edit, so the
    value has to be in a variable for the question to be askable at all. It goes in the probe and
    never in the real switch, which is what keeps this file from shooting the session it runs in.
    """
    if value is None:
        monkeypatch.delenv(_PROBE_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(_PROBE_VARIABLE, value)
    return _orm_strict_mode(_PROBE_VARIABLE)


def test_the_two_gates_name_the_same_switch() -> None:
    """This copy reads the SAME environment variable the ORM tabulates for Postgres.

    It goes first because every other check here depends on it: comparing two parsers that read
    different variables would compare nothing. And it is the cheapest way for this copy to rot —
    the ORM's side keeps its switches in a table indexed by engine, so renaming one there is one
    edit, and this file, three directories away, would keep asking about a name nobody sets.
    """
    orm_variable, _keys = _ORM_SWITCH_BY_REASON[_ORM_NO_SERVER_REASON]

    assert _STRICT_VARIABLE == orm_variable, (
        f"This suite reads {_STRICT_VARIABLE!r} and the ORM's suite reads {orm_variable!r} for the "
        f"same engine. One of the two gates is now switched by a variable nobody sets, and it will "
        f"stay quiet about it: an unset switch is OFF."
    )


def test_the_two_gates_share_the_phrase_and_the_two_spellings() -> None:
    """The skip phrase and the `true`/`false` spellings are the same strings on both sides.

    The phrase is what makes a skip recognisable AS a missing server, and it is repeated verbatim
    rather than imported for the same reason the parser is. The spellings are the contract itself:
    one word per side, and anything else refused. If either drifts, the two nets stop covering the
    same thing while both keep reporting success.
    """
    assert NO_SERVER_REASON == _ORM_NO_SERVER_REASON
    assert (_TRUE, _FALSE) == (_ORM_TRUE, _ORM_FALSE)


@pytest.mark.parametrize(
    ("value", "strict"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        ("true", True),
        ("TRUE", True),
        ("True", True),
        ("  true  ", True),
        ("false", False),
        ("FALSE", False),
        ("False", False),
    ],
)
def test_the_two_gates_read_the_same_values_the_same_way(
    value: str | None, strict: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset, blank, `true` and `false` in any casing: both parsers give the SAME answer.

    The expected column is written out rather than derived from either side, so a change made in
    both copies at once still has to be a change somebody meant: two halves agreeing on the wrong
    answer is exactly the state a comparison test alone cannot see.
    """
    assert _strict_from_value(value) is strict
    assert _orm_verdict(value, monkeypatch) is strict


@pytest.mark.parametrize("value", ["1", "0", "yes", "no", "on", "off", "ture", "sí"])
def test_the_two_gates_refuse_the_same_values(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo stops BOTH runs instead of picking a side, and `off` is the one that already bit.

    Both defaults are wrong in the same way: reading an unknown value as on hides a switch somebody
    meant to turn off, and reading it as off hides the very skips these nets exist to make loud. The
    old parser here was a blacklist, so `off` fell through to ON — and a blacklist that only one of
    two copies has stopped being is worse than one both still have, because now it is a surprise.

    These are the values that made the first version of this file kill the session: they are refused
    LOUDLY, and the old version wrote them where the live hook would read them.
    """
    with pytest.raises(ValueError, match=value):
        _strict_from_value(value)
    with pytest.raises(ValueError, match=value):
        _orm_verdict(value, monkeypatch)


@pytest.mark.parametrize("value", ["1", "off", "sí"])
def test_the_two_gates_say_the_same_sentence_back(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing alike is not enough: the two have to refuse with the SAME words.

    This project already paid for the other shape of it — one complaint explained in two wordings on
    the sync/async seam, with a test that compared the SQL and let the message through for months —
    and answered it by comparing the message too. In an ORM whose doctrine is to shout, the message
    IS the product, and a gate has nothing else to hand back: whoever reads this one is looking at a
    red CI and a value they thought was a boolean.

    THE ONE LICENSED DIFFERENCE is the name of the switch, because the ORM's parser is being asked
    through the probe and says so. It is put back before comparing rather than trimmed off both
    sides: naming the variable is the useful half of that sentence, and the test above is what pins
    that the two gates name the same one in earnest.
    """
    with pytest.raises(ValueError) as here:
        _strict_from_value(value)
    with pytest.raises(ValueError) as there:
        _orm_verdict(value, monkeypatch)

    assert str(here.value) == str(there.value).replace(
        _PROBE_VARIABLE, _STRICT_VARIABLE
    )
