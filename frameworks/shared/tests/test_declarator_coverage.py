"""How many of the ORM's DECLARATORS the demos actually declare with, and which ones they do not.

Third of the three tallies, and the one that measures the other end of the ORM. `test_orm_api_coverage`
counts what the demos CALL at runtime; `test_migration_op_coverage` counts what they MIGRATE with.
Neither of them can see a declarator, because a declarator runs once at import and leaves metadata
behind — by the time a page calls anything, `snake_check` has already done its whole job.

THE SURFACE IS MEASURED, NOT LISTED. It is every public `snake_*` callable the package exports, read
off the package itself. A hand-written list is how the previous tally came to say "26 of 34" over a
list of nine gaps — 34 minus 9 is 25, and both numbers were in the same line of the same table. It
had also gone stale in the other direction: `snake_trigger` was named as covered AND as pending,
because somebody struck it off one half of the sentence.

WHAT COUNTS AS EXERCISED. A demo file importing the name from `snakeorm` and referring to it. The
import is what makes the match honest: `request.snake_session` is an attribute the middleware hangs
on a request and has nothing to do with the `snake_session()` declarator, and a check on the bare
word would have counted it. Referring to the NAME rather than calling it is what catches `@snake_abstract`,
which is spelled without parentheses and which a call-shaped check reports as unused.

THE SUITES DO NOT COUNT, and the reason is the same one the sister nets give: a declarator written so
that the tally goes up proves nothing. It has to be a model a page reads, or it is decoration.

WHAT IS NOT DECLARED SITS IN TWO DICTIONARIES, AND THEY ARE DIFFERENT KINDS OF THING. `_NOT_YET` is
a DEBT: a domain has not asked the question that wants the declarator, and it closes by the domain
growing one. `_OUT_OF_SCOPE` is a DECISION already taken, and it never closes. Held together, as
they were, the surface could not be reached however much work got done — and a target unreachable BY
CONSTRUCTION is the other way of lying, the one hardest to see here, because a decision parked among
debts looks exactly like work somebody will eventually get to.

THREE DIRECTIONS ARE GUARDED, NOT TWO: declaring with a `_NOT_YET` entry fails until it is struck
off, losing one that was declared fails too, and an `_OUT_OF_SCOPE` entry that STARTS being declared
fails as well — because the decision changed and its reason did not.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import snakeorm

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The four roots, whole — never a package list somebody has to remember to extend.
_ROOTS = ("shared", "django", "flask", "fastapi")

_SKIPPED_DIRECTORIES = (
    "__pycache__",
    "node_modules",
    "tests",
    "migrations",
    ".mypy_cache",
)
_SKIPPED_FILES = ("verify.py",)

# Read off the package. Anything new that appears here counts as a gap until the list below says
# otherwise, which is the right default: a declarator nobody declares with is exactly what this
# file exists to surface.
_DECLARATORS = frozenset(
    name
    for name in dir(snakeorm)
    if name.startswith("snake_") and callable(getattr(snakeorm, name))
)


# Everything no demo declares with, and why. The shapes are worth telling apart, because they are
# not the same kind of thing at all:
#
#   * NOT YET — the domain that would want it is not written. These close by growing a demo.
#   * THE ORM'S OWN GAP — the declarator cannot be used PORTABLY because of something the ORM does
#     not do yet. This is the only shape that is work on the ORM, and it hides easily: read quickly,
#     it looks like the one below it.
#   * NOT WHAT THE DEMOS ARE — the declarator serves a mode this layer deliberately does not use.
#
# ONLY THE FIRST SHAPE IS A DEBT, and that is the whole point of the split: it closes by a demo
# growing, and the two below it never do. Held in one list, as they were, "the demos declare with
# everything the ORM offers" was a sentence no amount of work could make true — unfalsifiable rather
# than ambitious.
#
# `_NOT_YET` below holds the first shape. `_OUT_OF_SCOPE`, under it, holds the other two, and it is
# longer than anybody expected: the MIDDLE shape turned out on inspection not to be an ORM gap at
# all, which moved four declarators and two session methods across in one go. That story is told
# down there, next to the entries it settles.
_NOT_YET: dict[str, str] = {
    # EMPTY, and the heading is kept over nothing on purpose: this is where a declarator goes when
    # the ORM offers it and no domain has yet asked the question that wants it. An empty dictionary
    # is a CLAIM — that the demos declare with every declarator in scope — and it is the claim this
    # file exists to make checkable. The `BLOCK-E-DONE` case below is what asserts it.
    #
    # HOW THE LAST SEVEN CAME OFF is worth keeping, because it is the only way this tally means
    # anything. They were `snake_ceil`, `snake_floor`, `snake_sqrt`, `snake_power`, `snake_range`,
    # `snake_following` and `snake_date_sub`, and not one of them was closed by somebody going and
    # calling it. A DOMAIN grew — `logistics`, deliveries out of depots — and it turned out to want
    # all seven before it had a single page:
    #
    #   * which depot is nearest to this address is a DISTANCE, which is a square root over a sum of
    #     squares. It is the `ORDER BY` key of the delivery sheet, so the ranking happens where the
    #     rows are and only the three that win travel.
    #   * how many boxes for `n` units is `n / per_box` rounded UP, and how many leave SEALED is the
    #     same division rounded down. Both go on one picking slip and the gap between them is the
    #     loose picking somebody does by hand. This was the objection that had kept the pair here:
    #     the figures that could round were MONEY. These are not — they are a count of boxes — and
    #     the rule about money is untouched, which is what made the close honest rather than clever.
    #   * how busy is an HOUR is a window whose span is a VALUE, which is exactly what the old reason
    #     said would retire `snake_range`: two vans booked at nine are one band and read one figure,
    #     where `ROWS` would give each of them a window of its own. And the band is CENTRED, because
    #     a dispatcher is squeezed by what is waiting at ten as much as by what came in at eight —
    #     which is the "centred average" `snake_following`'s reason named and no report had asked for.
    #   * when must the van LEAVE is the promise shifted BACKWARD by the lead. `billing` shifts a
    #     date forward to find a due date and its reason said half a pair is not an answer; backwards
    #     scheduling is the other half, and it is the only direction a dispatch deadline moves.
    #
    # `snake_coalesce` and `snake_nullif` came off the same way one phase earlier: not by somebody
    # deciding to use them, but by a warehouse holding nothing and a pair holding nothing. One
    # reported `None` in a field declared `int`; the other divided by zero, which PostgreSQL refuses
    # and SQLite answers in silence.
}


# THE DECISIONS. Each one written as a decision rather than as a delay: none of these closes by a
# demo growing, because a demo growing TOWARDS one of them is the decoration this file exists to
# refuse. The guard below fails if one starts being declared with — a decision that has stopped
# holding is a decision nobody has revisited, and its reason goes on reading like a reason long
# after it stopped being one.
#
# FOUR OF THEM ARE ONE ARGUMENT, AND IT TOOK TWO AUDITS TO SEE IT. The chain was drawn correctly the
# first time and filed under the wrong heading both times:
#
#     a routine's body is RAW ENGINE SQL that the caller writes
#       -> a shared model declaring one stops being portable    (`snake_function`)
#         -> so no demo can declare a FUNCTION or a PROCEDURE
#           -> so there is nothing to call                      (`call`, `execute_procedure`, in
#                                                                the sibling tally)
#             -> and nothing needs the row container            (`snake_row`)
#
# THE FIRST AUDIT got the ROOT wrong. `Cap.STORED_FUNCTIONS` on the MySQL dialect used to say the
# ORM "does not know how to emit CREATE FUNCTION in its grammar", so the chain was filed as pending
# work on the ORM. Reading `emit_create_function` shows there is no grammar to know: it returns the
# caller's raw `body` and never consults a dialect. The message was believed instead of the code,
# which is the failure this repository documents everywhere and which a tally is especially good at
# hiding.
#
# Measured afterwards, the real difference is between the two engines ONE dialect serves:
#
#     CREATE OR REPLACE FUNCTION      MariaDB 11.8  ->  works, and replaces
#                                     MySQL 8.4     ->  ERROR 1064, syntax error
#
# So it is not "the ORM has not got round to it" and it is not purely "the engine cannot" either:
# supporting MySQL means a DROP-then-CREATE strategy for engines without replace. That is a decision
# about migrations, and it is written here so the next person makes it with the numbers rather than
# with a sentence somebody wrote once.
#
# THE SECOND AUDIT got the SHAPE wrong, and this is the one that cost a plan. With the root corrected
# the chain still sat under "not yet", so a roadmap read the tally, saw four declarators and two
# session methods apparently waiting on somebody, and wrote down a task to close them — a stored
# FUNCTION returning stock availability per warehouse. That task would have put one engine's raw SQL
# inside a model that three engines share: the exact decoration these nets exist to refuse, proposed
# in good faith BECAUSE THE TALLY SAID IT WAS OWED.
#
# That is the cost of filing a decision as a debt, and it is not a bookkeeping cost. A debt is an
# instruction to somebody who has not read the argument yet. The entries below are the argument —
# how many of them there are is what `len(_OUT_OF_SCOPE)` answers in the messages further down, and
# this line said "four" while the dictionary held seven.
_OUT_OF_SCOPE: dict[str, str] = {
    "snake_function": (
        "a routine's body is raw engine SQL, so a shared model declaring one stops being portable, "
        "and every model here runs on the three. Underneath that: SQLite cannot store functions at "
        "all, and MySQL and MariaDB disagree about CREATE OR REPLACE, which is what replacing a "
        "routine relies on. Closing this would mean breaking the rule this whole layer exists to "
        "demonstrate — a model written once runs on all three — so it is a decision, not a delay"
    ),
    "snake_row": (
        "it is the container for `session.call()` and `session.raw()`, and BOTH of its halves are "
        "declared out of scope in the sibling tally: the builder covers every query the demos ask "
        "for, and no demo can declare the routine that `call` would call. A container whose only "
        "two contents are decisions is a decision itself"
    ),
    "snake_session": (
        "it resolves a DSN by configuration, and the demos build their driver per framework — a "
        "database per demo, wrapped in `CaptureDriver` so the debug panel can see the queries. That "
        "wrapper is how the panel exists at all, so the convenience is not one this layer can take"
    ),
    "snake_on": (
        "a handler receives the INSTANCE and nothing else — no session — so it can neither query "
        "nor write. What is left is a same-row veto, and this ORM's doctrine puts a same-row "
        "invariant in the engine as a CHECK, which is what `snake_checks` already does on `Stock`. "
        "A signal here would duplicate a constraint that holds better where it is"
    ),
    "snake_db_first": (
        "it mirrors a table the application does NOT govern, and the demos govern all twenty-nine: "
        "they drop, migrate and seed on every boot. There is no foreign table to mirror. Growing "
        "one would not be a demo with one more feature, it would be a SECOND doctrine living inside "
        "the same application — db-first is the mirror of a sysadmin's schema, which the migrations "
        "ignore on purpose. It stays covered where it belongs, in `src/test/introspection/`"
    ),
    "snake_substring": (
        "no page shows a TRUNCATED string, and none should. Cutting a name to fit is a job for CSS, "
        "which knows the width; the database does not and never will"
    ),
    "snake_replace": (
        "no domain rewrites text on its way OUT of the database, and normalising text belongs to "
        "the layer that WRITES it, not to the one that reads it. Building a page that needed this "
        "would be inventing a defect in order to fix it in the wrong place"
    ),
}

# The surface the demos are MEANT to reach. It is the whole package minus what has been declared
# out, and it is the denominator every figure in this file uses: measuring against `_DECLARATORS`
# would go on reporting a shortfall that no work can ever close.
_IN_SCOPE = _DECLARATORS - set(_OUT_OF_SCOPE)

# The id a tally wears once it owes nothing. All three coverage files spell it the same, so a single
# selector reads the five tallies at once.
_DONE = "BLOCK-E-DONE"


def _sources() -> list[pathlib.Path]:
    """Every application file under the four roots. The suites and the migrations are not one."""
    return [
        path
        for root in _ROOTS
        for path in sorted((_ROOT / root).rglob("*.py"))
        if not any(part in _SKIPPED_DIRECTORIES for part in path.parts)
        and path.name not in _SKIPPED_FILES
    ]


def _declared_in(path: pathlib.Path) -> set[str]:
    """The declarators this file imports from the ORM and then names.

    Both halves are needed. Without the import, `request.snake_session` reads as a use of the
    declarator; without the naming, `@snake_abstract` — which takes no parentheses — reads as unused.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("snakeorm")
        for alias in node.names
    }
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id in imported
        and node.id in _DECLARATORS
    }


def _declared() -> set[str]:
    """Every declarator the demos declare with."""
    return {name for path in _sources() for name in _declared_in(path)}


def test_there_are_sources_to_look_at() -> None:
    """That the scan found files and recognises a declarator it must recognise.

    The trap of every check that discovers its own input: with the roots mismatched, "nothing is
    missing" holds over an empty set and the tally turns into decoration. `snake_model` is the sanity
    probe, because a demo without one would not have a single model in it.
    """
    sources = _sources()

    assert len(sources) >= 50, f"only {len(sources)} source files found under {_ROOTS}"
    assert len(_DECLARATORS) >= 30, sorted(_DECLARATORS)
    assert "snake_model" in _declared(), (
        "no `snake_model` was found in the demos, so every declarator would read as a gap. Either "
        "the roots stopped matching or the models moved."
    )


def test_the_two_lists_name_declarators_that_exist_and_do_not_overlap() -> None:
    """Both lists are spelled against the real package, so a rename cannot leave a ghost behind.

    A declarator renamed in the ORM would otherwise sit here for ever as a gap nobody can close,
    and the tally would be counting something that no longer exists.

    The overlap is checked here too, because it is the one failure the split introduces and nothing
    else would catch: a name on both lists is a declarator that is owed and declared out at the same
    time, and whichever dictionary a reader opens first is the answer they walk away with.
    """
    ghosts = sorted((set(_NOT_YET) | set(_OUT_OF_SCOPE)) - _DECLARATORS)
    both = sorted(set(_NOT_YET) & set(_OUT_OF_SCOPE))

    assert ghosts == [], (
        f"these are listed here and the package does not export them any more: {ghosts}"
    )
    assert both == [], (
        f"these are on BOTH lists: {both}. A declarator is either owed or declared out of scope; "
        f"being on both means the two reasons disagree and nobody has noticed."
    )


def test_nothing_that_was_declared_stops_being_declared() -> None:
    """A declarator the demos used and no longer use is a domain that got thinner without saying so.

    This is the direction that protects what has already been won. The tests below protect the
    direction the work goes in, and a tally with only one of the two can be satisfied by deleting.
    """
    lost = sorted((_IN_SCOPE - set(_NOT_YET)) - _declared())

    assert lost == [], (
        f"these were declared by the demos and are not any more: {lost}. Either a domain lost the "
        f"declaration, or it moved into a test — which does not count, and on purpose."
    )


def test_the_out_of_scope_decision_still_holds() -> None:
    """The third direction: a declarator declared out of scope may not quietly start being used.

    This is the guard the split makes necessary, and it is why `_OUT_OF_SCOPE` is a dictionary and
    not a paragraph. Every entry there is a claim about the demos — «no page shows a truncated
    string» — and a claim can stop being true without anybody going back to the sentence that made
    it. Unguarded, the reason ages into a lie that reads exactly like a reason.

    Closing this is never striking the line off. It is moving the entry back to `_NOT_YET`, or
    deciding the decision was wrong and writing THAT down. Either way a sentence changes, which is
    the whole point: a decision that is reversed in code and not in prose was never a decision.
    """
    used = sorted(set(_OUT_OF_SCOPE) & _declared())

    assert used == [], (
        f"these are declared OUT OF SCOPE and a demo now declares with them: {used}. The decision "
        f"changed and the reason next to it did not: "
        + "; ".join(f"{name} — {_OUT_OF_SCOPE[name]}" for name in used)
    )


@pytest.mark.parametrize("name", sorted(_NOT_YET) or [_DONE], ids=str)
def test_block_e_gap_is_still_open(name: str) -> None:
    """One test per declarator still owed: declaring with it fails here until it is struck off.

    A number written in prose ages the moment somebody does the work and forgets the prose — which
    is precisely what happened to the line that said "26 of 34" over a list of nine. Written as an
    assertion it cannot: the work itself turns the suite red, and the fix is to delete the line.

    IT IS ONE TEST PER ENTRY, and that is what turns the tally from a guard into an answer.
    Collecting `-k block_e` across the three coverage files lists what is left, by name, over all
    five tallies at once, so «how much is left before the demos exercise the whole ORM» is something
    you RUN rather than something you read off a document somebody has to remember to update.

    A tally that owes nothing contributes one case named `BLOCK-E-DONE` instead of none, and that
    case asserts the finish line itself. It exists because an empty parametrisation collects
    nothing, and a selector that finds nothing looks identical whether the work is finished or the
    name was mistyped.
    """
    declared = _declared()

    if name == _DONE:
        missing = sorted(_IN_SCOPE - declared)
        assert missing == [], (
            f"nothing is on `_NOT_YET` and yet these are not declared with: {missing}. Either put "
            f"them back with a reason, or declare them out of scope with one."
        )
        return

    assert name not in declared, (
        f"`{name}` is listed as not yet declared and a demo now declares with it. Strike it off "
        f"`_NOT_YET` in this file — the list IS the tally, and without it the surface stands at "
        f"{len(_IN_SCOPE - set(_NOT_YET))} of {len(_IN_SCOPE)} in scope "
        f"({len(_DECLARATORS)} in total, {len(_OUT_OF_SCOPE)} declared out)."
    )
