"""A migration already in the history is not edited. It is a record of what happened.

This net exists because the mistake was made TWICE in one afternoon, by the same person, twenty
minutes apart. A rename of `Stock.quantity` to `on_hand` was applied "to the inventory domain" with a
tool that walks directories, and `apps/inventory/migrations/` is a directory inside the inventory
domain. Nine historical files came out saying the column had been BORN as `on_hand`.

WHY THAT IS WORSE THAN IT LOOKS. Editing `0001` does not correct anything: it makes the history lie
about how the present was reached. Somebody applying it from scratch gets a different schema from the
one whoever applied it yesterday got, and the two never find out — until an `ALTER` in a later
migration refers to a column that, in their database, has another name.

AND `test_migration_drift.py` CANNOT CATCH IT. That is its structural limit, not an oversight: it
compares the FINAL STATE of the history against the models. With `0001` saying `on_hand` and `0004`
renaming `on_hand` to `on_hand`, the final state is right and the check is green. What it does not
verify — and cannot, replaying state without executing SQL — is that every STEP is applicable.

WHAT IT COMPARES. The migration files against `git`, which is the only record of what was there
before. A file already committed may not change; a new one may appear freely. That is what
"append-only" means here, and it is checkable in one command.

WHERE IT LOOKS, AND WHY THAT MOVED. The history used to be sixty files — the same twenty copied into
each demo — and it now lives ONCE, in `shared/migrations/<domain>/`, with each demo's
`apps/<domain>/migrations` a symlink to it. Git does not follow symlinks, so `git ls-files` over the
demos' paths finds nothing at all now: this net has to look where the FILES are, not where the
runner reaches them. The consequence is worth stating rather than discovering: the commit that lands
the relocation is this net's new BASELINE, and until it exists there is nothing committed at the new
path to compare against — which is the same "no record yet" state a fresh clone of a tarball is in,
and it is reported the same way, as a skip that says so.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from snakeorm.migration import load

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMOS = ("django", "flask", "fastapi")


def _tracked_migrations() -> list[str]:
    """The migration files git already knows about, repo-relative."""
    result = subprocess.run(
        ["git", "ls-files", "frameworks/shared/migrations/*/*.py"],
        capture_output=True,
        text=True,
        cwd=_ROOT.parent,
    )
    return [line for line in result.stdout.split() if not line.endswith("__init__.py")]


def _modified_migrations() -> list[str]:
    """Tracked migration files with uncommitted changes. These are the ones that must not exist."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "frameworks/shared/migrations/*/*.py"],
        capture_output=True,
        text=True,
        cwd=_ROOT.parent,
    )
    return [line for line in result.stdout.split() if not line.endswith("__init__.py")]


def test_git_can_be_read() -> None:
    """The check needs git. Without it every assertion below would hold over an empty list.

    A repository without history is a legitimate state — a fresh clone of a tarball — and there the
    honest outcome is a SKIP, not a green tick over nothing.
    """
    if not (_ROOT.parent / ".git").exists():
        pytest.skip("no git repository: this net has nothing to compare against")
    if not _tracked_migrations():
        pytest.skip(
            "nothing is committed under `frameworks/shared/migrations/` yet: the relocation of the "
            "history has not been committed, so there is no record to compare against"
        )

    assert len(_tracked_migrations()) >= 10, _tracked_migrations()


def test_no_migration_already_in_the_history_has_been_edited() -> None:
    """The whole point. A committed migration is a record; new ones are how a schema moves on.

    If this is red, the fix is almost never to keep the edit: it is to revert the file and write a
    NEW migration that makes the change. The exception is a genuine repair of a migration that was
    never applied anywhere, and then the commit message has to say so.
    """
    if not (_ROOT.parent / ".git").exists():
        pytest.skip("no git repository: this net has nothing to compare against")
    if not _tracked_migrations():
        pytest.skip(
            "nothing is committed under `frameworks/shared/migrations/` yet: the relocation of the "
            "history has not been committed, so there is no record to compare against"
        )

    edited = sorted(_modified_migrations())

    assert edited == [], (
        f"these migrations are already in the history and have been modified: {edited}. A migration "
        f"is a RECORD of what happened, not a document to keep up to date — editing one makes the "
        f"history lie about how the present was reached, and anybody applying it from scratch gets a "
        f"different schema from the one it produced before. Revert them and write a new migration."
    )


def test_the_three_demos_carry_the_same_history() -> None:
    """The three demos share a domain, so they share its history, file for file.

    A migration written into one demo and not the others is how the three stop being the same
    application on three frameworks — which is the premise `frameworks/` rests on.

    It survives the history living ONCE because it walks the demos' paths, symlinks and all: what it
    asserts is that the three reach the same FILENAMES, which stays worth asserting the day somebody
    adds a domain to one demo and forgets the other two. That the three reach the same INODE is a
    different fact and has its own net, in
    `test_every_engine_accepts_the_migration_plans.test_the_three_demos_share_one_history_on_disk`.
    """
    per_demo = {
        demo: sorted(
            f"{path.parent.parent.name}/{path.name}"
            for path in (_ROOT / demo / "apps").glob("*/migrations/*.py")
            if path.name != "__init__.py"
        )
        for demo in _DEMOS
    }
    reference = per_demo["django"]
    differing = {
        demo: sorted(set(files) ^ set(reference))
        for demo, files in per_demo.items()
        if sorted(files) != reference
    }

    assert differing == {}, (
        f"the demos' histories differ: {differing}. The three run the same domain, so a migration "
        f"belongs in all three or in none."
    )


def test_an_alter_view_says_what_the_view_looked_like_BEFORE() -> None:
    """An `AlterView` whose two sides are the same view is a no-op that emits the wrong SQL.

    It is checkable and it went wrong three times in one afternoon, so it is checked. The `old` side
    of an `AlterView` describes the view AS IT WAS, and a global rename over the domain kept turning
    it into a copy of the `new` side — at which point `_projection_changed()` sees nothing, the
    operation emits `CREATE OR REPLACE VIEW`, and PostgreSQL answers `cannot change name of view
    column`.

    Nothing else could see it. The drift check compares the FINAL state and is happy either way; the
    coverage tally counts that an `AlterView` was built, not that it says anything. Only running the
    migrations caught it, and only after the failure had reached a real server.

    IT COMPARES FINGERPRINTS AND IT USED TO COMPARE SOURCE TEXT, which is the same lesson this
    repository keeps relearning. The old version read the file with `ast` and counted DISTINCT
    `view_definition` string literals, so it was measuring one REPRESENTATION of a view body. The
    day `0005` started carrying a `view_query` on its new side — the engine-agnostic shape, which is
    the whole reason the ORM stores a view uncompiled — the count fell to one and the test called a
    perfectly good migration an offender. `view_fingerprint` is the thing `AlterView` itself
    compares by: it renders either shape through one canonical dialect, so a query and a frozen
    string are comparable and neither is privileged.
    """
    from snakeorm.migration.ddl import view_fingerprint
    from snakeorm.migration.operations import AlterView

    offenders: list[str] = []
    checked = 0
    for demo in _DEMOS:
        for directory in sorted((_ROOT / demo / "apps").glob("*/migrations")):
            for migration in load(str(directory)):
                for operation in migration.operations:
                    if not isinstance(operation, AlterView):
                        continue
                    checked += 1
                    if view_fingerprint(operation.old) == view_fingerprint(
                        operation.new
                    ):
                        offenders.append(f"{demo}/{migration.version}")

    assert checked > 0, (
        "no `AlterView` was found in any demo's history, so this net just passed over nothing. "
        "Either the operation stopped being exercised — which its coverage tally would also have "
        "to say — or the walk above stopped finding migrations."
    )
    assert offenders == [], (
        f"these migrations build an AlterView whose two sides are the SAME view: {offenders}. The "
        f"`old` side has to describe the view AS IT WAS — otherwise the operation cannot tell a "
        f"changed FILTER from a changed PROJECTION, and emits a replacement where the engine needs "
        f"a drop and a create."
    )
