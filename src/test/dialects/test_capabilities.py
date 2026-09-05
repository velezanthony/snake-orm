"""Tests for the capability CATALOG: the base list of what any engine can do.

Before, each capability was a loose attribute on the Protocol (`supports_upsert`, `supports_ilike`...).
It worked for asking about one, and it failed at two different things:

1. **They could not be WALKED.** Warning the user, at startup, about everything their engine does not
   give them requires iterating the capabilities, and twenty flat attributes do not iterate.
2. **A `bool` cannot say "halfway".** SQLite stores a `Decimal` and returns it exact, but it orders it
   as TEXT: `'9.99' > '10.00'`. That is not "unsupported" —the model works— nor is it full support.
   With two states you have to lie in one of the two directions.

Hence the three pieces: `Cap` is the BASE catalog, `Support` is tri-state (`Full`, `Degraded`,
`Nope`), and `SnakeCapabilities` forces every engine to answer the WHOLE catalog.

What that last point buys is what a `frozenset` of supported capabilities cannot give: if an engine
forgets to declare one, the set simply does not contain it and it reads as "unsupported" IN SILENCE.
A silent default, in the ORM that shouts. Here it blows up at import time and says which one.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SQLiteDialect,
    SnakeColumn,
    SnakeModel,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.dialects.base import SnakeDialect
from snakeorm.dialects.matrix import Engine, capabilities_for, flavour_of
from snakeorm.sql.condition import emit_condition
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects.capabilities import (
    Cap,
    Degraded,
    Full,
    Nope,
    Since,
    SnakeCapabilities,
)

_DIALECTS = [PostgresDialect(), MySQLDialect(), SQLiteDialect()]


@snake_model(table="cap_widgets")
class _Widget(SnakeModel):
    """A column to write a case-insensitive match against."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=40)


def test_forgetting_a_capability_dies_at_declaration_and_says_which() -> None:
    """Verifies that an incomplete catalog blows up, naming what is missing.

    It is the class's whole reason to exist. Without this guard, the absent capability would read as
    "unsupported" and the engine would inherit a `False` nobody wrote or reviewed.
    """
    incomplete = {cap: Full() for cap in Cap}
    del incomplete[Cap.UPSERT]

    with pytest.raises(SnakeDialectError) as error:
        SnakeCapabilities(incomplete)

    assert "UPSERT" in str(error.value)


def test_a_capability_that_is_not_full_must_say_why() -> None:
    """Verifies that degrading or denying a capability requires a reason.

    The reason is NOT documentation: it is the text the user reads at startup. Without it, the warning
    would say "your engine does not support X" and leave the dev exactly as lost as with no warning.
    """
    with pytest.raises(
        SnakeDialectError,
        match="Without it, the warning says that something cannot be done",
    ):
        Degraded("")
    with pytest.raises(
        SnakeDialectError,
        match="Without it, the warning says that something cannot be done",
    ):
        Nope("   ")


def test_degraded_means_it_works_badly_not_that_it_is_missing() -> None:
    """Verifies that `Degraded` CAN: that is the difference with `Nope`.

    Mixing them up breaks the plan in both directions. Treating `Degraded` as absent would forbid a
    `Decimal` on SQLite, which works. Treating `Nope` as present would emit SQL the engine rejects.
    """
    degraded = SnakeCapabilities(
        {cap: Full() for cap in Cap}
        | {Cap.DECIMAL_ORDERING: Degraded("it sorts as text")}
    )
    absent = SnakeCapabilities(
        {cap: Full() for cap in Cap} | {Cap.UPSERT: Nope("no ON CONFLICT")}
    )

    assert degraded.can(Cap.DECIMAL_ORDERING) is True
    assert absent.can(Cap.UPSERT) is False


def test_caveats_lists_only_what_is_not_full_with_its_reason() -> None:
    """Verifies that `caveats()` gives exactly what has to be told to the user, and nothing else.

    It is what makes the startup warning possible: a walkable list of (capability, reason).
    """
    capabilities = SnakeCapabilities(
        {cap: Full() for cap in Cap}
        | {
            Cap.UPSERT: Nope("no ON CONFLICT"),
            Cap.DECIMAL_ORDERING: Degraded("it sorts as text"),
        }
    )

    caveats = dict(capabilities.caveats())

    assert caveats == {
        Cap.UPSERT: "no ON CONFLICT",
        Cap.DECIMAL_ORDERING: "it sorts as text",
    }


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
@pytest.mark.parametrize("cap", list(Cap), ids=lambda c: c.name)
def test_every_dialect_answers_the_whole_catalogue(dialect: object, cap: Cap) -> None:
    """Verifies that ALL THREE engines answer EVERY entry in the catalog.

    Tied to the three of them and to every capability at once on purpose: adding an entry to `Cap`
    turns the three engines red at once and forces a decision on each. It is the half that turns the
    catalog into a source of truth instead of a list of good intentions.
    """
    capabilities = dialect.capabilities  # type: ignore[attr-defined]

    assert isinstance(capabilities.support_for(cap), (Full, Degraded, Nope))


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
def test_postgres_is_the_only_one_with_nothing_to_warn_about(dialect: object) -> None:
    """Verifies that the catalog reflects reality: Postgres full, the other two with caveats.

    It is the check that nobody declared `Full()` down the line just to get by. If some day SQLite
    supports `ALTER COLUMN`, this test falls and has to be looked at — which is exactly what we want.
    """
    caveats = dialect.capabilities.caveats()  # type: ignore[attr-defined]

    if isinstance(dialect, PostgresDialect):
        assert caveats == ()
    else:
        assert caveats != ()


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
def test_a_nope_means_the_operation_cannot_happen(dialect: SnakeDialect) -> None:
    """`Nope` and `Degraded` are not two shades of the same thing, and `ILIKE` proved it.

    A `Nope` says the engine CANNOT: somebody reads it and the plan stops, or the SQL takes another
    shape because this one is impossible. A `Degraded` says it works and something about the
    SEMANTICS is weaker. The word chosen is what a reader acts on.

    `Cap.ILIKE` was `Nope` on MySQL and SQLite while a case-insensitive match ran perfectly on both:
    the emitter translates it to `LOWER(a) LIKE LOWER(b)`. Nothing was refused and no plan stopped —
    what is lost is that `LOWER` folds only what the collation folds. That is the definition of
    `Degraded`, and the reason text already said so in its own words ("falls back to"), which is the
    tell: a `Nope` whose justification explains the fallback is not a `Nope`.

    Asserted the only way that means anything — by RUNNING the emission first. The claim is not that
    somebody classified it well, it is that the query the classification talks about comes out.
    """
    emitted, _ = emit_condition(_Widget.name.icontains("x"), dialect)

    assert emitted, "the case-insensitive match emitted nothing"
    assert not isinstance(dialect.capabilities.resolved[Cap.ILIKE], Nope), (
        f"{type(dialect).__name__} declares ILIKE as `Nope` and yet answers `{emitted}`. "
        "A translated shape is `Degraded`; `Nope` is for what cannot happen."
    )


# --- Since: the capability that arrives with a version of the engine ----------------------------


def test_since_resolves_to_full_when_the_engine_reaches_the_version() -> None:
    """An engine at or above the version gets the capability, with nothing to warn about.

    `Since` is a DECLARATION, not a fourth state: it collapses to `Full` or `Degraded` when the
    capabilities are built, so everything downstream keeps seeing the same three answers.
    """
    caps = SnakeCapabilities(
        {cap: Full() for cap in Cap}
        | {
            Cap.CHECK_CONSTRAINT_DDL: Since(
                (3, 53, 0), "ADD CONSTRAINT", below=Nope("rebuild the table")
            )
        },
        engine_version=(3, 53, 2),
    )
    assert caps.support_for(Cap.CHECK_CONSTRAINT_DDL) == Full()
    assert caps.can(Cap.CHECK_CONSTRAINT_DDL)


def test_since_below_the_version_takes_the_declared_state_and_names_both() -> None:
    """Below it, the answer is the one the capability declared, with BOTH version numbers in it.

    `below` is written out because only the capability knows what its absence means: a missing
    CHECK stops the operation (`Nope`), a missing native type only warns (`Degraded`). Collapsing
    to a fixed state would let the plan emit a statement the engine refuses.
    """
    caps = SnakeCapabilities(
        {cap: Full() for cap in Cap}
        | {
            Cap.CHECK_CONSTRAINT_DDL: Since(
                (3, 53, 0), "ADD CONSTRAINT", below=Nope("rebuild the table")
            )
        },
        engine_version=(3, 46, 1),
    )
    support = caps.support_for(Cap.CHECK_CONSTRAINT_DDL)
    assert isinstance(support, Nope), (
        "a missing CHECK stops the operation, it does not degrade"
    )
    assert "3.46.1" in support.reason, (
        "the reason does not name the version the user HAS"
    )
    assert "3.53.0" in support.reason, (
        "the reason does not name the version it would take"
    )
    assert "rebuild the table" in support.reason, (
        "the reason does not say what happens instead"
    )


def test_since_with_no_known_version_refuses_rather_than_promising() -> None:
    """An engine that cannot say its version does NOT get the benefit of the doubt.

    Promising a statement the engine may not accept turns a warning into a syntax error mid-migration.
    """
    caps = SnakeCapabilities(
        {cap: Full() for cap in Cap}
        | {
            Cap.CHECK_CONSTRAINT_DDL: Since(
                (3, 53, 0), "ADD CONSTRAINT", below=Nope("rebuild the table")
            )
        },
        engine_version=None,
    )
    assert isinstance(caps.support_for(Cap.CHECK_CONSTRAINT_DDL), Nope)


def test_the_check_and_the_foreign_key_are_two_capabilities() -> None:
    """SQLite 3.53 accepts `ADD CONSTRAINT ... CHECK` and still refuses UNIQUE, PK and FOREIGN KEY.

    Measured on 3.53.2: the CHECK runs and is enforced, while UNIQUE, PRIMARY KEY and FOREIGN KEY
    all still answer a syntax error. Only the CHECK left the group, so only the CHECK gets a
    capability of its own.
    """
    assert Cap.CHECK_CONSTRAINT_DDL is not Cap.ADD_CONSTRAINT


# --- MariaDB is not MySQL -----------------------------------------------------------------------


def test_mariadb_gets_what_it_has_and_mysql_does_not() -> None:
    """Measured on MariaDB 10.11/11.4/11.8 against MySQL 8.0/8.4/9.7: they differ, and the dialect
    that serves both used to answer MySQL for the two.

    `RETURNING` is the one that costs: on MariaDB `INSERT ... RETURNING id` answers the rows, and
    declaring it absent made the ORM pay a round trip it did not owe.
    """
    maria = capabilities_for(Engine.MARIADB)
    mysql = capabilities_for(Engine.MYSQL)

    assert isinstance(maria.support_for(Cap.RETURNING), Full)
    assert isinstance(mysql.support_for(Cap.RETURNING), Nope)
    assert isinstance(maria.support_for(Cap.UUID), Full)
    assert isinstance(mysql.support_for(Cap.UUID), Degraded)
    # And one that goes the other way, so this is not "MariaDB is better": MySQL takes a recursive
    # CTE as a branch of a compound and MariaDB answers 1064.
    assert isinstance(mysql.support_for(Cap.CTE_IN_COMPOUND_BRANCH), Full)
    assert isinstance(maria.support_for(Cap.CTE_IN_COMPOUND_BRANCH), Nope)


def test_an_unknown_flavour_promises_only_what_both_can_do() -> None:
    """With no connection there is no flavour, and the answer is the INTERSECTION of the two.

    Guessing either way would promise a statement half the servers refuse — a warning turning into a
    syntax error. The intersection is what the dialect answered before it could tell them apart, so
    a dialect built without a connection behaves exactly as it always did.
    """
    unknown = MySQLDialect().capabilities

    assert isinstance(unknown.support_for(Cap.RETURNING), Nope), (
        "MySQL cannot: do not promise it"
    )
    assert isinstance(unknown.support_for(Cap.CTE_IN_COMPOUND_BRANCH), Nope), (
        "MariaDB cannot: do not promise it either — the restriction wins in BOTH directions"
    )


@pytest.mark.parametrize(
    ("version_string", "expected"),
    [
        ("11.8.8-MariaDB-ubu2404", Engine.MARIADB),
        ("10.11.19-MariaDB-ubu2204", Engine.MARIADB),
        ("11.4.13-MariaDB-ubu2404", Engine.MARIADB),
        ("8.0.46", Engine.MYSQL),
        ("8.4.11", Engine.MYSQL),
        ("9.7.2", Engine.MYSQL),
    ],
)
def test_the_flavour_is_read_from_what_the_server_calls_itself(
    version_string: str, expected: Engine
) -> None:
    """The six strings are the ones the servers actually answered to `SELECT VERSION()`.

    MariaDB puts its name in there and MySQL does not, which is the whole detection — the same one
    Django makes (`mysql_is_mariadb`). Written down as data because a server string is the kind of
    thing that gets guessed at and then quietly stops matching.
    """
    assert flavour_of(version_string) is expected


def test_a_server_that_says_nothing_useful_keeps_the_strict_answer() -> None:
    """An unrecognisable version does NOT get the benefit of the doubt.

    Reading a flavour wrong is worse than not reading it. Guessing MySQL would not be the safe
    side either: MySQL is the restrictive one for `RETURNING` and the permissive one for
    `CTE_IN_COMPOUND_BRANCH`, so there is no flavour that is conservative in every direction. `None`
    is, because it falls back to what both can do.
    """
    assert flavour_of("") is None
    assert flavour_of("something-else-entirely") is None
