"""Every migration the demos carry is a plan the three engines ACCEPT, and nobody was checking.

`shared/config.py` says it out loud — «all three run against any of the THREE engines, which is the
whole demonstration: the same domain, the same selectors and the same endpoints, changing one
variable» — and the three demos build their schema at boot by APPLYING `apps/*/migrations`, not by a
shortcut. So the promise is not decorative: with `DB_BACKEND=sqlite` the migrations are what has to
land, and if one of them cannot, the demo does not come up at all.

WHAT WAS GUARDING IT. `test_migration_op_coverage._OUT_OF_SCOPE` groups a run of operations under
«`realize` refuses on the engines below», and a test that fails if a demo migration builds one. That
test is a BLACKLIST: it can only fail over the names somebody wrote down. An operation that an engine
refuses and that nobody thought to list goes through it in silence — which is precisely the failure
this repository deleted three language tests over, and it had already happened twice. The size of
that group is not written here on purpose: it has already grown once, and a figure copied into a
neighbouring file is the half that stops being true without anything going red.

WHAT THIS FOUND ON THE DAY IT WAS WRITTEN. Two migrations, in all three demos, that SQLite refuses:
`inventory/0004` drops and re-adds a CHECK, and `taxonomy/0004` adds the self-referencing foreign key
to a `tags` table that already exists. `DropCheck`, `AddCheck` and `AddForeignKey` are all counted as
exercised one file over, and none of the three is on the blacklist, so nothing went red. They are
declared below with their reason, exactly the way the sibling declares its decisions — the point is
that the number can only go DOWN, and that a new one turns this red on the day it is written.

WHAT THIS CANNOT SEE, said plainly rather than left for somebody to discover. `realize` answers about
the SHAPE of a plan: which operations this engine knows how to perform. It cannot answer whether the
SQL an operation CARRIES is portable, because some of it is a frozen string — a `view_definition` in
a `CreateView` is engine SQL that was rendered once, and the demos' `inventory/0003` carried
`FROM "public"."warehouse_stock"`, which `realize` accepts and SQLite then rejects («view "low_stock"
cannot reference objects in database public»). MySQL had its own version of the same blindness: the
history stopped at `orders/0001` with `1071, Specified key was too long`, because a `snake_enum`
column reached the dialect as a bare `str` and MySQL answered TEXT. Nothing static could reach that
either — the plan was the right SHAPE and the width was wrong. It is FIXED (the width is derived
from `enum_type` the way the base type already was), and it is written here in the past tense rather
than deleted: it is the clearest example this file has of what its own name does not promise.

That is why the name is `accepts the migration plans` and not `the migrations are portable`. A test
that cannot deliver its own name is worse than no test, because it manufactures confidence — and the
name this one wears is the one it can keep.

AND THAT SENTENCE NOW HAS A SIBLING RATHER THAN JUST AN APOLOGY.
`test_every_engine_applies_the_migration_history.py` APPLIES the whole history against a real server
on each of the three engines, which is the only thing that can see a frozen string. It found no new
refusal on the day it was written, because it came after the two above had been fixed by hand; what
it does is stop them being findable only by hand. It has since earned its keep in the OTHER
direction, which is the one nobody remembers to guard: when the MySQL width bug was fixed, it was
that file that went red over a declared stop that had stopped happening. The two files split the work the way their names say: this one needs no
server and lists EVERY refusal, that one needs a server and can only report the FIRST one, because
after a migration a server refused, everything downstream references tables that were never created.

ONE HISTORY ON DISK, AND THAT IS NEW TOO. The twenty files live once, in `shared/migrations/`, and
each demo's `apps/<domain>/migrations` is a symlink to them. They used to be sixty files —
byte-identical copies, except for seven where Django's carried one generator docstring and the other
two carried another, which is drift that had already happened and that nothing was comparing.
`test_the_three_demos_share_one_history_on_disk` is what holds the symlinks in place now; the
comparison below survives it because a symlink is a thing somebody can replace with a copy.
"""

from __future__ import annotations

import pathlib

import pytest
from snakeorm import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import SnakeDialect
from snakeorm.migration import load, realize

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMOS = ("django", "flask", "fastapi")

# The three engines the demos claim to run on, built here rather than taken from `shared.config`:
# that one reads `DB_BACKEND` and would hand back whichever ONE the `.env` names, which is the very
# thing that let this go unseen — the repository's `.env` says `postgres`, and postgres is the only
# engine any of this was ever tried on.
_ENGINES: tuple[tuple[str, SnakeDialect], ...] = (
    ("postgres", PostgresDialect()),
    ("mysql", MySQLDialect()),
    ("sqlite", SQLiteDialect()),
)


# WHAT AN ENGINE ALREADY REFUSES, keyed `<engine>/<app>/<version>` and holding the reason. It is a
# declaration and not a skip list: every entry is a place the demos do NOT run on that engine, and
# the tests below fail in BOTH directions — a refusal that is not here, and an entry here that has
# stopped refusing.
#
# BOTH ENTRIES HAVE GONE, and how they went is the part worth keeping. They said `inventory/0004`
# needed "the rename to travel without a CHECK being dropped" and `taxonomy/0004` needed "the self-FK
# to be born with the table" — two demands neither file could meet, because the CHECK does change and
# the table is older than the key. What was missing was a third way of SAYING the change:
# `RebuildTable` puts the table's constraint shape before and after in the migration file itself, and
# each dialect spells it — the minimal `ALTER` where there is one, the whole rebuild where there is
# not. The two files are rewritten with it and SQLite lands all twenty.
#
# THE DICTIONARY IS EMPTY AND STILL DOES ITS JOB: with no entries the first assertion below reads
# "no engine refuses anything anywhere", which is what this file is for.
_ALREADY_REFUSED: dict[str, str] = {}


def _migrations(demo: str) -> list[tuple[str, str]]:
    """Every `(app, version)` of a demo's history, in the order the runner would apply it.

    Found by walking `apps/*/migrations`, never from a list of app names: a list is what once left a
    whole tree outside a check and reported the count full over a universe that had been trimmed.
    """
    found: list[tuple[str, str]] = []
    for directory in sorted((_ROOT / demo / "apps").glob("*/migrations")):
        for migration in load(str(directory)):
            found.append((directory.parent.name, migration.version))
    return found


def _refusals(demo: str, engine: str, dialect: SnakeDialect) -> dict[str, str]:
    """Every `<engine>/<app>/<version>` of this demo that `realize` will not land, with its message.

    It calls exactly what `MigrationRunner` calls, on exactly the operations the file declares. A
    check that rebuilt the plan some other way would be measuring a shape the demos never apply.
    """
    refused: dict[str, str] = {}
    for directory in sorted((_ROOT / demo / "apps").glob("*/migrations")):
        for migration in load(str(directory)):
            try:
                realize(migration.operations, dialect)
            except SnakeMigrationError as error:
                key = f"{engine}/{directory.parent.name}/{migration.version}"
                refused[key] = str(error)
    return refused


@pytest.mark.parametrize("demo", _DEMOS)
def test_the_demo_has_a_history_to_check(demo: str) -> None:
    """That migrations were found at all, before anything below claims they are all accepted.

    The trap of every test that discovers files: if the glob stops matching, "no engine refuses
    anything" holds over an empty history and the guard becomes decoration.
    """
    found = _migrations(demo)

    assert len(found) >= 10, f"only found in {demo}: {found}"


@pytest.mark.parametrize("engine", [name for name, _ in _ENGINES])
def test_the_declared_refusals_name_migrations_that_exist(engine: str) -> None:
    """A declared refusal points at a migration that is still there, in all three demos.

    An entry left behind after a migration is renamed or squashed keeps this file looking honest
    while excusing something nobody can apply. It is the same guard the coverage files carry against
    an entry for an operation that no longer exists, in the direction people forget.
    """
    declared = {key for key in _ALREADY_REFUSED if key.startswith(f"{engine}/")}
    real = {
        f"{engine}/{app}/{version}"
        for demo in _DEMOS
        for app, version in _migrations(demo)
    }
    ghosts = sorted(declared - real)

    assert ghosts == [], (
        f"these are declared as refused by {engine} and no demo has such a migration: {ghosts}. "
        f"They were renamed or removed; fix the list, because an excuse for a file that does not "
        f"exist can never be paid off."
    )


@pytest.mark.parametrize("engine,dialect", _ENGINES, ids=[name for name, _ in _ENGINES])
def test_the_engine_accepts_every_migration_plan(
    engine: str, dialect: SnakeDialect
) -> None:
    """`realize` lands the whole history on this engine, except what is declared above.

    Both directions in one assertion, because they are one fact: a refusal that is not declared is a
    demo that does not boot on this engine, and a declared refusal that no longer happens is an
    excuse outliving its reason. The message carries the engine's own words, which is what somebody
    fixing it needs.
    """
    declared = {key for key in _ALREADY_REFUSED if key.startswith(f"{engine}/")}
    refused = {
        key: message
        for demo in _DEMOS
        for key, message in _refusals(demo, engine, dialect).items()
    }

    unexpected = sorted(set(refused) - declared)
    healed = sorted(declared - set(refused))

    assert unexpected == [], (
        f"{engine} refuses migrations nobody declared, so the demos do not come up on it with "
        f"`DB_BACKEND={engine}`: "
        + "; ".join(f"{key} — {refused[key]}" for key in unexpected)
    )
    assert healed == [], (
        f"these are declared as refused by {engine} and `realize` now takes them: {healed}. Strike "
        f"them off — a declaration that has stopped being true is the next reader's wrong map."
    )


@pytest.mark.parametrize("engine,dialect", _ENGINES, ids=[name for name, _ in _ENGINES])
def test_the_three_demos_are_refused_the_same_things(
    engine: str, dialect: SnakeDialect
) -> None:
    """The three demos share one history per domain, so an engine must refuse them identically.

    It is the premise of `frameworks/` — the same domain served three ways — and the half that goes
    wrong silently is one demo's migration drifting from its twins. Here that shows up as an engine
    accepting two of the three, which is a difference no page would ever surface.
    """
    per_demo = {
        demo: sorted(key.split("/", 1)[1] for key in _refusals(demo, engine, dialect))
        for demo in _DEMOS
    }
    distinct = {tuple(value) for value in per_demo.values()}

    assert len(distinct) == 1, (
        f"{engine} does not refuse the same migrations in the three demos, so their histories have "
        f"drifted: {per_demo}"
    )


def test_the_three_demos_share_one_history_on_disk() -> None:
    """The three demos' migration directories are ONE directory, reached three ways.

    THIS IS THE NET THAT REPLACED SIXTY FILES. Each domain's history used to exist three times, once
    per demo, byte-identical and compared by nothing — so three places to fix a migration and three
    places for one to drift. Seven of them already had: Django's copy said «Editable by hand» where
    the other two said «Hand-editable», a difference nobody chose and nobody could have seen.

    It resolves the paths rather than diffing the files, and the difference is the whole point. A
    content comparison goes green over three copies that happen to agree today, which is exactly the
    state this replaced; resolving to one inode is the only assertion that says they CANNOT disagree
    tomorrow. It is also what catches the specific way this arrangement dies: somebody's tool
    replaces a symlink with a real directory and everything keeps working, silently, until the day
    two of them differ.
    """
    resolved: dict[str, set[pathlib.Path]] = {}
    for demo in _DEMOS:
        for directory in sorted((_ROOT / demo / "apps").glob("*/migrations")):
            resolved.setdefault(directory.parent.name, set()).add(directory.resolve())

    assert resolved, "no `apps/*/migrations` was found in any demo"
    shared_by_two_or_three = {
        domain: sorted(str(path) for path in paths)
        for domain, paths in resolved.items()
        if len(paths) != 1
    }

    assert shared_by_two_or_three == {}, (
        f"these domains do not resolve to ONE history: {shared_by_two_or_three}. The files live in "
        f"`shared/migrations/<domain>` and each demo reaches them through a symlink; a copy here is "
        f"a fork nobody will notice until the two halves say different things."
    )
    outside = sorted(
        str(next(iter(paths)))
        for paths in resolved.values()
        if (_ROOT / "shared" / "migrations") not in next(iter(paths)).parents
    )

    assert outside == [], (
        f"these histories resolve outside `shared/migrations/`: {outside}. One copy is the point, "
        f"and `shared/` is where the demos' shared things live — a history parked inside one demo "
        f"is a history that demo owns."
    )
