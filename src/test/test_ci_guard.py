"""The net that prevents silent skips has, itself, a way of failing silently.

`test/conftest.py` turns the skip of a test that needed a database into a failure, and to recognise
it, it looks at the REASON: the phrase the whole repo uses to announce that there is no server. That
is a convention, and conventions erode — the day somebody writes "no Postgres here" instead of
"Postgres is not reachable", that test drops out of the net and **nobody will notice**, because CI will
stay green. Which is exactly the state the net existed to make impossible.

A safeguard that can stop working without warning is not a safeguard. This ties it to the real test
tree.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass

import pytest

from test.conftest import (
    _STRICT_BY_REASON,
    NO_MYSQL_REASON,
    NO_SERVER_REASON,
    _connection_advice_for,
    _skipped_for_lack_of_server,
    _strict_mode,
)

_ROOT = pathlib.Path(__file__).resolve().parent


_SHARED_REASONS = ("NO_SERVER_REASON", "NO_MYSQL_REASON")
"""The names of the two constants a skip may announce itself with. Anything else is a phrase of
one's own, and a phrase of one's own is invisible to `_STRICT_BY_REASON`."""


@dataclass(frozen=True, slots=True)
class _SkipCall:
    """One `pytest.skip(...)` invocation: where it is, what it says, and what names it says it with."""

    path: pathlib.Path
    line: int
    reason: str
    names: frozenset[str]

    @property
    def where(self) -> str:
        """`folder/file.py:line` — the call, not the file, because the call is the unit here."""
        return f"{self.path.relative_to(_ROOT)}:{self.line}"

    @property
    def excuse_key(self) -> str:
        """File AND wording, so an excuse covers ONE motive and never a whole file."""
        return f"{self.path.relative_to(_ROOT)}::{self.reason}"


_NOT_A_SERVER_SKIP: dict[str, str] = {
    "migration/test_emitter_dialect_matrix.py::this SQLite cannot: {} (`realize` stops it)": "a "
    "DECLARED capability (`Cap` says Nope), not a missing server: that skip is the correct "
    "outcome and turning it into a failure would demand every engine do everything. It says THIS "
    "SQLite because the answer moved: `Since` grants the CHECK from 3.53, so the same skip fires "
    "on 3.46 and not on 3.53",
    "migration/test_emitter_dialect_matrix.py::this SQLite gained it: {} (the other test runs it)": (
        "the mirror of the one above: the engine in front of us HAS the capability, so the control "
        "for what it cannot do has nothing to control. The other half of the matrix executes it"
    ),
    "migration/test_emitter_dialect_matrix.py::MySQL cannot: {}": "the same, for MySQL",
    "integration/test_hunt_roundtrip.py::ruff is not on the PATH": "a missing TOOL and not a "
    "missing database: no container brings `ruff` back",
    "migration/test_emitter_dialect_matrix.py::{} cannot: {}": "the executed half of the matrix, "
    "and the reason is always DECLARED --either a capability the engine does not have, or a fixture "
    "that deliberately holds no view because a view blocks ALTER COLUMN on PostgreSQL. Every one of "
    "them names where it IS covered; none of them is a missing server",
    "integration/test_maths_functions_e2e.py::SQLite built without ENABLE_MATH_FUNCTIONS: {}": "a "
    "property of the BINARY and not of a server. SQLite's maths are a compile-time option, so this "
    "cannot be a `Cap` either --a capability is answered by the dialect CLASS, which does not know "
    "which library got linked. No container brings `ceil` back",
}
"""The `pytest.skip` CALLS whose reason is not a missing server, keyed by file AND wording.

**Per call, never per file.** This table used to hold three file NAMES, and a file name is a
whitelist of the wrong granularity: it covers more than it was written to cover. Measured — an AST
sweep of all 69 `pytest.skip` calls under `src/test/` found 5 announcing a phrase of their own, four
of them legitimate and one a hole: `integration/test_full_flow_e2e.py` skipped on an unreachable
`analytics` database with a sentence of its own, inside a file the old table excused by name for a
reason that had nothing to do with that call. The excuse was written for the capability skips; the
server skip inherited it for free.

This repository has already paid for this exact shape once: `debug/channel.py`
sat in the bilingual exemption list without a single `SnakeDebugLanguage` in it, and underneath lived a
`SnakeConfigError` in Spanish that a user hits on startup. **An exemption that covers too much is an
exemption that hides.** The granularity of the excuse has to match the granularity of the thing being
excused, and the thing being excused is a skip — not a file.

The key is the wording rather than the line number on purpose: a line number goes stale on the next
edit and would have to be maintained, whereas the wording IS the motive, which is what a reader is
being asked to accept. `{}` stands where the call interpolates a value.
"""


def _reason_of(call: ast.Call) -> str:
    """The literal wording of the skip's reason, with `{}` where a value gets interpolated.

    Static text and not the runtime message: this net reads the tree, so what it can see is what the
    author WROTE. That is also the honest thing to key an excuse on — a person reviewing the table
    is agreeing to a sentence, not to a line number.
    """
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return argument.value
        if isinstance(argument, ast.JoinedStr):
            pieces: list[str] = []
            for part in argument.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    pieces.append(part.value)
                else:
                    pieces.append("{}")
            return "".join(pieces)
    return ""


def _skip_calls(root: pathlib.Path) -> list[_SkipCall]:
    """Every `pytest.skip(...)` under `root`, one entry PER CALL, found by parsing.

    Two widenings over the version that went by file, and both were holes. It walks `*.py` and no
    longer `test_*.py`, because `scenarios/conftest.py` skips for want of a server and every test in
    that folder rides on it; and it yields one record per invocation, because a file is free to skip
    twice for two different motives — which is precisely what `test_full_flow_e2e.py` did.

    `ast` and not `in text`: how a file spells its connection is its own business, and making the net
    depend on that spelling is what let twenty files out of it once already.
    """
    found: list[_SkipCall] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            attribute = func.attr if isinstance(func, ast.Attribute) else None
            plain = func.id if isinstance(func, ast.Name) else None
            if "skip" not in (attribute, plain):
                continue
            names = frozenset(
                child.id for child in ast.walk(node) if isinstance(child, ast.Name)
            )
            found.append(_SkipCall(path, node.lineno, _reason_of(node), names))
    return found


def _skips_for_want_of_a_server() -> list[_SkipCall]:
    """Every skip whose motive IS a missing server: all of them minus the excused calls."""
    return [
        call for call in _skip_calls(_ROOT) if call.excuse_key not in _NOT_A_SERVER_SKIP
    ]


def test_there_are_tests_that_need_a_real_server() -> None:
    """The net is worthless with no fish: if nobody skips, this file measures nothing."""
    calls = _skips_for_want_of_a_server()

    assert len(calls) >= 40, f"only {len(calls)} skips depend on a real server"


@pytest.mark.parametrize("call", _skips_for_want_of_a_server(), ids=lambda c: c.where)
def test_every_one_of_them_announces_it_with_the_agreed_wording(
    call: _SkipCall,
) -> None:
    """Every skip CALL announces itself with the SHARED CONSTANT — imported, not spelt out.

    The unit is the call, and that correction is the whole point of this version. Asking the question
    of the FILE («does the word NO_SERVER_REASON appear anywhere in it?») answers a different question
    from the one being asked: a file that imports the constant for nineteen of its skips passes while
    the twentieth invents a sentence. Measured, that was not hypothetical —
    `integration/test_full_flow_e2e.py` skipped on an unreachable `analytics` database with a phrase of
    its own, and the file was excused by name anyway.

    It caught a real hole the moment it was first written: `test/migration/test_atomicity.py` and
    `test_data_migration_integration.py` need a server and were outside the version before it, which
    went by folders. They are the atomicity and data-migration tests: among the ones it hurts most not
    to run.

    The demand is the NAME and not the text. Fifty-three files each carried their own copy of the
    phrase, so the wording was a convention held by everybody agreeing — and twenty of them had
    drifted to "there is no Postgres available", which the runtime check did not recognise. Importing
    one constant makes the agreement structural: there is nothing left to spell differently.
    """
    # Either shared constant: MySQL has its own phrase and its own switch, and a skip that needs
    # THAT server is covered by naming it. What is not allowed is a phrase of one's own.
    used = call.names & frozenset(_SHARED_REASONS)

    assert used, (
        f"{call.where} skips for want of a server without naming NO_SERVER_REASON or "
        f"NO_MYSQL_REASON, so the net in test/conftest.py does NOT cover it: with the database down "
        f"and the strict switch on, this test skips in green. Import the constant for the engine it "
        f"needs instead of writing the phrase — or, if the motive is genuinely not a missing server, "
        f"add THIS CALL to _NOT_A_SERVER_SKIP with the motive written out. Never the whole file."
    )
    assert NO_SERVER_REASON not in call.reason, (
        f"{call.where} writes the phrase out instead of importing it. A copy is a convention held "
        f"by everybody remembering, and twenty files had already drifted."
    )
    assert NO_MYSQL_REASON not in call.reason, (
        f"{call.where} writes the MySQL phrase out instead of importing it, with the same effect."
    )


def test_no_excuse_covers_a_call_that_is_no_longer_there() -> None:
    """A stale excuse is a hole waiting to be reused: every key has to match a real call.

    This is the guard on the guard. The table it protects grants exemptions, and an exemption whose
    call has been deleted or rephrased stops being an exemption and becomes a trap with a name on it
    — the next skip that happens to land on that wording inherits a permission nobody granted it.
    Since the key is the file plus the wording, editing either one retires the excuse loudly here
    rather than quietly widening it.
    """
    live = {call.excuse_key for call in _skip_calls(_ROOT)}

    stale = sorted(set(_NOT_A_SERVER_SKIP) - live)

    assert not stale, (
        f"these excuses in _NOT_A_SERVER_SKIP match no `pytest.skip` call any more: {stale}. "
        f"Delete them — an excuse that outlives its call covers whatever moves in next."
    )


@pytest.mark.parametrize(
    ("value", "strict"),
    [
        (None, False),
        ("", False),
        ("false", False),
        ("FALSE", False),
        ("true", True),
        ("TRUE", True),
    ],
)
def test_the_switch_reads_the_environment_the_way_a_human_would_write_it(
    value: str | None, strict: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset and empty are off; the rest is a BOOLEAN, read case-insensitively.

    It matters because the value is written by a CI YAML, where `false` ends up being the string
    `"false"`. Treating it as true just for being a non-empty string would turn strict mode on
    exactly where it was asked to be off, and the tests would fail for no apparent reason.

    THIS LIST USED TO END WITH `("sí", True)`, and that entry was the contract rather than a
    curiosity: anything that was not one of three known spellings counted as ON. It made the parser a
    blacklist, so `off` — which reads to a person as plainly off — switched the net on. Now both
    sides are written out and anything else is refused by name; the cases for that are below.
    """
    if value is None:
        monkeypatch.delenv("SNAKEORM_REQUIRE_POSTGRES", raising=False)
    else:
        monkeypatch.setenv("SNAKEORM_REQUIRE_POSTGRES", value)

    assert _strict_mode() is strict


def test_it_tells_apart_a_missing_server_from_any_other_reason_to_skip() -> None:
    """Only skips caused by a missing server become failures. The rest are legitimate.

    A unit test may skip because the dialect does not support a capability, and turning that into a
    failure would be noise dressed up as rigour: the net would stop being read within two weeks.
    """

    class _Report:
        def __init__(self, text: str) -> None:
            self.longrepr = text

    assert _skipped_for_lack_of_server(_Report(f"Skipped: {NO_SERVER_REASON}: refused"))
    assert not _skipped_for_lack_of_server(
        _Report("Skipped: SQLite no soporta FOR UPDATE")
    )


def test_the_failure_names_the_variables_of_the_ENGINE_that_was_missing() -> None:
    """A MySQL failure has to point at `MYSQL_*`, not at the Postgres variables.

    It used to point at `DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME` whichever engine had gone
    missing, because the wording was written when there was only one gate. So the person who finally
    turned the MySQL switch on was sent to check the connection of a database that was up — the
    worst shape a diagnostic takes, since following it proves everything is fine.

    This is the same failure the file it guards was written about, one level up: a safeguard can be
    working perfectly and still say something that costs somebody an afternoon.
    """
    for reason, expected, forbidden in (
        (NO_MYSQL_REASON, "MYSQL_HOST", "DB_HOST"),
        (NO_SERVER_REASON, "DB_HOST", "MYSQL_HOST"),
    ):
        advice = _connection_advice_for(reason)
        assert expected in advice, f"{reason} -> {advice}"
        assert forbidden not in advice, f"{reason} named the other engine: {advice}"


@pytest.mark.parametrize("value", ["true", "TRUE", "True"])
def test_only_true_switches_it_on(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`true`, in any casing, and NOTHING else — not `yes`, not `on`, not `1`.

    One spelling per side is the whole point. Every extra synonym is another thing a reader has to
    know is equivalent, and the moment there are six the question stops being "is it on?" and becomes
    "is MY word on the list?" — which is how `off` came to switch the net on.
    """
    monkeypatch.setenv("SNAKEORM_REQUIRE_POSTGRES", value)

    assert _strict_mode() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "False"])
def test_only_false_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`false`, in any casing. `off`, `no` and `0` are refused rather than translated.

    `off` is the one that used to bite: the old parser was a blacklist —`0`, `false` and `no` meant
    off and ANYTHING else meant on— so switching the net off with a spelling it did not know did the
    opposite, in silence. Refusing it is better than adding it to a list, because the next person
    will reach for `disabled`.
    """
    monkeypatch.setenv("SNAKEORM_REQUIRE_POSTGRES", value)

    assert _strict_mode() is False


@pytest.mark.parametrize("value", ["1", "0", "yes", "no", "on", "off", "ture", "sí"])
def test_anything_that_is_not_true_or_false_is_refused_by_name(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo must SHOUT rather than pick a side, because both sides are wrong.

    Guessing `on` hides a switch somebody meant to turn off; guessing `off` hides the very skips this
    net exists to surface. Neither is a safe default, so there is no default: the value is named back
    and the run stops.
    """
    monkeypatch.setenv("SNAKEORM_REQUIRE_POSTGRES", value)

    with pytest.raises(ValueError, match=value):
        _strict_mode()


# ---- The switches are read once, at startup ------------------------------------------------------
#
# WHAT WAS WRONG, SAID PROPERLY, because the wrong version of this paragraph was written first and
# somebody reading it in a year would come away believing the gate had been broken. IT HAD NOT. The
# net never failed open: measured, `SNAKEORM_REQUIRE_POSTGRES=ture` with the database DOWN raised and
# stopped the run. A typo could not quietly disable it.
#
# What it did wrong was WHEN and HOW it complained.
#
# WHEN: only the first time something skipped for want of a server — that is, the day the database
# went down. So you asked for a clear signal about the DATABASE and got one about your shell. The two
# failures arrive together and the loud one is not the one you need.
#
# HOW: as an INTERNALERROR, because a `ValueError` out of `pytest_runtest_makereport` is an exception
# inside a hook. pytest dies there: no summary, no tally, no test named, the traceback pointing at
# the safeguard rather than at the environment. In an ORM whose doctrine is that the MESSAGE is the
# product, being right in that shape is the worst way to be right.
#
# So the value is now validated once, in `pytest_configure`, before a single test is collected. The
# hook's own reading stays lazy and stays correct: by the time it runs, the value is known good.

_SWITCHES: tuple[str, ...] = tuple(
    variable for variable, _keys in _STRICT_BY_REASON.values()
)
"""Every engine switch, taken FROM the table rather than written out here for a second time.

`_STRICT_BY_REASON` is the one place that says which engines have a gate. A list copied into this
file would go stale the day a fourth engine arrives — and it would go stale QUIETLY, which is the
exact failure mode this whole file exists to make impossible.
"""

_PROJECT_ROOT = _ROOT.parents[1]
"""The repo root: `src/test` -> `src` -> here. Where a pytest run finds the `pyproject.toml`."""


def _pytest_with(**switches: str | None) -> subprocess.CompletedProcess[str]:
    """A SEPARATE pytest run, collection only, with the switches set to what is asked.

    In another process on purpose, and this is the lesson the sibling gate in `frameworks/` paid
    for: what is under test here is what the session does while STARTING, and a test cannot ask
    that of the session it is already inside. `monkeypatch.setenv` on a live switch is worse than
    useless — it is what killed a suite once already.

    `--collect-only` because the abort has to happen BEFORE collection: if a single test is
    collected, the gate did not stop anything, whatever it printed. Every switch is cleared first so
    the answer never depends on what the person running the suite happens to export.
    """
    environment = dict(os.environ)
    for name in _SWITCHES:
        environment.pop(name, None)
    for name, value in switches.items():
        if value is not None:
            environment[name] = value
    return subprocess.run(  # noqa: S603 - fixed command, no user input
        [
            sys.executable,
            "-m",
            "pytest",
            str(_ROOT / "test_ci_guard.py"),
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _output_of(result: subprocess.CompletedProcess[str]) -> str:
    """Both streams together: which one a `UsageError` lands on is pytest's business, not ours."""
    return f"{result.stdout}\n{result.stderr}"


@pytest.mark.parametrize("variable", _SWITCHES)
def test_a_typo_in_any_switch_stops_the_run_before_a_single_test(variable: str) -> None:
    """A value that is not a boolean aborts at startup, cleanly, naming variable and value.

    ANY of the switches, driven off the table: the gate that gets forgotten is the one for the
    engine added last, which is how the MySQL half came to be missing from CI in the first place.

    Three things are asserted and each is a separate way this went wrong before: that the exit code
    is the CONFIGURATION one (a run that stops for a bad setting is not a run that failed tests),
    that nothing was collected (an abort that lets the suite start is not an abort), and that the
    word INTERNALERROR does not appear (that was the whole complaint).
    """
    result = _pytest_with(**{variable: "ture"})
    output = _output_of(result)

    assert result.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert f"ERROR: {variable}='ture'" in output, output
    assert "INTERNALERROR" not in output, output
    assert "collected" not in output, output


def test_the_abort_says_what_it_would_have_accepted() -> None:
    """The complaint carries the two spellings, so the fix is in the message and not in a file.

    Whoever reads this is looking at a red CI and a variable they were sure was a boolean. Naming
    the value back proves it was READ; naming `true` and `false` is what lets them fix it without
    going to find the parser. It is the same sentence the parser raises — one wording, not two.
    """
    variable = _SWITCHES[0]
    output = _output_of(_pytest_with(**{variable: "ture"}))

    assert "'true'" in output, output
    assert "'false'" in output, output
    assert "leave it unset" in output, output


def test_every_bad_switch_is_named_in_the_SAME_abort() -> None:
    """Two typos are reported together, not one run at a time.

    Stopping at the first would make a person fix one, run again, and find the other — paying a
    whole start-up per mistake to learn something the first run already knew. The gate has read
    every switch by then; saying so costs nothing.
    """
    output = _output_of(_pytest_with(**dict.fromkeys(_SWITCHES, "nope")))

    for variable in _SWITCHES:
        assert f"ERROR: {variable}='nope'" in output, output


@pytest.mark.parametrize("value", ["true", "false", None])
def test_a_good_value_or_none_at_all_starts_the_run_without_a_word(
    value: str | None,
) -> None:
    """`true`, `false` and absent: the run starts and the gate says NOTHING.

    The half that is easy to forget. A validation that also fires on good input teaches people to
    scroll past it, and a gate nobody reads is a gate that is not there — the same way the skip
    tally nobody reads is what made this whole file necessary.
    """
    result = _pytest_with(**dict.fromkeys(_SWITCHES, value))
    output = _output_of(result)

    assert result.returncode == pytest.ExitCode.OK, output
    assert "ERROR:" not in output, output


def _workflow_jobs() -> list[tuple[str, str, dict[str, object]]]:
    """Every job of every workflow, as `(file, job name, job body)`.

    A glob over `.github/workflows/` and not one hand-written path, for the same reason `_SWITCHES`
    is derived: a second workflow added tomorrow would be outside a hard-coded name and nothing
    would say so. `_skip_calls` above already walks a tree rather than a list.
    """
    import yaml

    jobs: list[tuple[str, str, dict[str, object]]] = []
    for path in sorted((_PROJECT_ROOT / ".github" / "workflows").glob("*.yml")):
        document = yaml.safe_load(path.read_text())
        for name, body in (document.get("jobs") or {}).items():
            if isinstance(body, dict):
                jobs.append((path.name, name, body))
    return jobs


def _jobs_that_bring_an_engine_up() -> list[tuple[str, str, dict[str, object]]]:
    """The jobs that start a database container.

    `services:` is the STRUCTURAL signal, and it was chosen over looking for `pytest` in the `run:`
    steps: that would have declared the `frameworks` job free of tests, and it runs `manage.py test`
    against a live engine.
    """
    return [job for job in _workflow_jobs() if job[2].get("services")]


def test_the_workflow_still_has_jobs_that_bring_an_engine_up() -> None:
    """The floor under the test below: an empty sweep parametrises to nothing and passes.

    Without this, deleting the `services:` blocks would make the switch check vacuously true —
    which is the same silence the check exists to break.
    """
    assert _jobs_that_bring_an_engine_up(), (
        "no job declares `services:`: either CI stopped running against real engines, or this net "
        "is looking for the wrong signal"
    )


@pytest.mark.parametrize("variable", _SWITCHES)
def test_every_job_with_an_engine_answers_for_every_switch(variable: str) -> None:
    """A job that starts a database ANSWERS for each engine gate, even if the answer is `''`.

    Deleting the `SNAKEORM_REQUIRE_MYSQL` line from `ci.yml` used to leave this whole file green
    while every `test_*mysql*.py` and the eleven migration tests that read `MYSQL_HOST` skipped in
    silence on every PR. `ci.yml` says that is not hypothetical: "only the Postgres one was here:
    the MySQL integration tests could skip ENTIRELY and the merge came out green".

    `_SWITCHES` is derived from `_STRICT_BY_REASON`, so a fourth engine is covered the day its gate
    exists — everywhere EXCEPT here, which was the one place the derivation did not reach.

    An explicit `''` counts as an answer: a job may legitimately not require an engine, and this
    asks that somebody DECIDED, not that they said yes.
    """
    for filename, job, body in _jobs_that_bring_an_engine_up():
        env = body.get("env")
        declared = set(env) if isinstance(env, dict) else set()
        assert variable in declared, (
            f"{filename}: the job '{job}' brings a database up and does not mention {variable}. "
            f"Without it the tests behind that gate skip in silence and the merge comes out green."
        )


def test_the_leak_net_watches_every_engine_that_has_a_gate() -> None:
    """`_CONNECTION_ENV` covers the variables of EVERY gated engine, derived rather than listed.

    It watched `DATABASE_URL`, `SNAKEORM_DSN` and `DB_*` — the Postgres ones — while the catalogue
    of engines has been three since MySQL got its gate, and `MYSQL_ENV_KEYS` sits 170 lines above it
    in the same file. Nothing leaks a `MYSQL_HOST` today, so this is closing the door before the
    first test that would, not after.

    The point is the derivation, not the coverage: written out by hand, a fourth engine's variables
    go unwatched the day its gate appears, and they go unwatched QUIETLY — a stray `MYSQL_HOST`
    sends every following test at a database that is not there and they SKIP rather than fail.
    """
    from test.conftest import _CONNECTION_ENV, _STRICT_BY_REASON

    for _variable, keys in _STRICT_BY_REASON.values():
        for key in keys:
            assert key in _CONNECTION_ENV, (
                f"{key} decides which database the suite talks to and the leak net does not watch "
                f"it: a stray one makes every following test skip instead of fail"
            )


# Every target `make audit` composes, and WHERE CI answers for it. A target maps either to a
# fragment that must appear in a workflow, or to a written reason for not being there.
#
# The map is the point. `make audit` calls itself "what would happen in CI", and nothing checked
# that claim: measured, four of its fourteen targets were absent — though two of those turned out to
# be `pytest src/test/...`, which the workflow's own `pytest -q` already collects. A net that had
# compared TARGET NAMES would have reported both as missing and been wrong about half its findings.
_AUDIT_IN_CI: dict[str, str] = {
    "lint": "ruff check .",
    "format-check": "ruff format --check .",
    "typecheck": "uv run mypy .",
    "typecheck-frameworks": "cd frameworks && uv run mypy shared",
    "typecheck-strict": "uv run mypy --strict src/snakeorm/",
    "pyright": "uv run pyright src/snakeorm/",
    "pyright-frameworks": "make pyright-frameworks",
    "docs-build": "mkdocs build --strict",
    "test": "uv run pytest -q",
    "frameworks-test": "make frameworks-test-",
    # `pytest src/test/benchmarks` and `pytest src/test/examples` — collected by the workflow's own
    # `pytest -q`, verified rather than assumed. What is NOT covered is the `python -m examples.tour`
    # half of `examples`, and that is written down below rather than left looking covered.
    "benchmarks-smoke": "uv run pytest -q",
    "examples": "uv run pytest -q",
    "typecheck-react": "npm run typecheck",
    "lint-react": "npm run lint",
}

_AUDIT_NOT_IN_CI: dict[str, str] = {}
"""Targets `audit` composes that NO workflow runs, each with the reason it does not.

Empty, and it has been full: `typecheck-react` and `lint-react` lived here while the client's
TypeScript was checked by whoever ran `make audit` locally and by nobody else. The `react` job
closed that, so they moved up — and the move was not optional, because the test below now refuses a
target declared absent that a workflow actually runs.
"""


def test_every_audit_target_is_either_in_ci_or_declared_absent() -> None:
    """`make audit` says it is "what would happen in CI". This is what makes that a checked claim.

    Nothing compared the two, so the Makefile could grow a gate the workflow never ran — and it
    already had: the React demo's type-check and lint are in `audit` and in no job at all.

    Being absent is allowed; being absent SILENTLY is not. An unlisted target fails here and the
    person adding it has to say which it is.
    """
    makefile = (_PROJECT_ROOT / "Makefile").read_text()
    targets = re.search(r"^audit:([^#\n]*)", makefile, re.M).group(1).split()  # type: ignore[union-attr]

    undeclared = [
        target
        for target in targets
        if target not in _AUDIT_IN_CI and target not in _AUDIT_NOT_IN_CI
    ]

    assert undeclared == [], (
        f"`make audit` composes {undeclared}, and this file does not say whether CI runs them. "
        f"Add it to `_AUDIT_IN_CI` with the step that covers it, or to `_AUDIT_NOT_IN_CI` with the "
        f"reason it is not there."
    )


@pytest.mark.parametrize("target", sorted(_AUDIT_IN_CI))
def test_the_step_that_covers_an_audit_target_is_still_in_the_workflow(
    target: str,
) -> None:
    """The other direction: a step deleted from CI stops covering the target that named it.

    Without this the map is prose. `SNAKEORM_REQUIRE_MYSQL` disappearing from `ci.yml` is exactly
    the shape of the accident this guards against, one level up.
    """
    workflows = "".join(
        path.read_text()
        for path in sorted((_PROJECT_ROOT / ".github" / "workflows").glob("*.yml"))
    )

    assert _AUDIT_IN_CI[target] in workflows, (
        f"`{target}` is mapped to `{_AUDIT_IN_CI[target]}`, which no workflow runs any more: "
        f"either the step moved and the map needs updating, or the gate silently stopped."
    )


@pytest.mark.parametrize("target", sorted(_AUDIT_NOT_IN_CI))
def test_a_target_declared_absent_is_really_absent(target: str) -> None:
    """A hole that gets filled has to stop being declared a hole, and only this notices.

    The map above is checked against the workflows in both directions; this one was checked in
    NEITHER, and it rotted the moment the `react` job landed. `typecheck-react` and `lint-react` sat
    here saying "no job installs a node toolchain" while a job installed one and ran both — the file
    that exists to keep `make audit`'s claim honest, itself out of date, in green.

    A stale entry here is the expensive kind: it reads as a known limitation, so nobody re-checks
    it, and the gate it describes is doing work nobody credits.
    """
    workflows = "".join(
        path.read_text()
        for path in sorted((_PROJECT_ROOT / ".github" / "workflows").glob("*.yml"))
    )
    makefile = (_PROJECT_ROOT / "Makefile").read_text()
    recipe = re.search(rf"^{re.escape(target)}:.*?\n((?:\t.*\n)+)", makefile, re.M)
    assert recipe is not None, f"`{target}` has no recipe in the Makefile any more"
    # Split on `&&` and drop the `cd`, because a workflow expresses the same command differently:
    # the recipe is `cd frameworks/react_front && npm run lint` and the job is `npm run lint` with a
    # `working-directory`. Comparing whole recipe lines found nothing and passed — this test was
    # written that way first, and adding a stale entry back by hand did NOT turn it red.
    commands = [
        fragment.strip()
        for line in recipe.group(1).splitlines()
        for fragment in line.split("&&")
        if fragment.strip() and not fragment.strip().startswith(("cd ", "#"))
    ]

    running = [command for command in commands if command in workflows]
    assert running == [], (
        f"`{target}` is declared as NOT in CI, but a workflow runs {running}. Move it to "
        f"`_AUDIT_IN_CI` with the step that covers it — a hole that was filled is not a hole."
    )
