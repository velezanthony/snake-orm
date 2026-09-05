"""`snakeorm.__version__` is the first thing an issue is opened with.

It is READ from the installed metadata and never written down beside `pyproject.toml`: two copies of
one number agree until the release somebody bumps one of them, and the version is exactly the field
where that lie is expensive — a bug report against 0.1.0 that was really 0.2.0 sends everybody to
read the wrong code.
"""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

import snakeorm

_ROOT = Path(__file__).resolve().parents[2]


def test_the_package_says_which_version_it_is() -> None:
    """Importing it is enough to know: no metadata call at the call site."""
    assert snakeorm.__version__
    assert snakeorm.__version__ == metadata.version("snake-orm")


def test_the_version_is_not_a_second_copy_of_the_number() -> None:
    """What `pyproject.toml` declares is what the package answers, with nobody keeping them in step."""
    declared = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert snakeorm.__version__ == declared["project"]["version"]
