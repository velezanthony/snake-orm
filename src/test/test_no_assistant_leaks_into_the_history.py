"""Nothing that had an assistant for its reader gets committed, and this is what keeps it that way.

The repository was swept by hand once: agent instructions, skill files, working notes and a `.atl/`
directory came out, and the plans went behind `.gitignore`. A sweep answers for the day it ran. This
answers for tomorrow, which is the only part that was still open.

IT WALKS THE INDEX, NOT THE DISK, and that distinction is the whole design. `.claude/`, `.atl/` and
whatever the next tool is called live on somebody's machine and belong there — the question is never
"does this file exist" but "is it about to ship". `git ls-files` answers exactly that, and it answers
it for files no `.gitignore` rule anticipated: a stray `AGENTS.md`, a docstring citing a skill, a
commit-message convention pasted into a README.

WHY A TEST AND NOT A `.gitignore` RULE. Ignoring works on paths somebody predicted. Half of what the
sweep found was not a path at all — it was prose inside files that legitimately ship, naming tools
that had read them. No pattern catches that, and a pattern that tried would have to be widened by
whoever added the next tool, which is the rule that gets forgotten.

WHAT IT DOES NOT CLAIM. The history already carries these words, and rewriting it was considered and
declined: what shipped, shipped. This holds the line from here on, which is the decision that was
actually taken.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]

_NAMES = (
    "claude",
    "anthropic",
    "chatgpt",
    "openai",
    "copilot",
    "gemini",
    "codex",
    "devin",
    "engram",
    "openspec",
)
"""Assistants and the tooling around them, by name.

Names and not concepts, because a name is unambiguous and a concept is not: "agent" is a word this
ORM could legitimately use one day, and "cursor" already is one — `iterate()` opens a server-side
cursor on Postgres and MySQL, and the word appears in the guide, the reference and the limits page.

`llm` is not here for the same reason, learned by measuring: it matches `enrollments`, a table the
demo domain has had since the beginning, in eight files.
"""

_ARTEFACTS = (
    r"CLAUDE\.md",
    r"AGENTS?\.md",
    r"\.claude/",
    r"\.atl/",
    r"SKILL\.md",
    r"Co-Authored-By",
)
"""Files and conventions these tools write, matched as they are written.

`Co-Authored-By` is here and it is not about a tool at all: it is the trailer an assistant appends to
a commit, and the one thing on this list that reaches a reader who never opens a file. It is checked
in the tracked text because a template or a contributing guide is where it would be prescribed.
"""

_ALLOWED = re.compile(
    r"""
    coverage-history/assets/(data|js|css)/  # measurement snapshots and the viewer's own code
    | package-lock\.json                    # npm's resolution, not ours to edit
    | uv\.lock                              # the same, for Python
    | static/app\.css                       # tailwind's build output
    | test_no_assistant_leaks_into_the_history\.py  # this file names them all, by necessity
    """,
    re.VERBOSE,
)
"""Tracked files whose CONTENT nobody writes by hand.

Not an exemption from the policy: a lockfile cannot leak an instruction, and this file has to spell
the words out to look for them. Every one is content generated or vendored, and the list is short on
purpose — an exemption that grows is the sweep coming back.
"""


def _tracked_text_files() -> list[pathlib.Path]:
    """Every file in the index whose content a person writes.

    `is_file()` is doing real work and not defending against nothing: the three demos each track a
    `migrations` entry that is a SYMLINK to `shared/migrations/<domain>`, so `git ls-files` hands
    back ten paths that open as directories. Reading one raises `IsADirectoryError`, which is not
    what a leak looks like — it is the sweep breaking and reporting it as a finding. The symlink's
    target is walked anyway, under its own path, so nothing goes unread.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        path
        for name in listing.stdout.split("\0")
        if name and not _ALLOWED.search(name)
        if (path := _REPO / name).is_file()
    ]


def test_the_sweep_is_reading_something() -> None:
    """The floor. Without it, a broken `git ls-files` would make every assertion below vacuous.

    Both tests are "no file contains X". If the listing came back empty — wrong cwd, git absent, the
    exemption widened until it covered the repository — they would pass over nothing and report the
    repository clean. This is what refuses that.
    """
    files = _tracked_text_files()

    assert len(files) > 500, f"only {len(files)} tracked files were read"
    assert any(path.name == "README.md" for path in files), (
        "the sweep missed the README"
    )


@pytest.mark.parametrize("name", _NAMES)
def test_no_assistant_is_named_in_tracked_text(name: str) -> None:
    """A tool that read this repository does not get to be mentioned by the repository.

    Not tidiness. A reader who meets `CLAUDE.md` in a package they are evaluating learns something
    about how it was built and nothing about whether it works, and the repository has no way to
    answer the question it just raised.
    """
    hits = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # pragma: no cover - binary or a race with a checkout
        for number, line in enumerate(text.splitlines(), start=1):
            if name in line.lower():
                hits.append(f"{path.relative_to(_REPO)}:{number}: {line.strip()[:90]}")

    assert hits == [], (
        f"{name!r} appears in tracked text, which means it ships:\n  "
        + "\n  ".join(hits[:10])
    )


@pytest.mark.parametrize("pattern", _ARTEFACTS)
def test_no_assistant_artefact_is_tracked_or_named(pattern: str) -> None:
    """The files these tools write, and the trailer they sign with.

    Checked in the CONTENT and not only in the paths, because the way one comes back is somebody
    writing "add a `CLAUDE.md` with the conventions" into `CONTRIBUTING.md` — no file added, the
    instruction shipped anyway, and the next person creates it.
    """
    matcher = re.compile(pattern, re.IGNORECASE)
    hits = []
    for path in _tracked_text_files():
        if matcher.search(str(path.relative_to(_REPO))):
            hits.append(f"{path.relative_to(_REPO)}: tracked")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # pragma: no cover - binary or a race with a checkout
        for number, line in enumerate(text.splitlines(), start=1):
            if matcher.search(line):
                hits.append(f"{path.relative_to(_REPO)}:{number}: {line.strip()[:90]}")

    assert hits == [], (
        f"{pattern!r} is in the index, which means it ships:\n  "
        + "\n  ".join(hits[:10])
    )


def test_the_plans_are_still_out_of_the_index() -> None:
    """`docs/planning/` and `docs/interno/` stay on disk and out of the history.

    `test_the_docs_scope_is_narrow` already pins this from the documentation nets' side. It is here
    too because the two answer different questions and the answers have to agree: that one says the
    nets do not check them, this one says they do not ship. A path added there and not here would
    stop being checked while still being published.
    """
    listing = subprocess.run(
        ["git", "ls-files", "docs/planning", "docs/interno"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    assert listing.stdout.strip() == "", (
        f"the plans are tracked again:\n{listing.stdout}"
    )
