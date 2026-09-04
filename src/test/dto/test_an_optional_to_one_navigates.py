"""Navigating ACROSS a nullable to-one type-checks, and the value it reads stays optional.

THIS FILE USED TO ASSERT THE OPPOSITE, and the inversion is the point of it.

It was `test_an_optional_to_one_cannot_be_navigated_yet.py`, and it measured a real gap: class
access on a to-one is typed `type[M]`, so with `M = FlatAuthor | None` that distributed to
`type[FlatAuthor] | type[None]`, `type[None]` has no columns, and `FlatPost.editor.username` was an
error in both checkers — with mypy leaking a `SnakeExpr[str] | Any` behind it. Its own docstring
said it should go red the day somebody fixed the descriptor, and that it should then be deleted.

It has not been deleted, it has been TURNED OVER, because the gap it guarded is worth a net in the
other direction. What closed it is an overload on the type of `self`:

    @overload
    def __get__(self: SnakeToOne[N | None], instance: None, owner: Any) -> type[N]: ...

The user's syntax did not change — `SnakeToOne[FlatAuthor | None]` is still how a nullable relation
is declared, and not one model was migrated.

The five cases below are pinned in BOTH checkers because the fix has to be right in two ways at
once, and only one of them is obvious:

  - class access must LOSE the `| None` (`FlatPost.editor` -> `type[FlatAuthor]`), because in SQL
    the relation is not an object that may be missing, it is a table on the far side of a LEFT JOIN;
  - instance access must KEEP it (`post.editor` -> `FlatAuthor | None`), because reading the value
    off a loaded row genuinely can hand back nothing.

An overload change that got the first half and dropped the second would look like a success from
the navigation side while quietly deleting the `None` every caller is supposed to handle. That is
what `test_the_value_read_off_an_instance_is_still_optional` is here to refuse.

The order of the overloads is load-bearing and fails SILENTLY, which is why it gets its own test in
`src/test/typing/test_the_optional_overload_comes_first.py`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.typecheck

# src/test/dto -> src/test -> src -> the repo root, where pyproject.toml lives and `uv` runs.
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

_PROBE = """from __future__ import annotations

from test.dto.domain import FlatPost


def probe(post: FlatPost) -> None:
    reveal_type(FlatPost.author)
    reveal_type(FlatPost.editor)
    reveal_type(FlatPost.editor.username)
    reveal_type(post.author)
    reveal_type(post.editor)
    reveal_type(FlatPost.editor.country.name)
"""

_EXPECTED = (
    "type[FlatAuthor]",
    "type[FlatAuthor]",
    "SnakeExpr[str]",
    "FlatAuthor",
    "FlatAuthor | None",
    "SnakeExpr[str]",
)
"""One per `reveal_type` in `_PROBE`, in order. Normalised: see `_normalise`."""

_MYPY_REVEALED = re.compile(r'Revealed type is "(?P<type>[^"]+)"')
_PYRIGHT_REVEALED = re.compile(r'Type of "[^"]+" is "(?P<type>.+)"$')
_QUALIFIED = re.compile(r"\b(?:[A-Za-z_][A-Za-z0-9_]*\.)+(?=[A-Za-z_])")


def _normalise(revealed: str) -> str:
    """Reduces a checker's rendering of a type to the shape the two of them agree on.

    The two do not spell types the same way and neither spelling is the contract: mypy writes fully
    qualified names (`test.dto.domain.FlatAuthor`) and reaches for `Union[...]`, pyright writes bare
    names. Comparing raw strings would pin the checkers' formatting rather than the ORM's typing,
    and would go red on a mypy upgrade that changed nothing about this repository.

    So module paths are dropped and `Union`/`Optional` are rewritten into PEP 604. What survives is
    the part the project actually promises.
    """
    text = revealed.strip()
    optional = re.fullmatch(r"Optional\[(?P<inner>.+)\]", text)
    if optional:
        text = f"{optional.group('inner')} | None"
    union = re.fullmatch(r"Union\[(?P<members>.+)\]", text)
    if union:
        members = [member.strip() for member in union.group("members").split(",")]
        text = " | ".join(member.replace("None", "None") for member in members)
    text = _QUALIFIED.sub("", text)
    return text.replace("builtins.", "").strip()


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Runs a checker from the project root and hands back the finished process."""
    return subprocess.run(  # noqa: S603 - fixed command, no user input
        command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )


def _mypy_reveals(path: Path) -> list[str]:
    """Every type mypy reveals in `path`, in source order, normalised.

    The return code is checked because an empty list has two meanings — mypy revealed nothing, or
    mypy never ran — and only one of them is a finding. Same reason `test_type_checkers.py` checks
    it: a broken setup that reads as "the types are fine" is the worst answer this file can give.

    `--cache-dir=/dev/null` is NOT tidiness, and it cost a wrong answer to find. mypy keys its
    incremental cache by MODULE name, and every test here writes its probe as `probe.py` into a
    `tmp_path` of its own — different directory, same module. So the second invocation was served
    the FIRST one's results, reported under the first one's path: after the descriptor was fixed,
    mypy still printed the old `SnakeExpr[str] | Any` and the pre-fix `union-attr` errors, and this
    file went red over a fix that was already working.

    It fails in the alarming direction just as easily. Had the cache been warmed by a passing run,
    a later BREAKING change would have been reported green, and this test's whole job is to notice
    that change. Disabling the cache makes the answer depend on the code and not on what happened
    to be checked before it.
    """
    result = _run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-color-output",
            "--no-error-summary",
            "--cache-dir=/dev/null",
            str(path),
        ]
    )
    assert result.returncode in (0, 1), (
        f"mypy did not run (exit {result.returncode}).\n{result.stdout}{result.stderr}"
    )
    return [
        _normalise(match.group("type"))
        for line in result.stdout.splitlines()
        if (match := _MYPY_REVEALED.search(line))
    ]


def _pyright_reveals(path: Path) -> list[str]:
    """Every type pyright reveals in `path`, in source order, normalised."""
    result = _run(["uv", "run", "pyright", "--outputjson", str(path)])
    assert result.returncode in (0, 1), (
        f"pyright did not run (exit {result.returncode}).\n{result.stdout}{result.stderr}"
    )
    report = json.loads(result.stdout)
    diagnostics = sorted(
        (
            diagnostic
            for diagnostic in report["generalDiagnostics"]
            if diagnostic["severity"] == "information"
        ),
        key=lambda diagnostic: diagnostic["range"]["start"]["line"],
    )
    return [
        _normalise(match.group("type"))
        for diagnostic in diagnostics
        if (match := _PYRIGHT_REVEALED.search(diagnostic["message"].splitlines()[0]))
    ]


@pytest.fixture
def probe(tmp_path: Path) -> Path:
    """The probe file, written where both checkers can see the installed package."""
    path = tmp_path / "probe.py"
    path.write_text(_PROBE, encoding="utf-8")
    return path


def test_mypy_reveals_the_five_types(probe: Path) -> None:
    """mypy agrees with the contract on every one of the pinned accesses.

    Pinned as a whole list rather than one assert per case so that a shift in ORDER is caught too:
    the two class accesses reveal the same string, so comparing them individually would let them
    swap places unnoticed.
    """
    assert _mypy_reveals(probe) == list(_EXPECTED)


def test_pyright_reveals_the_same_five_types(probe: Path) -> None:
    """And pyright agrees with mypy, which is the project rule: two gates, one answer.

    This is not redundancy with the test above. The overload that makes this work is resolved on the
    type of `self`, and that is exactly the corner where the two checkers have been measured to
    diverge — with a union of two models plus `| None`, mypy infers `type[Never]` and pyright infers
    the union of the two. That case is unreachable (the linker refuses it), and this test is what
    would notice if some future change made the two disagree about the reachable ones.
    """
    assert _pyright_reveals(probe) == list(_EXPECTED)


def test_navigating_an_optional_to_one_raises_no_error(probe: Path) -> None:
    """The half the old file asserted the other way round: `FlatPost.editor.username` compiles.

    The old assertion was `'has no attribute "username"' in output`. Keeping a check that the error
    is GONE — rather than only that the revealed type is right — is what catches a regression that
    reintroduces the error while some fallback still reports a plausible type.
    """
    result = _run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-color-output",
            "--cache-dir=/dev/null",
            str(probe),
        ]
    )
    assert "error:" not in result.stdout, result.stdout


def test_no_any_leaks_out_of_the_navigation(probe: Path) -> None:
    """The other half of the old file, which mattered in a project whose rule is zero `Any`.

    Navigating the optional used to come back `SnakeExpr[str] | Any`: the `type[None]` arm of the
    distributed union resolved to `Any` and every read through it went unchecked. An error you can
    see is survivable; the `Any` riding along behind it is not.
    """
    assert not any("Any" in revealed for revealed in _mypy_reveals(probe)), (
        "the navigation must not resolve through an `Any` arm"
    )


def test_the_value_read_off_an_instance_is_still_optional(probe: Path) -> None:
    """The guard against a fix that goes too far, and the reason the change is CORRECT.

    Unwrapping the `| None` is right for CLASS access, where the relation is a table in a LEFT JOIN
    and cannot be "missing". It would be a lie for INSTANCE access: `post.editor` reads a value off
    a loaded row, and that row's editor genuinely may not exist.

    An overload written to unwrap in both places would fix the navigation and silently delete the
    `None` that every caller is meant to handle — a type lie of exactly the kind
    `_guard_nullability_parity` exists to prevent, arriving through the front door.
    """
    assert _mypy_reveals(probe)[4] == "FlatAuthor | None"
    assert _pyright_reveals(probe)[4] == "FlatAuthor | None"


def test_a_required_to_one_is_untouched(probe: Path) -> None:
    """The control. Without it, the tests above could be passing for any reason at all.

    `FlatPost.author` is declared `SnakeToOne[FlatAuthor]` with no `| None` anywhere, so it must go
    on resolving through the plain generic overload exactly as it did before.
    """
    assert _mypy_reveals(probe)[0] == "type[FlatAuthor]"
    assert _mypy_reveals(probe)[3] == "FlatAuthor"
