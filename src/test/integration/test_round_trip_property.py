"""Round-trip by PROPERTY: any value of any type, written and read back, on both engines.

`test_type_round_trip.py` tests ONE value per type, picked by hand. This one declares the property
—for ANY value of the type, what was written comes back identical— and lets Hypothesis generate
hundreds: integers at the 64-bit edges, floats with odd exponents, long-precision `Decimal`,
`datetime` with microseconds, strings with everything a human never puts in a list, nested dicts.

It is the counterpart to "every permutation": the space is not enumerated (it is infinite), the
invariant is declared and then explored. When something breaks it, Hypothesis shrinks it down to the
smallest value that fails.

Each example writes a row, reads it and calls `rollback` to leave the database clean for the next
one —which on top of that exercises that the rollback WORKS, which until today was not true on
SQLite—.

The strategies are BOUNDED to the contract, not crippled so they pass: a NaN `float` does not
round-trip through SQL (`NaN != NaN`), a NUL byte does not fit in a TEXT on any engine, a naive
`datetime` loses its zone on purpose. Every exclusion carries its reason; excluding without a reason
would be hiding a bug.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from test.conftest import NO_SERVER_REASON
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from snakeorm import (
    SnakeColumn,
    SnakeDialect,
    SnakeDriver,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.core.config import dsn_from_env
from snakeorm.migration import emit_create_table


@snake_model(table="rtp_valores")
class Values(SnakeModel):
    """One nullable column per type, so as to write ONE and leave the rest as NULL."""

    id: SnakeColumn[int] = snake_auto()
    entero: SnakeColumn[int | None] = snake_int()
    text: SnakeColumn[str | None] = snake_str()
    booleano: SnakeColumn[bool | None] = snake_column()
    real: SnakeColumn[float | None] = snake_column()
    exacto: SnakeColumn[Decimal | None] = snake_column()
    momento: SnakeColumn[SnakeUtc | None] = snake_datetimetz()
    identificador: SnakeColumn[UUID | None] = snake_column()
    crudo: SnakeColumn[bytes | None] = snake_column()
    documento: SnakeColumn[dict | None] = snake_column()


snake_link()

# --- Strategies BOUNDED to the contract, with the reason for every limit ------------------------

# SQLite stores signed 64-bit integers; Postgres BIGINT does the same. Outside that range it is the
# engine that does not support it, not the ORM.
_INTEGERS = st.integers(min_value=-(2**63), max_value=2**63 - 1)

# No NUL: neither SQLite nor Postgres admit `\x00` inside a TEXT (Postgres rejects it out loud,
# SQLite truncates). It is a limit of the engines, documented, not a weakness of the ORM.
# `codec="utf-8"` discards surrogates at the root —they do not encode to UTF-8, the very thing
# `pyliteral` looks after—.
_TEXTS = st.text(alphabet=st.characters(codec="utf-8", exclude_characters="\x00"))

# NaN and Inf are out: `NaN != NaN` breaks any comparison, and a round-trip that compares with `==`
# cannot state anything about them. It is a property of IEEE-754, not of the ORM.
_FLOATS = st.floats(allow_nan=False, allow_infinity=False)

# Bounded Decimal: no NaN/Inf, and at a scale that fits. A Decimal of a thousand digits is a limit
# of the storage, not of the round-trip.
_DECIMALS = st.decimals(
    allow_nan=False,
    allow_infinity=False,
    places=4,
    min_value=-(10**15),
    max_value=10**15,
)

# AWARE datetime in UTC: the naive one loses its zone on purpose (see the TIMESTAMPTZ decision), so
# it is not comparable back. Microseconds included, which is where a naive formatting breaks.
_INSTANTS = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(UTC),
)

# JSON: nested dicts of JSON-serializable values. The key is ALWAYS str (JSON has no other kind).
# WITHOUT floats on purpose: JSON does not tell `100.0` from `100`, and Postgres (JSONB) normalizes
# the numbers while SQLite (TEXT) preserves them as they are, so a big float comes back as an int on
# one engine and as a float on the other. It is not a failure of the ORM: it is the nature of JSON,
# identical in any tool, and it is in `docs/users/reference/limits.md`. JSON integers are bounded to
# 2^53, the largest one a JSON `double` represents exactly.
_JSON_INTEGER = st.integers(min_value=-(2**53), max_value=2**53)
# The text INSIDE the JSON —keys and values— also without NUL: Postgres rejects `NUL` in a JSONB
# just as in a TEXT, so it is the same limit of the engine, not of the ORM.
_JSON_SCALAR = st.none() | st.booleans() | _JSON_INTEGER | _TEXTS
_DOCUMENTS = st.dictionaries(
    keys=_TEXTS,
    values=st.recursive(
        _JSON_SCALAR,
        lambda children: st.lists(children) | st.dictionaries(_TEXTS, children),
        max_leaves=8,
    ),
    max_size=5,
)

_FIELDS = {
    "entero": _INTEGERS,
    "text": _TEXTS,
    "booleano": st.booleans(),
    "real": _FLOATS,
    "exacto": _DECIMALS,
    "momento": _INSTANTS,
    "identificador": st.uuids(),
    "crudo": st.binary(),
    "documento": _DOCUMENTS,
}


def _connect(engine: str) -> tuple[SnakeDriver, SnakeDialect]:
    """Driver and dialect of the engine; Postgres is skipped when there is no server."""
    from snakeorm import (
        PostgresDialect,
        PsycopgDriver,
        SQLiteDialect,
        SQLiteDriver,
    )

    if engine == "sqlite":
        return SQLiteDriver.connect(":memory:"), SQLiteDialect()
    import psycopg2

    try:
        return PsycopgDriver.connect(dsn_from_env()), PostgresDialect()
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")


@pytest.fixture(scope="module", params=["postgres", "sqlite"])
def session(request: pytest.FixtureRequest) -> Iterator[SnakeSession]:
    """ONE session per engine, with the table created. Each example writes, reads and rolls back."""
    driver, dialect = _connect(request.param)
    table = snake_table(Values)
    driver.execute(f'DROP TABLE IF EXISTS "{table.name}"', ())
    driver.commit()
    driver.execute(emit_create_table(table, dialect), ())
    driver.commit()
    try:
        yield SnakeSession(driver, dialect)
    finally:
        driver.close()


@pytest.mark.parametrize("field", sorted(_FIELDS), ids=str)
@given(data=st.data())
@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_any_value_of_the_type_round_trips(
    field: str, session: SnakeSession, data: st.DataObject
) -> None:
    """A generated value of the field's type is written and returns EQUAL. Rollback leaves it clean.

    The value is requested with `data.draw` INSIDE the test so that it depends on the parametrized
    `field`: each column pulls from its own strategy. The final `rollback` reverts the row, so the
    hundreds of examples neither dirty the table nor collide with each other.
    """
    value = data.draw(_FIELDS[field], label=field)

    # Every column at NULL except the one for this field: a nullable column without a default is
    # still a required argument of the constructor (nullable is not "has a default").
    kwargs: dict[str, object] = dict.fromkeys(_FIELDS)
    kwargs[field] = value
    row = Values(**kwargs)  # type: ignore[arg-type]
    try:
        session.add(row)
        loaded = session.first(SnakeQuery(Values).filter(Values.id == row.id))
    finally:
        # It ALWAYS rolls back, even if the `add` fails: on Postgres a failed statement leaves the
        # transaction poisoned, and without this rollback the next Hypothesis example would die with
        # `InFailedSqlTransaction` instead of with its own counterexample.
        session.rollback()

    assert loaded is not None
    returned = getattr(loaded, field)
    assert returned == value, f"{field}: wrote {value!r}, got back {returned!r}"
