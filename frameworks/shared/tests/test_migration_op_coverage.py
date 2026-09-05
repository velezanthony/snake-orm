"""How many of the ORM's migration OPERATIONS the demos actually use, as a number that can only go up.

The twin of `test_orm_api_coverage.py`, one storey down, and it exists because the gap it measures
had been there since `frameworks/` began without anybody looking. That file asks whether an operation
with a reason to want `savepoint()` ever calls it; this one asks the same of `AlterColumn`,
`RenameColumn`, `AddCheck` and the twenty-odd others.

WHAT IT FOUND WHEN IT WAS WRITTEN. Five. `CreateTable`, `AddForeignKey`, `AddColumn`, `CreateView`
and `CreateIndex` — which between them are what a schema does on the day it is BORN. Every operation
that belongs to a schema that has since CHANGED was exercised nowhere but `src/test`: the demos had
twenty-nine tables and no history.

WHY THAT MATTERS MORE THAN IT SOUNDS. A migration is the one piece of an ORM whose failures are
expensive in exactly the situation where nobody is watching — a deploy, over data that already
exists, on a Tuesday. `src/test` proves each operation emits what it should; only a demo whose
domains EVOLVE proves that the emitted thing survives contact with a schema somebody is using. The
suite already caught one of these once: twenty-one migrations declared `TIMESTAMP` while the models
said `TIMESTAMPTZ`, and it lasted because the demos build their schema FROM THE MODELS and never run
their own migrations.

WHAT COUNTS AS EXERCISING. A migration file of a demo that INSTANTIATES the operation. Not a mention
in a comment, not an import: the call. It is read with `ast` for the same reason its sibling is — a
grep would count the operation names written in this very docstring.

WHAT IS NOT USED IS WRITTEN OUT BELOW WITH ITS REASON, IN TWO DICTIONARIES, and here the split
matters more than in either sibling: most of what is declared out was never work at all. One group
is the operations the demos CANNOT write, because they run on three engines and `realize` refuses
these on some of them; another is the two data migrations that would run over an empty database.
Filed as "not yet", they made this tally read "11 of 26" for ever — a shortfall of which only the
retirements could ever have been closed, and no amount of work would have moved the rest. A target
unreachable BY CONSTRUCTION is the other way of lying, and it is the way that survives audits,
because every line of it has a good reason written next to it.

THE SIZES OF THOSE GROUPS ARE NOT WRITTEN DOWN IN PROSE, and that is a lesson this file learned the
expensive way. Every figure about the lists themselves is built on the run, out of
`len(_OUT_OF_SCOPE)`, `len(_IN_SCOPE)` and `len(_operations())`, inside the assertion messages —
because the engine-refusal group GROWS. `AddCheck` and `DropCheck` joined it the day `inventory/0004`
was rewritten, and every sentence that had counted it, here and in
`test_every_engine_accepts_the_migration_plans.py`, went stale without one test going red. A count in
a docstring is a claim nothing checks.

So: `_NOT_YET` is the debt, and it closes by a domain RETIRING something. `_OUT_OF_SCOPE` is the
decisions, and they close by a different decision being taken — running the demos on one engine, or
seeding before migrating — which is not this list's to take.

AND `_NOT_YET` IS NOW EMPTY, which is the second half of the same lesson and cost the same kind of
measurement. The five that were left were the RETIREMENTS, all filed under one reason: «nothing has
been retired». Going to retire something for real is what showed that reason was the wrong shape.
Two of the five are refused by an engine and three by the demos' own shape, none of them closes by
writing a migration, and every one of them had been sitting in the dictionary called "pending" —
telling the next reader there was work here. There was not. The arguments are below, and each one
names the decision that would reopen it.

THREE DIRECTIONS ARE GUARDED, NOT TWO: using a `_NOT_YET` operation fails until it is struck off,
losing one that was used fails too, and an `_OUT_OF_SCOPE` operation that STARTS being built fails
as well — a migration that appears on SQLite's blacklist and in a demo's history is either a broken
demo or a decision nobody wrote down, and both want a red test.

AND THAT THIRD GUARD IS A BLACKLIST, which is why it has a sibling now. It can only fail over the
names written in `_OUT_OF_SCOPE`; an operation that no engine accepts and that nobody thought to
list passes it in silence — exactly the failure mode this repository deleted three language tests
over. `test_every_engine_accepts_the_migration_plans.py` asks the other question, of the whole
history, without a list: does `realize` accept this plan on this dialect? It found TWO migrations
the demos already carry that SQLite refuses outright, both built out of operations this file counts
as exercised and neither of them on any blacklist.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from snakeorm import migration

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMOS = ("django", "flask", "fastapi")


def _operations() -> frozenset[str]:
    """The migration operations the ORM offers, read FROM THE MODULE and not from a list.

    An operation is a CLASS that knows how to emit its SQL (`up_sql`) or to run its logic (`run`).
    The two `Protocol`s that define those shapes are excluded: they are the contract, not operations
    somebody can put in a migration.
    """
    found: set[str] = set()
    for name in dir(migration):
        value = getattr(migration, name)
        if not inspect.isclass(value) or name.startswith("_"):
            continue
        if getattr(value, "_is_protocol", False):
            continue
        if hasattr(value, "up_sql") or hasattr(value, "run"):
            found.add(name)
    return frozenset(found)


def _migration_files() -> list[pathlib.Path]:
    """Every migration file of the three demos, found by walking rather than by a list.

    A list of app names is what once left `src/examples/` outside a check for a whole migration, with
    the count coming out full over a universe that had been trimmed.
    """
    return sorted(
        path
        for demo in _DEMOS
        for path in (_ROOT / demo / "apps").glob("*/migrations/*.py")
        if path.name != "__init__.py"
    )


def _instantiated() -> set[str]:
    """Every operation NAME the demos' migrations call, collected with `ast`.

    The call and not the import: a file that imports `AlterColumn` and never builds one has not
    exercised it. Read with `ast` rather than grepped, for the same reason its sibling gives — a grep
    would count the names written in this file's own docstring.
    """
    used: set[str] = set()
    for path in _migration_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                used.add(node.func.id)
    return used & _operations()


# THE DECISIONS. Every entry this file carries, and not one of them was work somebody had failed to
# do. They are here so that the debt below is a number that can reach zero — and it has.
_OUT_OF_SCOPE: dict[str, str] = {
    # --- The engines cannot, and the demos run on all three ---------------------------------------
    #
    # These are NOT "nobody got round to it". The demos are engine-switchable (`DB_BACKEND` in the
    # root `.env`), so a migration only belongs in their history if all three can APPLY it, and
    # `realize` refuses these on the engines below. Writing one would break `make frameworks-test`
    # the moment somebody ran it on SQLite, which is the default.
    #
    # Closing them means running the demos on PostgreSQL only, which is a different decision from
    # this list. It is written out because the previous reasons here were invented — see #23 in the
    # bug journal — and an invented reason is worse than none: it closes the question.
    "AlterColumn": "SQLite refuses it (Cap.ALTER_COLUMN): the table would have to be rebuilt",
    "DropForeignKey": "SQLite refuses it, with its own message in `realize`",
    # These two WERE exercised, by `inventory/0004`, and that migration is the reason they are here
    # now. SQLite has no `ALTER TABLE ... ADD/DROP CONSTRAINT` (Cap.ADD_CONSTRAINT), so the pair was
    # the single place the whole history stopped on the default engine — the tally counted them
    # green while the demos did not come up. `RebuildTable` is the portable way to say the same
    # thing, the migration is rewritten with it, and these two go where `AlterColumn` and
    # `DropForeignKey` already were: an operation the demos cannot use because one of their three
    # engines cannot apply it. They close by the SAME decision as the rest of this group — the demos
    # migrating on PostgreSQL only.
    "AddCheck": "SQLite refuses it (Cap.ADD_CONSTRAINT); `RebuildTable` says it portably",
    "DropCheck": "SQLite refuses it (Cap.ADD_CONSTRAINT); `RebuildTable` says it portably",
    "CreateFunction": "SQLite and MySQL have no stored functions (Cap.STORED_FUNCTIONS)",
    "DropFunction": "SQLite and MySQL have no stored functions",
    "AlterFunction": "SQLite and MySQL have no stored functions",
    "CreateSchema": "SQLite and MySQL have no named schemas (Cap.SCHEMAS)",
    "DropSchema": "SQLite and MySQL have no named schemas",
    # The reason used to read "SQLite and MySQL do not store COMMENT ON", and half of it was one of
    # the invented reasons this block warns about: MySQL stores comments and now writes them as a
    # clause. Only SQLite is left, which is enough to keep the operation out — the bar here is all
    # THREE engines applying it, not two.
    "AlterTableComment": "SQLite stores no comment at all (Cap.COMMENTS); MySQL does, as a clause",
    #
    # --- The demos always migrate an EMPTY database -----------------------------------------------
    #
    # `verify.py` and the two `main`s do drop + migrate + seed, in that order, so a data migration
    # would always run over nothing. Writing one would tick this tally and prove nothing, which is
    # exactly the vacuous coverage this file exists to end — so it is refused on purpose rather than
    # gamed. Closing them needs a demo that migrates a database with rows in it, which is a decision
    # about how the demos BOOT and not about their schema history.
    "RunPython": "the demos drop + migrate + seed, so a data migration would run over an empty DB",
    "RunSQL": "same as RunPython, and the builder has covered every piece of DDL the demos needed",
    #
    # --- The half of a history where something is RETIRED -----------------------------------------
    #
    # These five sat in `_NOT_YET` for as long as this file has existed, under a single reason:
    # «nothing has been retired». The reason was true and the FILING was wrong, which is the harder
    # error to see — a debt is an instruction to somebody who has not read the argument yet, and
    # these five had no work in them to instruct anybody about.
    #
    # DELETION IS STILL WHERE THE SILENT FAILURE LIVES, and nothing here disputes that. A migration
    # that creates something and fails is noticed on the spot; one that deletes and fails halfway
    # leaves somebody without their data. The question this list answers is who can point at it, and
    # the answer measured out to be `src/test` and not a demo: all five are covered there, and the
    # three that most want a server have one — `test_drop_column_with_foreign_key.py` and
    # `test_triggers_e2e.py` run APPLIED, under `@pytest.mark.integration`. A demo cannot add to that
    # without either breaking on SQLite or growing decoration. Two of the five are an engine's
    # refusal; three are the demos' own shape.
    #
    # WHAT THE DEMOS HAVE RETIRED, so that "nothing has been retired" is not left standing as a
    # sentence: the redundant indexes of `orders/0002` and `taxonomy/0003`. That is why `DropIndex`
    # is not here — it is exercised, and it is the one deletion that needs neither a foreign key out
    # of the way nor a declarator to survive it.
    # RENAMING A TABLE is the one below that was not blocked by anything: it is a decision no domain
    # here has taken. And there is a twist worth writing, because the operation was built FOR the
    # rebuild and the rebuild does not use it: inside `_remake_table` the rename is one statement of
    # several, emitted as SQL, not a step of the plan — an operation there would be a plan inside a
    # plan. So `RenameTable` is what it always was on its own merits: a thing a user can now express
    # in a migration and could not before. Inventing a table rename to tick this line is exactly the
    # decoration this file exists to refuse.
    "RenameTable": (
        "no domain has renamed a table, and the operation that motivated it does not use it: "
        "`_remake_table` emits its `RENAME TO` as one statement among several, because inside a "
        "rebuild the rename is not a step of the plan. It stands on its own merits — renaming a "
        "table could not be expressed at all before it — and it closes the day a domain outgrows "
        "one of its names, not the day somebody needs a green line"
    ),
    "DropColumn": (
        "the one field a domain has outgrown is `posts.category_id` — re-verified, and the domain "
        "half of the argument is intact: `Post.category` is included, filtered and navigated by "
        "nothing, `create_post` writes it `None` on both colours, the only thing three demos ever "
        "show of a category is `Blog.categories.count()` (the number, never a category), and "
        "`taxonomy` classifies posts now, with tags that are many-per-post, nested and filterable. "
        "It is a FOREIGN KEY column, so it is gated by `DropForeignKey` a few lines up, and the gate "
        "was re-measured against SQLite 3.50.4 with the DDL this ORM actually emits — a table-level "
        "`CONSTRAINT ... FOREIGN KEY`, not the inline form: `ALTER TABLE posts DROP COLUMN "
        'category_id` answers `unknown column "category_id" in foreign key definition`, before AND '
        "after `categories` is dropped, and SQLite has no `DROP CONSTRAINT` to put in front of it. A "
        "column with no key on it drops portably on all three today, and every such column was "
        "measured to be a fact its domain writes. So this closes by the SAME decision as the whole "
        "«the engines cannot» group above — the demos migrating on PostgreSQL only — and not by a "
        "demo retiring anything"
    ),
    "DropTable": (
        "the table at the other end of that same retirement, `categories`, and it is out of reach "
        "for the entry above's reason: PostgreSQL and MariaDB both refuse to drop a table an FK "
        "still points at, so it goes after the child's column, which cannot go. Thirteen of the "
        "twenty-nine tables have nothing pointing at them and could be dropped portably today — "
        "measured off the relationship graph, not read off the models one at a time — and every one "
        "of them is the leaf its domain exists to write: the payments, the order lines, the stock "
        "movements, the tag bridge, the visits, the revisions, the deliveries. Retiring one of those "
        "to tick this line would be inventing dead weight in order to remove it"
    ),
    # DropView WAS here, and its reason turned on one sentence: «the one view was ALTERED rather
    # than retired». That stopped being true in `inventory/0004`. Nothing about `low_stock` was
    # retired to tick this line — the argument against that is intact and is why no entry replaced
    # it here — but the view now has to come DOWN and go back up across the column rename: MariaDB
    # freezes the names a view was written with and answers error 1356 afterwards, and SQLite cannot
    # remake a table a view is standing on. So the operation is exercised by a migration that needed
    # it, which is the only way this file ever wanted an entry closed.
    "DropTrigger": (
        "the one trigger is still wanted, and it cannot retire the way this operation usually "
        "arrives — a trigger whose rule becomes a `CHECK`, which is what this ORM's own guide "
        "prefers — because `tg_bump_visit_count` maintains a COUNTER on another table, and no CHECK "
        "can hold a running total. Retiring it means giving up `Post.visit_count`, which is "
        "denormalised precisely because counting `visits` does not scale. Re-measured: "
        "`CreateTrigger` is still built exactly once across the three demos, so there is no second "
        "trigger to retire either"
    ),
    "AlterTrigger": (
        "the one trigger's body has not changed since it was declared, and the refinement somebody "
        "reaches for first does not hold up: `tg_bump_visit_count` only counts UP, but nothing in "
        "the three demos ever deletes a visit — re-measured, no service, use case or route does — so "
        "the drift it would repair cannot happen, and a body written in order to be altered is the "
        "decoration this file exists to refuse. It is also the wrong shape twice over: `AFTER "
        "DELETE` has no `NEW` to read, so the fix would be a SECOND trigger, which is "
        "`CreateTrigger` and already exercised. And `logistics`, the domain that arrived after this "
        "reason was written, wants no trigger at all: its figures are computed per query — a "
        "distance, a box count, a window frame — and not one of them is a total kept on another "
        "table"
    ),
}


# THE DEBT, AND IT IS EMPTY. Everything the demos' migrations do not reach is a decision now, each
# one written out above with the argument that put it there and the decision that would reopen it.
#
# The dictionary stays. It is not ceremony: an operation added to the ORM tomorrow lands here by
# default, because `test_block_e_gap_is_still_open` reads `_IN_SCOPE` against what the migrations
# build, and the finish line `BLOCK-E-DONE` asserts that difference is empty. A new operation
# nobody exercises turns this file red on the day it appears, which is the right default and the
# reason the surface is read off the module instead of listed.
_NOT_YET: dict[str, str] = {}

# The surface the demos are MEANT to reach: every operation minus the ones declared out. It is the
# denominator of every figure here, and using `_operations()` instead is what made "11 of 26" a
# sentence that could never improve.
_IN_SCOPE = _operations() - set(_OUT_OF_SCOPE)

# The id a tally wears once it owes nothing. All three coverage files spell it the same, so a single
# selector reads the five tallies at once.
_DONE = "BLOCK-E-DONE"


def test_the_operations_are_discovered() -> None:
    """The introspection found operations. Without this, every tally below holds over an empty set.

    The ORM offers twenty-odd; a number well under that means `_operations()` stopped recognising
    them and the file is measuring nothing, which is precisely the state it was written to end.
    """
    assert len(_operations()) >= 20, f"only found: {sorted(_operations())}"


def test_the_demos_have_migrations_to_read() -> None:
    """And there are files to read. An empty walk would make "nothing uncovered" trivially true."""
    assert len(_migration_files()) >= 10, f"only found: {_migration_files()}"


def test_the_two_lists_name_real_operations_and_do_not_overlap() -> None:
    """Both lists name operations that EXIST: a renamed one must not linger on either.

    An entry left behind after a rename keeps the tally looking honest while describing an operation
    nobody can call. It is the same failure the sibling file guards, in the direction people forget.

    The overlap is checked in the same breath because it is the failure the split introduces and
    nothing else would catch: an operation that is owed AND declared out is one whose two reasons
    contradict each other, and whichever dictionary a reader opens first is the answer they keep.
    """
    ghosts = sorted((set(_NOT_YET) | set(_OUT_OF_SCOPE)) - _operations())
    both = sorted(set(_NOT_YET) & set(_OUT_OF_SCOPE))

    assert ghosts == [], (
        f"these are listed here and are not operations of the ORM: {ghosts}. They were renamed or "
        f"removed; fix the list, because an entry for something that cannot be called is a gap "
        f"that can never close."
    )
    assert both == [], (
        f"these are on BOTH lists: {both}. An operation is either owed or declared out of scope; "
        f"being on both means the two reasons disagree and nobody has noticed."
    )


def test_the_out_of_scope_decision_still_holds() -> None:
    """The third direction: an operation declared out of scope may not quietly start being built.

    On this tally the guard has teeth beyond the bookkeeping, and that is why it is worth having
    here even more than in the sibling files. Every entry of the «the engines cannot» group above is
    refused by `realize` on at least one engine the demos run on, so a migration that builds one is
    not merely an undocumented change of mind — it is a demo that breaks the moment
    `make frameworks-test` runs on SQLite, which is the default. This test says so at the point the
    migration is written rather than at the point somebody switches engine.
    """
    used = sorted(set(_OUT_OF_SCOPE) & _instantiated())

    assert used == [], (
        f"these are declared OUT OF SCOPE and a demo migration now builds them: {used}. The "
        f"decision changed and the reason next to it did not: "
        + "; ".join(f"{name} — {_OUT_OF_SCOPE[name]}" for name in used)
    )


@pytest.mark.parametrize("name", sorted(_NOT_YET) or [_DONE], ids=str)
def test_block_e_gap_is_still_open(name: str) -> None:
    """One test per operation still owed: building one fails here until it is struck off the list.

    A count kept in a comment drifts; a count kept as an assertion cannot. Written this way the work
    itself is what turns the suite red, and the fix is to delete the line that says the gap is
    still there.

    IT IS ONE TEST PER ENTRY, and that is what turns the tally from a guard into an answer.
    Collecting `-k block_e` across the three coverage files lists what is left, by name, over all
    five tallies at once, so «how much is left before the demos exercise the whole ORM» is something
    you RUN rather than something you read off a document somebody has to remember to update.

    A tally that owes nothing contributes one case named `BLOCK-E-DONE` instead of none, and that
    case asserts the finish line itself. It exists because an empty parametrisation collects
    nothing, and a selector that finds nothing looks identical whether the work is finished or the
    name was mistyped.
    """
    built = _instantiated()

    if name == _DONE:
        missing = sorted(_IN_SCOPE - built)
        assert missing == [], (
            f"nothing is on `_NOT_YET` and yet no demo migration builds these: {missing}. Either "
            f"put them back with a reason, or declare them out of scope with one."
        )
        return

    assert name not in built, (
        f"`{name}` is listed as not yet exercised and a demo migration now builds one. Strike it "
        f"off `_NOT_YET` in this file — the list IS the tally, and without it the operations stand "
        f"at {len(_IN_SCOPE - set(_NOT_YET))} of {len(_IN_SCOPE)} in scope "
        f"({len(_operations())} in total, {len(_OUT_OF_SCOPE)} declared out)."
    )


@pytest.mark.parametrize("name", sorted(_IN_SCOPE - set(_NOT_YET)), ids=str)
def test_the_operation_stays_exercised(name: str) -> None:
    """The other direction: an operation already covered may not quietly stop being used.

    Reported one per test so a regression names the operation instead of handing over a set. This is
    the half that catches a migration being deleted or squashed away, which is exactly how a demo
    loses coverage without anybody editing this file.
    """
    assert name in _instantiated(), (
        f"{name} is on neither list, so it is claimed as exercised, and no migration of the three "
        f"demos builds one. Either a migration that used it is gone, or it never was — put it back "
        f"on `_NOT_YET` with its reason."
    )
