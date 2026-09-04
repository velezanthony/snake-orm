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
from snakeorm.sql.condition import emit_condition
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects.capabilities import (
    Cap,
    Degraded,
    Full,
    Nope,
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
    assert not isinstance(dialect.capabilities.declared[Cap.ILIKE], Nope), (
        f"{type(dialect).__name__} declares ILIKE as `Nope` and yet answers `{emitted}`. "
        "A translated shape is `Degraded`; `Nope` is for what cannot happen."
    )
