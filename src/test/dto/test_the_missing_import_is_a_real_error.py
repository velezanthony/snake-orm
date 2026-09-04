"""The generator refuses a field whose name the file does not import. This proves it has to.

The refusal is only worth its inconvenience if writing the annotation anyway would really break
something, and there is a reason to doubt that: the file starts with `from __future__ import
annotations`, so every annotation in it is a STRING that nobody evaluates at runtime. It is
reasonable to assume postponed evaluation makes the import optional.

It does not, and this file runs mypy to say so rather than asserting it from memory. The checker
resolves annotations whether or not the interpreter does, and a name that is not in scope is an
error — `Name "datetime" is not defined`. So a generator that wrote the field without the import
would have produced a file that fails the type check, which is to say it would have broken the build
in order to fix a type.

That is what makes "say what to add and add nothing" the right answer rather than a cop-out: the
alternative is not "it works anyway", it is a red build with the generator's own line in it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.typecheck

_WITHOUT_THE_IMPORT = '''"""Postponed annotations, and `datetime` nowhere in scope."""

from __future__ import annotations

from typing import TypedDict


class UserPublic(TypedDict):
    """The body the generator would have written without its import guard."""

    id: int
    created_at: datetime.datetime
'''

_WITH_THE_IMPORT = _WITHOUT_THE_IMPORT.replace(
    "from typing import TypedDict", "import datetime\nfrom typing import TypedDict"
)


def _mypy(path: Path) -> str:
    """Runs mypy over one file and returns its output, checked for having actually run.

    Empty output has two meanings — mypy approved the file, or mypy never started — and telling
    them apart is the difference between a finding and a broken setup. A crash returns 2.
    """
    finished = subprocess.run(  # noqa: S603 - fixed command, no user input
        [sys.executable, "-m", "mypy", "--no-color-output", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode in (0, 1), (
        f"mypy did not run: {finished.returncode}\n{finished.stdout}{finished.stderr}"
    )
    return finished.stdout


def test_postponed_annotations_do_not_excuse_the_missing_import(
    tmp_path: Path,
) -> None:
    """`from __future__ import annotations` does NOT make the import optional. Measured.

    This is the premise of the whole import guard. If it were false, refusing would be pointless
    friction and the right answer would be to write the field and say nothing.
    """
    path = tmp_path / "no_import.py"
    path.write_text(_WITHOUT_THE_IMPORT, encoding="utf-8")

    output = _mypy(path)

    assert 'Name "datetime" is not defined' in output


def test_the_same_body_passes_once_the_import_is_there(tmp_path: Path) -> None:
    """The other half, without which the test above proves nothing about the IMPORT.

    A file that failed for some unrelated reason would satisfy the first assertion just as well.
    This one holds everything else fixed and changes only the line the guard asks for.
    """
    path = tmp_path / "with_import.py"
    path.write_text(_WITH_THE_IMPORT, encoding="utf-8")

    assert "error:" not in _mypy(path)
