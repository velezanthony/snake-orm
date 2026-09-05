"""Runs mypy AND pyright over the case files and checks the typing contract.

The thesis of SnakeORM is that the type system is the single source of truth. Until now that
was checked by hand, with spikes. Here it is automated: if a refactor breaks deep navigation
or opens a hole that lets bad SQL be written, these tests fail.

- `cases_positive.py` → 0 errors in both checkers.
- `cases_negative.py` → an error EXACTLY on the lines marked with `# EXPECT: <code>`.

Both checkers must agree on WHICH lines they reject (the error codes do differ, so only
mypy is contrasted against the concrete code).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
POSITIVE = HERE / "cases_positive.py"
NEGATIVE = HERE / "cases_negative.py"
# The repo root (where pyproject.toml lives and `uv` runs): src/test/typing → src/test → src → root.
PROJECT_ROOT = HERE.parent.parent.parent

_MYPY_LINE = re.compile(r"^[^:]+:(?P<line>\d+): error: .*\[(?P<code>[a-z-]+)\]$")
_EXPECT = re.compile(r"#\s*EXPECT:\s*(?P<code>[a-z-]+)\s*$")

pytestmark = pytest.mark.typecheck


def _expected_errors(path: Path) -> dict[int, str]:
    """Extracts `{line number: error code}` from the `# EXPECT:` comments of the file."""
    expected: dict[int, str] = {}
    for number, text in enumerate(path.read_text().splitlines(), start=1):
        match = _EXPECT.search(text)
        if match:
            expected[number] = match.group("code")
    return expected


def _run(
    command: list[str], *, cwd: Path = PROJECT_ROOT
) -> subprocess.CompletedProcess[str]:
    """Runs a checker and returns the finished process. From the project root unless told otherwise.

    `cwd` exists because the demo apps only resolve `shared` from `frameworks/`, which is the same
    reason `make typecheck-frameworks` changes directory before running.
    """
    return subprocess.run(  # noqa: S603 - fixed command, no user input
        command, cwd=cwd, capture_output=True, text=True, check=False
    )


def _mypy_errors(path: Path) -> dict[int, str]:
    """Runs mypy over a file and returns `{line number: error code}`.

    `--no-color-output` is not cosmetic: mypy honours `FORCE_COLOR`, which plenty of terminals and
    CI runners export these days, and then every line arrives wrapped in ANSI escapes that this
    regex does not match. The result was an EMPTY dict — read as "the type checker approves code
    that must not compile", the most alarming message this file can produce — for a reason that had
    nothing to do with the code. Asking for plain output makes the answer depend on mypy and not on
    whoever's shell invoked it.

    And the returncode is checked, because `{}` has two meanings: mypy ran and found nothing, or
    mypy never ran. Telling them apart is the difference between a real finding and a broken setup.
    """
    result = _run(
        ["uv", "run", "mypy", "--no-color-output", "--no-error-summary", str(path)]
    )
    assert result.returncode in (0, 1), (
        f"mypy did not run (exit {result.returncode}). Empty output would otherwise read as "
        f"'no type errors'.\nstderr: {result.stderr[:400]}"
    )
    errors: dict[int, str] = {}
    for text in result.stdout.splitlines():
        match = _MYPY_LINE.match(text)
        if match:
            errors[int(match.group("line"))] = match.group("code")
    return errors


def _pyright_errors(*paths: Path, cwd: Path = PROJECT_ROOT) -> list[str]:
    """Runs pyright over `paths` and returns one `file:line: message` per error.

    The returncode is checked for the same reason `_mypy_errors` checks it: an empty list has two
    meanings — pyright ran and found nothing, or pyright never ran — and only one of them is good
    news. `1` is "there were errors", anything above that is "it did not run".
    """
    result = _run(
        ["uv", "run", "pyright", "--outputjson", *(str(path) for path in paths)],
        cwd=cwd,
    )
    assert result.returncode in (0, 1), (
        f"pyright did not run (exit {result.returncode}). An empty list would otherwise read as "
        f"'no type errors'.\nstderr: {result.stderr[:400]}"
    )
    report = json.loads(result.stdout)
    return [
        f"{Path(diagnostic['file']).name}:"
        f"{diagnostic['range']['start']['line'] + 1}: {diagnostic['message'].splitlines()[0]}"
        for diagnostic in report["generalDiagnostics"]
        if diagnostic["severity"] == "error"
    ]


def _pyright_error_lines(path: Path) -> set[int]:
    """Runs pyright over a file and returns the (1-based) lines with an error."""
    result = _run(["uv", "run", "pyright", "--outputjson", str(path)])
    assert result.returncode in (0, 1), (
        f"pyright did not run (exit {result.returncode}). An empty set would otherwise read as "
        f"'no type errors'.\nstderr: {result.stderr[:400]}"
    )
    report = json.loads(result.stdout)
    return {
        diagnostic["range"]["start"]["line"] + 1  # pyright counts from 0
        for diagnostic in report["generalDiagnostics"]
        if diagnostic["severity"] == "error"
    }


def test_positive_cases_pass_mypy() -> None:
    """Everything that MUST type-check does: mypy finds not a single error in the positive cases."""
    assert _mypy_errors(POSITIVE) == {}


def test_positive_cases_pass_pyright() -> None:
    """Same with pyright: both checkers must agree (project rule)."""
    assert _pyright_error_lines(POSITIVE) == set()


def test_negative_cases_fail_mypy_exactly_where_expected() -> None:
    """Every `# EXPECT: <code>` line produces that error, and no other line fails.

    If a refactor opens a hole, the error disappears and this test catches it.
    """
    assert _mypy_errors(NEGATIVE) == _expected_errors(NEGATIVE)


def test_negative_cases_fail_pyright_on_the_same_lines() -> None:
    """Pyright rejects the SAME lines as mypy (the codes differ, the lines do not)."""
    assert _pyright_error_lines(NEGATIVE) == set(_expected_errors(NEGATIVE))


# The two scopes `make pyright` and `make pyright-frameworks` declare. They are named here and
# compared against the Makefile below, so widening the gate without widening this net (or the other
# way round) is a failure and not a silence.
_PACKAGE = Path("src/snakeorm")
_APPS = (
    Path("frameworks/django"),
    Path("frameworks/flask"),
    Path("frameworks/fastapi"),
)


def test_the_package_itself_has_no_pyright_errors() -> None:
    """`make pyright` over `src/snakeorm`, run by the suite instead of only by whoever remembers.

    Until this existed the net checked the two CONTRACT files and nothing else, so the package
    could —and did— carry a pyright error for as long as nobody typed the command: an
    `async_translating` that widened its return type took every asynchronous driver out of the
    `AsyncDriver` protocol, `make audit` fell over, and the project went on believing pyright was
    at zero. A gate nobody runs is not a gate, and one that advertises itself as green is worse
    than none.
    """
    assert _pyright_errors(PROJECT_ROOT / _PACKAGE) == []


def test_the_three_demo_apps_have_no_pyright_errors() -> None:
    """`make pyright-frameworks`. It runs FROM `frameworks/`, which is where `shared` resolves.

    The cwd is the whole point: from the repo root `shared` does not resolve and the errors this
    catches never appear — the same resolution reason `typecheck-frameworks` is written down for.
    """
    root = PROJECT_ROOT / "frameworks"
    assert _pyright_errors(*(PROJECT_ROOT / app for app in _APPS), cwd=root) == []


def test_the_makefile_gate_checks_exactly_these_scopes() -> None:
    """The Makefile's pyright targets look at what the two tests above look at, and nothing more.

    Without this the net is a copy of the gate that drifts from it in silence: a fourth demo added
    to `pyright-frameworks` would be checked by CI and not by the suite, or the other way round,
    and both sides would stay green over their own half.
    """
    makefile = (PROJECT_ROOT / "Makefile").read_text()

    for scope in (_PACKAGE, *_APPS):
        assert str(scope) in makefile, (
            f"{scope} is in this net and not in the Makefile: the suite checks something the gate "
            f"does not."
        )
