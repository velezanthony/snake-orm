"""The documentation nets skip what is not this project's documentation, and skip nothing else.

Two things are out. `.github/` is GitHub's own forms, read on github.com by whoever is filling one
in — no site serves them and no twin would ever be shown. And `planning/` and `interno/`, which are
gitignored. They live on somebody's machine
and the next person to read them is that same person, so a missing Spanish twin is not debt owed —
and left in scope it would be reported as debt forever, which is how a net starts teaching people to
ignore it.

An exemption is only safe while it is NARROW, and that is the half worth testing. A list that grows
by one careless entry stops being a decision and turns into the place failures go to be quiet — the
same thing `EXCLUDED_DIRS` warns about in its own docstring. So both directions are asserted here:
what is out stays out, and the documents around it are still in.
"""

from __future__ import annotations


import pytest

from test.docs_scope import READ_ANYWAY, ROOT, is_bilingual, is_ours


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/features.md",
        "frameworks/README.md",
    ],
)
def test_the_exemption_did_not_widen(relative: str) -> None:
    """The documents beside them are still owed a twin.

    Most of these sit in the repository ROOT, where things that are not documentation have lived
    before. An exemption written a shade too broadly takes them all, and that is not hypothetical:
    the obvious spelling of "skip the root" would.

    These are paths, not files: `is_ours` answers about a name and never asks the disk. So an entry
    whose document gets deleted keeps passing, guarding nothing. It is the reader's job to drop it,
    because no red will.
    """
    assert is_ours(ROOT / relative)


@pytest.mark.parametrize(
    "relative",
    [
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/config.yml",
        "CHANGELOG.md",
    ],
)
def test_what_speaks_one_language_owes_no_translation(relative: str) -> None:
    """These are not documentation: nothing serves them as a page and no twin would be shown.

    The pull-request template landed and `test_every_page_has_a_spanish_twin` immediately demanded a
    `.es.md` for it — correctly, by its own rule, since it sweeps the whole repository. The exemption
    is declared here so it is a decision somebody took rather than a path that quietly slipped out.

    `CHANGELOG.md` is here for the same reason and a different one: it is a release record, read
    beside a tag and a package page, and it says so in its own opening lines.
    """
    assert not is_ours(ROOT / relative)


@pytest.mark.parametrize(
    "relative",
    ["docs/planning", "docs/interno"],
)
def test_what_is_gitignored_is_not_tracked(relative: str) -> None:
    """Plans and internal notes stay LOCAL: on disk, out of the repository.

    A plan is corrected while it is being executed, so one kept beside a shipped product reads as a
    promise it never made. They are read by whoever builds the next thing, and that reader is
    already on this machine.

    TRACKED and not EXISTS, and the difference is the whole point: these files are meant to be here,
    on somebody's machine. What must not happen is one of them entering the history — which is what
    a `git add -f` does, and what nothing else in this repository would ever mention again.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "--", relative],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert not tracked, (
        f"{relative} is tracked again ({len(tracked)} file(s), e.g. {tracked[0]}). It is gitignored "
        f"on purpose: keep it locally, out of the history. If it is meant to ship, it is not a plan "
        f"and not an instruction, and it does not belong under that name."
    )


def test_the_feature_index_is_unpublished_and_translated_all_the_same() -> None:
    """`features.md` is the one document that answers those two questions differently.

    Unpublished because it links to source files the built site does not carry; translated because
    whoever is deciding whether this ORM does what they need reads that table, in whichever language
    they have. Any switch that folded the two answers together would take it.
    """
    assert is_bilingual(ROOT / "docs/features.md")
    assert is_ours(ROOT / "docs/features.md")


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "CONTRIBUTING.md",
        "docs/users/index.md",
        "docs/contributors/architecture.md",
        "frameworks/README.md",
        "docs/features.md",
    ],
)
def test_the_published_documents_still_owe_one(relative: str) -> None:
    """The other direction: what a reader actually opens is still bilingual.

    The root files are the ones at risk from a rule written as "skip what the site does not
    publish": `README.md` and `CONTRIBUTING.md` live outside `docs/` and are not published by mkdocs
    either, yet they are the first thing anybody reads.
    """
    assert is_bilingual(ROOT / relative)


def test_the_two_nets_agree_on_who_owes_a_twin() -> None:
    """One question, one answer. The two nets used to give different ones over `docs/`.

    `test_docs_are_bilingual` swept the published pages and skipped `planning/` and `interno/`;
    `test_every_page_has_a_spanish_twin` swept everything and demanded a twin for them. Both were
    green about their own rule, so the disagreement was invisible from either side — a page could
    be owed a translation by one net and exempt in the other, which is the drift `docs_scope`
    exists to prevent and was quietly having.

    Containment and not equality, because the two sets are no longer the same one: `roadmap.md` is
    translated without being published. Equality would have been the tidier assertion and it would
    have made that exception unexpressible — so the direction that matters is pinned (published
    always owes a twin) and the gap has to be exactly what somebody declared, never one more.
    """
    from test.test_docs_are_bilingual import _site_pages

    published = {p.resolve() for p in _site_pages()}
    owed = {
        p
        for p in (ROOT / "docs").rglob("*.md")
        if is_bilingual(p) and not p.name.endswith(".es.md")
    }

    assert published <= owed, (
        "published with no translation owed: "
        f"{sorted(p.relative_to(ROOT).as_posix() for p in published - owed)}"
    )
    assert {p.relative_to(ROOT).as_posix() for p in owed - published} == set(
        READ_ANYWAY
    ), (
        "translated without being published, and not declared: "
        f"{sorted(p.relative_to(ROOT).as_posix() for p in owed - published)}"
    )
