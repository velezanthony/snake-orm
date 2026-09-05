"""How much of the ORM's API the demos actually USE, as a number that can only go up.

`frameworks/` is the only place where SnakeORM is exercised the way an application would exercise
it: a server in front, a real database and somebody clicking. `src/test` proves each piece works;
a demo proves it works WHEN SOMETHING USES IT. So the question worth pinning is not "does
`savepoint()` have a test" — it does — but "does anything with a reason to want one ever call it".

Measured when this was written: 13 of 24 `SnakeSession` methods and 8 of 16 user-facing `SnakeQuery`
methods. The rest was not marginal — the whole of concurrency control, streaming (`iterate`), the
compounds and the aggregates that a report is made of.

CONCURRENCY CONTROL IS THE PART THAT HAS SINCE CLOSED, and how it closed is the point of the exercise
rather than a detail of it. `for_update`, `savepoint` and `set_isolation` came off this list because
the `orders` domain grew two operations that WANT them — reserving stock two customers are competing
for, and settling an order whose billing can fail on its own — not because somebody went looking for
three methods to call. The proof is in `test_orders_concurrency.py`, where the reservation is red
when the lock is taken out.

STREAMING AND THE AGGREGATES CLOSED THE SAME WAY, one phase later. `iterate` came off the session's
list because two pages EXPORT a result that has no business being held in memory, and `having`,
`join`, `distinct` and `union` came off the query's because two pages report figures a `filter`
cannot produce. Same rule as before: each of them arrived with a question that wanted it, not with
somebody hunting for four methods to call. `union` is the one worth reading twice — almost every
compound over a single table is an `OR` in disguise, and this one is not only because each branch
keeps its own `LIMIT`, which is a bound no `WHERE` can express.

`union_all` WAS THE LAST ONE AND IT CLOSED FROM THE OTHER SIDE OF THAT SAME ARGUMENT. The order
report wants the deduplication — an order that is both the biggest and the newest is one row of the
answer — and the shape this reason held out for was a ledger whose duplicate IS a datum. The
movement book is it: two systems write the movements of a warehouse, the shop and the floor, and it
prints the last lines of each. Two units of one SKU leaving one warehouse at one instant are two
shipments, so folding them loses a unit the stock still says left.

What the old reason could not see is WHERE such a ledger comes from, and it is the part worth
keeping. It said a duplicate row of a keyed table is not a datum, and that is exactly right: over a
table `only()` puts the primary key back and `defer()` refuses to drop it, so every projection is
unique by construction and `union` has nothing to remove. What it did not follow through is that a
`@snake_view` has no primary key — a read-only row cannot be written back, so there is no identity
to preserve — and `defer(StockLedger.id)` is therefore allowed. `stock_ledger` is the movements read
as facts, and it is the only shape in this ORM where the two operators give different answers.

BOTH SESSION TALLIES ARE NOW FULL, and the last four came off in one batch by growing three domains:

- `recursive` — `taxonomy` gained a TREE. A taxonomy is a hierarchy, the word means nothing else, and
  the two questions a reader arrives with — where am I, what is under this — are the same walk in
  opposite directions. Neither has a shape in a plain SELECT: two `include`s reach a grandparent and
  stop, and the honest alternative is one query per level, an N+1 whose N is the depth of somebody
  else's data. The pages draw the breadcrumb, and `test_taxonomy_tree.py` asserts the STATEMENT COUNT
  while the tree is three deep, because the content assertions pass either way.
- `only` — `engagement` gained the traffic export the previous reason had already NAMED. `visits` is
  the volume table and it carries a `user_agent` no column of that file prints.
- `defer` — and this one parted company with `only`, which the old reason ("see `only`") had not
  foreseen: ONE query cannot be both, and the two verbs are not two spellings of one thing. `only`
  names what to keep, which freezes the list at whatever the table has today; `defer` names what to
  leave, which keeps meaning "everything except the wide one" as the table grows. So `defer` closed
  in `content`, over a post's edit history: `post_revisions.body` is an article, and a sidebar that
  draws two hundred dates has no business sending two hundred copies of one.
- `refresh`, on BOTH sides of the colour line — `engagement` already had a TRIGGER keeping
  `Post.visit_count`, and recording a visit now answers with the number the ENGINE wrote. The post is
  read before the write, the trigger moves the row underneath it, and the same instance is taught
  what the row says. A `refresh` of a row nobody else touched would have proved nothing.
- `iterate` on `AsyncSession` — the FastAPI demo grew the CSV route the old reason asked for. It also
  took a fix to this file's own reader, which is written up at `_awaited`: the call had been there
  for three exports and the three-form syntax test could not see it.

Two of those closings turned up ORM defects rather than demo gaps, which is the argument for this
whole exercise stated as an outcome. `iterate()` over an `only()` raised from the mapper on both
colours, and `AsyncSession.all` did the same — the SQL was narrowed and the hydration was not. Both
are fixed in `src/snakeorm/session/`, and neither was reachable until a domain asked the question.

WHAT IS NOT EXERCISED IS WRITTEN OUT BELOW WITH ITS REASON, IN TWO DICTIONARIES THAT ARE NOT TWO
HALVES OF ONE THING. `_NOT_YET` is a DEBT — it closes by the domain growing a question that wants
the method. `_OUT_OF_SCOPE` is a DECISION already taken, and it never closes. Held in one dictionary
they were indistinguishable, and the tally could not reach the whole of its surface however much
work got done: a goal unreachable BY CONSTRUCTION is the other way of lying, and the one this file
was least able to see, because every entry on it looked like work somebody would eventually do.

THREE DIRECTIONS ARE GUARDED, NOT TWO. Covering a `_NOT_YET` entry fails until it is struck off;
losing one that was already covered fails too; and an `_OUT_OF_SCOPE` entry that STARTS being
exercised fails as well, because a decision that has stopped holding is one nobody has written down
yet. That third direction is the one a decision rots in — a reason parked next to a fact that has
quietly become false reads exactly like a reason that still stands. A count kept in a comment
drifts; a count kept as an assertion cannot.

WHAT COUNTS AS EXERCISING. Not the tests. A `session.savepoint()` written inside a test so the
method has a caller proves that the method exists, which was never in doubt — the plan this file
comes from says exactly that. What counts is the DOMAIN and the three demos: `shared/` minus its
tests, and `django/`, `flask/` and `fastapi/` minus theirs. A method reaches this list by being
wanted by an operation, not by being ticked off.

HOW IT LOOKS. The source is parsed with `ast` and every `something.name(...)` is collected, which
reads no comments and no strings — a grep would have counted the method names written in this very
docstring, and the first grep that measured this file's numbers did exactly that: it read the three
`", ".join(...)` in the seeder as `SnakeQuery.join` and reported an API method as covered that
nothing calls.

It matches on the NAME, because the receiver's TYPE is what nothing short of a type checker could
give us here. Two narrowings keep that from lying, and both are needed:

- a call on a string literal is dropped, which is what `", ".join(...)` is;
- a SESSION method only counts when the receiver is NAMED like a session. Without it
  `Warehouse.stock.count()` — a relation aggregate, a different class entirely — reads as
  `SnakeSession.count`, and the tally claims pagination is covered while no page paginates.

A QUERY method needs no such narrowing: a query is built by chaining, so its receiver is usually
another call and has no name to match on. The names it does collide with are not names anything else
in these four trees calls.

AND THERE ARE THREE TALLIES, NOT TWO, SINCE THE FASTAPI DEMO WENT ASYNCHRONOUS. `AsyncSession` is a
different class with its own twenty-odd methods, and it deserves its own count for the same reason
`SnakeSession` does: nothing outside `src/test` used to call it. Sharing one tally between them would
have been worse than useless in BOTH directions — an `await session.exists(...)` written in
`shared/aio/` would have marked `SnakeSession.exists` as covered while no synchronous demo called it,
and the day a synchronous page dropped an operation the tally would have stayed full because the
asynchronous twin still had it.

Which class a call belongs to is decided by SYNTAX and not by a list of directories: a call is an
`AsyncSession` call when it is `await`ed, when it is the subject of an `async with` (that is
`savepoint`), or when it is iterated by an `async for` (that is `iterate`). Every other call on
something named like a session is synchronous. A directory list would have been the same mistake as
naming the packages one by one — it works until somebody puts a session somewhere the list does not
mention, and then it is quietly wrong.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from collections.abc import Callable
from typing import NamedTuple

import pytest
from snakeorm import AsyncSession, SnakeQuery, SnakeSession

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The four roots, whole. Naming the packages one by one is what once left `src/examples/` outside a
# check for a whole migration, with the count coming out full over a universe that had been trimmed.
_ROOTS = ("shared", "django", "flask", "fastapi")

# What is not an application: the suites themselves, and the caches and vendored trees under them.
_SKIPPED_DIRECTORIES = (
    "__pycache__",
    "node_modules",
    "tests",
    "migrations",
    ".mypy_cache",
)
_SKIPPED_FILES = ("verify.py",)

# `SnakeQuery` emits SQL as well as building it, and the emission is the SESSION's caller, not the
# user's: `to_sql` and friends are how a session turns a query into a statement, and
# `include_segments`/`prefetches`/`to_many_includes`/`to_one_includes` are how it asks a query what
# it is carrying. Counting them would say the demos ignore two thirds of an API they are not meant
# to call. Anything NEW on the class counts as user-facing until this list says otherwise, which is
# the right default: a method that appears and is never used should show up here as a gap.
_QUERY_IS_NOT_USER_FACING = frozenset(
    {
        "include_segments",
        "prefetches",
        "to_many_includes",
        "to_one_includes",
    }
)

# What a session is called where it is used. Every one of these four trees receives it as a
# parameter or reads it off the request, and both spellings end in the same word — `g.session` in
# Flask, `request.snake_session` in Django, a plain `session` everywhere in `shared/`. The match is
# on the LAST identifier, so the attribute forms are covered without listing them.
_SESSION_RECEIVERS = frozenset({"session", "snake_session", "db", "db_session"})


def _public_methods(cls: type) -> frozenset[str]:
    """The public callables of a class, which is the API a user of it can reach."""
    return frozenset(
        name
        for name, value in inspect.getmembers(cls)
        if not name.startswith("_") and callable(value)
    )


_SESSION_API = _public_methods(SnakeSession)
_ASYNC_SESSION_API = _public_methods(AsyncSession)
_QUERY_API = frozenset(
    name
    for name in _public_methods(SnakeQuery)
    if not name.startswith("to_") and name not in _QUERY_IS_NOT_USER_FACING
)


# THE DEBT, AND IT IS EMPTY — every method of `SnakeSession` that is not declared out of scope has an
# operation with a reason to want it. The dictionary stays because emptiness is the STATEMENT: a
# surface with nothing owed reports one case named `BLOCK-E-DONE`, which asserts the finish line
# itself, and the day a new method lands on the class it appears here as a gap without anybody
# remembering to add it. Deleting the dictionary would delete the assertion along with the debt.
#
# The last entry to come off was `refresh`, and it came off the way the rule demands: `engagement`
# already had a TRIGGER keeping `Post.visit_count`, and recording a visit now answers with the number
# the ENGINE wrote — read back onto the very object that was held before the write. A `refresh` of a
# row nobody else had touched would have proved nothing at all.
_SESSION_NOT_YET: dict[str, str] = {}

# THE DECISIONS, and all three of them are one argument seen from three places: THE SQL A DEMO
# CANNOT WRITE. It is worth reading in full, because two of the three spent a long time on the debt
# list wearing a reason that sounded like laziness and was doctrine.
#
# `raw` is the entry to read twice, because the honest reading of it is the opposite of the obvious
# one. «the builder covers every query the demos ask for, which is the intended state» was already
# written here, as the reason it was still pending — and it was never the excuse of a gap. It is THE
# BEST RESULT AVAILABLE to an ORM whose rule is that no raw SQL goes where a builder reaches. A page
# calling `raw()` in order to strike the line off would take the thing the project counts as a
# failure and file it as an achievement.
#
# `call` AND `execute_procedure` LOOKED LIKE DEBTS AND WERE NOT, and the chain that proves it runs
# through the sibling tally rather than through this file, which is exactly why it went unseen:
#
#     a routine's body is RAW ENGINE SQL that the caller writes
#       -> a shared model declaring one stops being portable   (`snake_function`, declared out there)
#         -> so no demo can declare a FUNCTION or a PROCEDURE  (these two)
#           -> so there is nothing to call, and nothing to hold the rows  (`snake_row`, out there too)
#
# The PROCEDURE half is shorter still, and it was worth measuring rather than assuming: the ORM has
# no procedure declarator and no CreateProcedure operation. `execute_procedure` can only `CALL` a
# routine that something else created, so the portability argument never even gets its turn.
#
# Every model in `shared/` runs on the three engines, and underneath the portability argument the
# engines do not even agree: SQLite cannot store routines at all — its functions are registered by
# the process that opens the connection, so they never live in the database — while MariaDB accepts
# `CREATE OR REPLACE FUNCTION` and MySQL 8.4 answers ERROR 1064 to it, and one dialect serves both.
#
# So the old reasons — «no demo declares a database FUNCTION returning rows to call», «no demo
# declares a stored PROCEDURE» — were true sentences pointing at the wrong thing. No demo declares
# one because NO DEMO CAN, not without breaking the rule this whole layer exists to demonstrate: a
# model written once runs on all three. A debt that can only be paid by breaking the doctrine was
# never a debt; it was a decision filed in the wrong dictionary, and it sat there long enough to be
# written into a plan as work somebody should go and do.
#
# None of the three closes by being covered: they close by being DECLARED, which is what this
# dictionary is. And the guard below keeps the declaration from rotting — the day a demo genuinely
# needs one of them, this net goes red and somebody has to write down what changed, instead of the
# call landing as a quiet tick on a tally that was already claiming success.
_SESSION_OUT_OF_SCOPE: dict[str, str] = {
    "call": (
        "no demo declares a database FUNCTION returning rows, and none CAN: a routine's body is raw "
        "engine SQL, so a shared model that declares one stops being portable — and every model "
        "here runs on the three engines. Underneath that, SQLite cannot store routines at all and "
        "MySQL and MariaDB disagree about CREATE OR REPLACE. Closing this would mean breaking the "
        "rule the whole layer demonstrates, so it is a decision and not a debt"
    ),
    "execute_procedure": (
        "the same argument as `call` and then some: a PROCEDURE's body is engine SQL too, and the "
        "ORM offers no way to declare one AT ALL — there is no `snake_procedure` and no "
        "CreateProcedure operation, only `CALL` on a routine somebody else made. A demo would have "
        "to ship a hand-written CREATE PROCEDURE through RunSQL, which the migration tally declares "
        "out of scope on its own account. It read as pending only while the reason said 'no demo "
        "declares one' instead of 'no demo can'"
    ),
    "raw": (
        "the builder covers every query the demos ask for, which is the INTENDED state and not a "
        "gap. An ORM whose rule is 'no raw SQL where a builder reaches' has no better result to "
        "report than a demo layer that never needed one, so calling it to tick this line would be "
        "celebrating a failure"
    ),
}

# `exists`, `delete_where` and `get_or_create` came off the list together, and by the same route the
# concurrency three took: an operation grew a reason to want them. `taxonomy` writes to the one N—N
# with an explicit bridge, and a bridge row is identified by its PAIR rather than by a key — so
# untagging asks `exists` (a yes or a no, not a row fetched in order to be discarded) and deletes
# with `delete_where` on both columns, while tagging is `get_or_create` because a screen with
# checkboxes can be submitted twice and two rows for one fact is not a thing the domain can mean.
# The blind `add` they replace is what made the second click a duplicate.

# The same tally for the ASYNCHRONOUS session, which the FastAPI demo drives and nothing else does.
# It spent longer behind its synchronous sibling and that was honest rather than embarrassing: one
# demo of three is asynchronous, so an operation reached this column only when THAT demo served it.
# Both of its last two entries closed that way. `iterate` waited for the FastAPI demo to grow a CSV
# route, which its own reason had said it would; `refresh` came off with its synchronous twin,
# because the operation that wants it is served on both surfaces.
#
# `iterate` is the one worth reading twice, because half of it was not a demo gap at all: the call
# had been in `shared/aio/` for three exports and this file's own reader could not see it. What it
# took was a fourth syntactic form — see `_awaited` — and the lesson is the one this repository keeps
# paying for elsewhere: a tally that cannot see what it claims to measure reports a debt that has
# already been paid, and reads exactly like one that has not.
_ASYNC_SESSION_NOT_YET: dict[str, str] = {}

# The same three decisions, on the other side of the colour line — and they are written out in full
# rather than pointed at, because these dictionaries are read one at a time by whoever is closing a
# gap. The three are out of scope for BOTH sessions for one reason each, but they are six
# declarations, exactly as a debt is two debts: an operation reaches the asynchronous column only
# when the demo that IS asynchronous serves it.
#
# AND THE ARGUMENT LANDS HARDER HERE, which is the part worth noticing. A debt on this side is
# narrower than its synchronous twin — one demo of three is asynchronous, so it waits on FastAPI
# specifically. A DECISION is not narrower at all: portability is a property of the model, and a
# model has no colour. `call` and `execute_procedure` are shut here for a reason that has nothing to
# do with which demo drives which session, and reading the two columns side by side is what makes
# the difference visible.
_ASYNC_SESSION_OUT_OF_SCOPE: dict[str, str] = {
    "call": (
        "no demo declares a database FUNCTION returning rows, and none CAN: a routine's body is raw "
        "engine SQL, so a shared model that declares one stops being portable — and every model "
        "here runs on the three engines. Underneath that, SQLite cannot store routines at all and "
        "MySQL and MariaDB disagree about CREATE OR REPLACE. Closing this would mean breaking the "
        "rule the whole layer demonstrates, so it is a decision and not a debt"
    ),
    "execute_procedure": (
        "the same argument as `call` and then some: a PROCEDURE's body is engine SQL too, and the "
        "ORM offers no way to declare one AT ALL — there is no `snake_procedure` and no "
        "CreateProcedure operation, only `CALL` on a routine somebody else made. A demo would have "
        "to ship a hand-written CREATE PROCEDURE through RunSQL, which the migration tally declares "
        "out of scope on its own account. It read as pending only while the reason said 'no demo "
        "declares one' instead of 'no demo can'"
    ),
    "raw": (
        "the builder covers every query the demos ask for, which is the INTENDED state and not a "
        "gap. An ORM whose rule is 'no raw SQL where a builder reaches' has no better result to "
        "report than a demo layer that never needed one, so calling it to tick this line would be "
        "celebrating a failure"
    ),
}


# EMPTY, and the emptiness is the whole surface reached rather than a list somebody forgot to fill.
# `union_all` was the last entry and the movement book took it off: `shared/selectors/
# inventory_selectors.py::book_compound` joins the two origins that write a warehouse's movements,
# and `test_movement_book.py` proves against a real engine that `union` would print one line where
# there are two events. The reason it held out is written up in this file's docstring, because the
# half of it that was RIGHT is worth keeping: over a keyed table the two operators cannot differ.
_QUERY_NOT_YET: dict[str, str] = {}

# Nothing on `SnakeQuery` is out of scope, and the empty dictionary is the statement rather than an
# oversight: every method of this surface had a question a real application would ask, so the whole
# of it was in play and the target for this net was the whole of it. The two other nets each carry a
# declaration; this one carrying none is a measurement, not a gap in the bookkeeping. With
# `_QUERY_NOT_YET` empty as well, the tally is now BOTH dictionaries empty — which is the one state
# where this net asserts the finish line itself, under the id `BLOCK-E-DONE`.
_QUERY_OUT_OF_SCOPE: dict[str, str] = {}

# `intersect` and `except_` came off the list with the tag filter, and they are the pair worth
# reading twice: neither is a `WHERE` that somebody preferred to write as a compound. Requiring two
# tags of an N—N is a condition on two DIFFERENT bridge rows, so `tag_id = A AND tag_id = B` matches
# nothing — the shapes that work are a self-join per extra tag or one branch per extra tag, and this
# is the second. `except_` is its exclude half. Folding either in Python would return the same rows
# and drag every post of every tag over the wire to discard most of them.


def _sources() -> list[pathlib.Path]:
    """Every application source file of the four roots: the domain and the three demos, no suites."""
    found: list[pathlib.Path] = []
    for root in _ROOTS:
        for path in sorted((_ROOT / root).rglob("*.py")):
            parts = set(path.relative_to(_ROOT).parts)
            if parts & set(_SKIPPED_DIRECTORIES):
                continue
            if path.name in _SKIPPED_FILES or path.name.startswith("test_"):
                continue
            found.append(path)
    return found


def _receiver_name(node: ast.expr) -> str | None:
    """The LAST identifier of what a method was called on: `g.session` and `session` both give one."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None  # a call, a subscript: a chained query has no name to match on


def _awaited(tree: ast.AST) -> set[int]:
    """The calls in one file that are asynchronous, by identity. FOUR forms, and the fourth is new.

    Three of them are about how a call is USED, and they are what tells an `AsyncSession` call from a
    `SnakeSession` one where nothing else can: both classes name their methods the same on purpose,
    so the receiver says nothing and the annotation is not always there to read. `savepoint` is only
    ever an `async with` and `iterate` only ever an `async for` — neither is awaited — so leaving
    those two out would have counted the two most interesting methods on the wrong side.

    THE FOURTH IS A CALL THE COROUTINE HANDS BACK, and it was missing for as long as nothing in the
    demos handed one back. `AsyncSession.iterate()` is deliberately not a coroutine — it returns the
    iterator so its guard against an unstreamable query fires on the CALL rather than on the first
    row — so a use case that wraps it writes `return session.iterate(...)` and awaits nothing. Under
    the three-form reading that call was indistinguishable from a synchronous one, and the
    asynchronous tally reported `iterate` as owed while the demo that drives it called it three
    times over.

    It is worth being exact about why this is the fourth form and not a fourth GUESS. The obvious
    generalisation — "any session call inside an `async def`" — is wrong here and would be wrong
    quietly: `fastapi/apps/lab/urls.py` takes a SYNCHRONOUS session into `async def` endpoints on
    purpose, and that decision is written down in `fastapi/apps/deps.py`. Reading the enclosing
    function's colour would credit every one of those to `AsyncSession` and the tally would start
    lying in the direction that flatters it. A `return` is narrower and it is the value of the
    coroutine itself: measured over the four roots, it matches exactly three call sites, all three
    of them `iterate`, all three in `shared/aio/`.
    """
    marked: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            marked.add(id(node.value))
        elif isinstance(node, ast.AsyncWith):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    marked.add(id(item.context_expr))
        elif isinstance(node, ast.AsyncFor) and isinstance(node.iter, ast.Call):
            marked.add(id(node.iter))
        elif isinstance(node, ast.AsyncFunctionDef):
            marked |= _returned_calls(node)
    return marked


def _returned_calls(function: ast.AsyncFunctionDef) -> set[int]:
    """The calls RETURNED by one coroutine, by identity — its own body only, not a nested one.

    The walk stops at a nested function on purpose: a synchronous `def` written inside a coroutine
    returns a value to whoever calls IT, not to the event loop, and counting its returns would be
    the enclosing-colour mistake by another road.
    """
    marked: set[int] = set()
    stack: list[ast.AST] = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
            marked.add(id(node.value))
        stack.extend(ast.iter_child_nodes(node))
    return marked


def _calls(path: pathlib.Path) -> list[tuple[str, str | None, bool]]:
    """Every `receiver.name(...)` in one file, as `(name, receiver, is asynchronous)`.

    A call on a string literal is dropped: `", ".join(...)` is not `SnakeQuery.join`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    asynchronous = _awaited(tree)
    found: list[tuple[str, str | None, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute):
            continue
        if isinstance(function.value, ast.Constant):
            continue
        found.append(
            (function.attr, _receiver_name(function.value), id(node) in asynchronous)
        )
    return found


def _exercised_session() -> set[str]:
    """SYNCHRONOUS session methods the demos call: named like a session, and not awaited."""
    return {
        name
        for path in _sources()
        for name, receiver, asynchronous in _calls(path)
        if receiver in _SESSION_RECEIVERS and not asynchronous
    }


def _exercised_async_session() -> set[str]:
    """ASYNCHRONOUS session methods the demos call: named like a session, and awaited."""
    return {
        name
        for path in _sources()
        for name, receiver, asynchronous in _calls(path)
        if receiver in _SESSION_RECEIVERS and asynchronous
    }


def _exercised_query() -> set[str]:
    """Query methods the demos call. A chained query has no receiver name, so none is required.

    Colour does not apply here and asking for it would be a category error: building a query runs
    nothing, which is exactly why the two demos share their fragments.
    """
    return {name for path in _sources() for name, _, _ in _calls(path)}


class _Net(NamedTuple):
    """One tally: a surface, what it owes, what it has declared out, and how it is measured.

    The three used to be spelled out three times over, once per test, and the three copies had to
    agree by hand. They are one table now for the same reason the surfaces are read off the classes
    instead of listed: a thing written twice is a thing that can disagree with itself.
    """

    name: str
    api: frozenset[str]
    not_yet: dict[str, str]
    out_of_scope: dict[str, str]
    exercised: Callable[[], set[str]]

    def in_scope(self) -> frozenset[str]:
        """The surface the demos are meant to reach: everything not declared out."""
        return self.api - set(self.out_of_scope)


_NETS: tuple[_Net, ...] = (
    _Net(
        "SnakeSession",
        _SESSION_API,
        _SESSION_NOT_YET,
        _SESSION_OUT_OF_SCOPE,
        _exercised_session,
    ),
    _Net(
        "AsyncSession",
        _ASYNC_SESSION_API,
        _ASYNC_SESSION_NOT_YET,
        _ASYNC_SESSION_OUT_OF_SCOPE,
        _exercised_async_session,
    ),
    _Net(
        "SnakeQuery", _QUERY_API, _QUERY_NOT_YET, _QUERY_OUT_OF_SCOPE, _exercised_query
    ),
)

_EVERY_NET = pytest.mark.parametrize("net", _NETS, ids=[net.name for net in _NETS])

# The id a net wears once it owes nothing. Both of the sister files use the same word, so one
# selector reads all five tallies at once — see `test_block_e_gap_is_still_open` below.
_DONE = "BLOCK-E-DONE"

_GAPS = [
    pytest.param(net, name, id=f"{net.name}-{name}")
    for net in _NETS
    for name in (sorted(net.not_yet) or [_DONE])
]


def test_there_are_sources_to_look_at() -> None:
    """That the scan found files and recognises a call it must recognise.

    It is the trap of every check that discovers its own input: if the roots stop matching, "nothing
    is missing" holds over an empty set and the guard turns into decoration. `filter` is the sanity
    probe because a demo with no `filter` in it would not be a demo.
    """
    sources = _sources()

    assert len(sources) >= 50, f"only {len(sources)} source files found under {_ROOTS}"
    assert "filter" in _exercised_query()
    assert "all" in _exercised_session(), (
        f"no call was found on a receiver named one of {sorted(_SESSION_RECEIVERS)}, so every "
        f"session method would read as a gap. The demos renamed the session variable."
    )
    assert "all" in _exercised_async_session(), (
        f"no AWAITED call was found on a receiver named one of {sorted(_SESSION_RECEIVERS)}, so "
        f"every asynchronous session method would read as a gap while the FastAPI demo drives one."
    )


@_EVERY_NET
def test_the_two_lists_name_methods_that_exist_and_do_not_overlap(net: _Net) -> None:
    """Both lists are spelled against the real API, so a rename cannot leave a ghost on either.

    A method renamed in the ORM would otherwise sit here forever as a gap nobody can ever close,
    and the tally would be measuring a method that no longer exists.

    The overlap is checked in the same breath because it is the failure the split introduces and
    nothing else would catch: an entry in both dictionaries is a method that is simultaneously owed
    and declared out, and whichever of the two a reader happens to open is the answer they get.
    """
    ghosts = sorted((set(net.not_yet) | set(net.out_of_scope)) - net.api)
    both = sorted(set(net.not_yet) & set(net.out_of_scope))

    assert ghosts == [], (
        f"these are listed on {net.name} but not in the API any more: {ghosts}"
    )
    assert both == [], (
        f"these are on BOTH lists for {net.name}: {both}. A method is either owed or declared out "
        f"of scope; being on both means the two reasons disagree and nobody has noticed."
    )


@_EVERY_NET
def test_nothing_that_was_exercised_stops_being_exercised(net: _Net) -> None:
    """A method the demos used and no longer use is a demo that got thinner without saying so.

    This is the direction that protects what has already been won. The other tests protect the
    direction the work goes in, and the direction a decision goes stale in.
    """
    lost = sorted((net.in_scope() - set(net.not_yet)) - net.exercised())

    assert lost == [], (
        f"these were exercised by the demos and are not any more: {lost}. Either a page lost the "
        f"operation that called them, or the call moved into a test — which does not count, and on "
        f"purpose: a call written so the method has a caller proves nothing."
    )


@_EVERY_NET
def test_the_out_of_scope_decision_still_holds(net: _Net) -> None:
    """The third direction: something declared out of scope may not quietly start being used.

    This is the guard the split makes necessary, and it is the whole reason `_OUT_OF_SCOPE` is a
    dictionary rather than a comment. A decision is a claim about the demos — «no page here needs
    raw SQL» — and a claim can stop being true without anybody revisiting the sentence that made
    it. Left unguarded, the reason ages into a lie that reads exactly like a reason, and it reads
    that way to the next person as well.

    Closing this is not striking the line off. It is moving the entry back to `_NOT_YET`, or
    deciding the decision was wrong and writing THAT down — either way, a sentence changes.
    """
    used = sorted(set(net.out_of_scope) & net.exercised())

    assert used == [], (
        f"these are declared OUT OF SCOPE on {net.name} and something in the demos now calls "
        f"them: {used}. The decision changed and the reason next to it did not: "
        + "; ".join(f"{name} — {net.out_of_scope[name]}" for name in used)
    )


@pytest.mark.parametrize(("net", "name"), _GAPS)
def test_block_e_gap_is_still_open(net: _Net, name: str) -> None:
    """One test per gap still owed: covering it fails here until it is struck off the list.

    A number written in a comment ages the moment somebody does the work and forgets the comment.
    Written as an assertion it cannot: the work itself is what turns the suite red, and the fix is
    to delete the line that says the gap is still there.

    IT IS ONE TEST PER ENTRY, and that is what makes the tally answer a question rather than only
    guard one. Collecting `-k block_e` across the three coverage files lists what is left, by name,
    over all five tallies at once — so «how much is left before the demos exercise the whole ORM»
    is something you RUN, not something you read off a document that somebody has to remember to
    update. A tally kept in prose is how the previous one came to say "26 of 34" over a list of
    nine.

    A tally that owes nothing contributes one case named `BLOCK-E-DONE` instead of none, and that
    case asserts the finish line itself: every method in scope, exercised. It is there because an
    empty parametrisation collects nothing, and a selector that finds nothing looks the same
    whether the work is finished or the name was mistyped.
    """
    exercised = net.exercised()

    if name == _DONE:
        missing = sorted(net.in_scope() - exercised)
        assert missing == [], (
            f"{net.name} owes nothing on its list and yet these are not exercised: {missing}. "
            f"Either put them back on `_NOT_YET` with a reason, or declare them out of scope."
        )
        return

    assert name not in exercised, (
        f"`{name}` is listed as not yet exercised on {net.name} and something now calls it. Strike "
        f"it off `_NOT_YET` in this file — the list IS the tally, and without it {net.name} stands "
        f"at {len(net.in_scope() - set(net.not_yet))} of {len(net.in_scope())} in scope "
        f"({len(net.api)} in total, {len(net.out_of_scope)} declared out)."
    )
