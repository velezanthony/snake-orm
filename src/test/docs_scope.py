"""What the documentation nets look at, declared once for all of them.

Two nets sweep the repository's markdown — `test_links_the_site_never_builds` and
`test_the_two_language_graphs_match` — and they used to answer "which files are mine?" separately.
Two answers to one question drift, and the drift is silent: a directory excluded from one net and
not the other looks covered from either side.

Read the two lists below as what they are: `EXCLUDED_DIRS` is a DECISION, `NOT_OURS` is a fact.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

EXCLUDED_DIRS: tuple[str, ...] = ()
"""Directories the documentation nets ignore. Empty on purpose — nothing is exempt yet.

**One switch, all or nothing.** A directory named here leaves BOTH nets at once: no Spanish twin is
owed for it and its links stop being checked. That is the intent, not a side effect. Watching half
of a path is worse than not watching it — it reads as covered from either side, and the half nobody
watches is where things rot.

Add one here only to declare a decision, never to quiet a failure you have not decided about. The
floors under both nets guard the accident and not this: they check the sweep did not empty by a
broken glob, and name no document that would keep you from excluding it on purpose.

`features.md` is NOT here, and the reason is that there are THREE questions, not two.
`exclude_docs` in `mkdocs.yml` answers whether a document is PUBLISHED; `is_bilingual` below answers
whether it is TRANSLATED; this list answers whether it is CHECKED at all. The feature index is
unpublished —it links to source files the site does not carry— and translated all the same, and its
links still have to resolve.

This paragraph used to name two questions and fold translation into publication. It read correctly
right up until the day the answers parted company, which is the failure mode of every rule stated
one distinction short of the ones it governs.

The plans and the internal notes used to live here too, under `planning/` and `interno/`. They are
gitignored now: a plan is corrected while it is being executed, and one kept beside a shipped
product reads as a promise. What stayed is the feature index, which was only in that directory
because it inherited the name.
"""

NOT_DOCUMENTATION = (".github", "CHANGELOG.md", "planning", "interno")
"""Not this repository's documentation. Not a policy about translating any of it.

`.github/` is GitHub's own forms — the pull-request template and the issue links. Their reader is
the person filling the form on github.com, in the one language the repository writes in, and GitHub
would not serve a `.es.md` twin to anybody.

`CHANGELOG.md` records what shipped, and it is read beside a release tag and a package page — the
audience the code, the docstrings and every emitted message already address in English. The prose
under `docs/` is mirrored because it TEACHES, and a release record teaches nobody.

Plans and internal notes are read by whoever builds the next thing, and that reader is already on
this machine. They carry ONE language because they have one audience, so a missing Spanish twin is
not debt owed — and left in scope it would be reported as debt forever, which is how a net starts
teaching people to ignore it.

Their links are not checked either, and that IS a change rather than a detail: while they shipped, a
rotted link inside one was a dead end for the next person. Off the history they are somebody's
working notes, and the next person is the same person.

Both are GITIGNORED: they live on whoever's machine is working here, and out of the history. That
does not make this list redundant — the files are still on DISK, so the sweeps that walk the tree
still meet them, and this is what tells those sweeps they were never in the question.
`test_what_is_gitignored_is_not_tracked` is what keeps them out of the history itself, and the two
have to agree: a path added here and not there stops being checked while still shipping.

Kept apart from `EXCLUDED_DIRS` on purpose, and the difference is the whole point of both lists.
That one exempts a directory of REAL documentation from a check it should pass one day; this one
says the file was never in the question. Merging them would let "we have not translated it yet"
hide inside "it does not need translating".

Matched against every part of the path, like `NOT_OURS`, so one list covers both directories
without a second list to drift against it.
"""


OFF_SITE: tuple[str, ...] = (
    "features.md",
    "features.es.md",
    *NOT_DOCUMENTATION,
    *EXCLUDED_DIRS,
)
"""Directories the site does not publish, plus whatever is out of scope entirely.

Mirrors `exclude_docs` because a test cannot read that config without parsing YAML. It is a
SUPERSET of `EXCLUDED_DIRS` rather than a rival: a directory nobody checks cannot be one the site
publishes, so excluding it from the nets excludes it from this question too. Written as a superset
so the two cannot drift — they did, and it cost two false failures the day `coverage-history/`
appeared: a third list, in a third file, that nobody remembered to widen.

It also decides who is owed a translation, through `is_bilingual`. Same list because it is the same
fact —what a reader outside this repository ever opens— and a second one spelling it again would be
the drift this module exists to prevent.
"""

NOT_OURS = (
    ".venv",
    "node_modules",
    "site",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
)
"""Trees holding no document of ours: dependencies, caches and build output.

Kept apart from `EXCLUDED_DIRS` so the two cannot be confused. This one is not a policy — nobody
decided `.venv` needs no translation — and merging them would let a real exemption hide inside a
list nobody reads.
"""


def is_ours(path: pathlib.Path) -> bool:
    """Whether a file is a document this repository is answerable for."""
    return not any(
        part in NOT_OURS or part in EXCLUDED_DIRS or part in NOT_DOCUMENTATION
        for part in path.parts
    )


READ_ANYWAY: tuple[str, ...] = ("docs/features.md",)
"""Unpublished documents that somebody outside this repository still opens.

`features.md` is the LIST of what is built and how much net holds each piece up. It is not published
because it links to source files the built site does not carry, and it IS translated because whoever
is deciding whether this ORM does what they need reads that table, in whichever language they have.
It used to be `planning/roadmap.md`, and it was there only because it inherited the name when the
old plan was renamed out of the way — a naming accident that made it look like a plan for months.

An allow-list and not a pattern, and it fails CLOSED on purpose: an unpublished document written
tomorrow goes untranslated without anybody deciding anything. The cost is that a second status
document has to be named here — one line, paid by whoever knows it is one.
"""


def is_bilingual(path: pathlib.Path) -> bool:
    """Whether this document is owed a version in the other language.

    Narrower than `is_ours`, and the gap between the two is the point: a plan is a document this
    repository answers for —its links are checked— and it is still not translated. It records how
    something got built, for whoever builds the next thing, and that reader is already here.

    The exceptions go in `READ_ANYWAY`, named one by one. Not a switch to reach for when a
    translation is merely late. `EXCLUDED_DIRS` is where an
    unwritten translation would go, and it is empty; this is about documents that were never in the
    question. Told apart the same way `NOT_OURS` and `EXCLUDED_DIRS` are, and for the same reason:
    let "I have not done it yet" hide inside "it does not need doing" and the list stops meaning
    anything.
    """
    if not is_ours(path):
        return False
    try:
        named = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:  # pragma: no cover - a path from outside the repository
        return False
    if named in READ_ANYWAY:
        return True
    return not any(part in OFF_SITE for part in path.parts)
