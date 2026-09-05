"""The composite `IN` against the three engines, with the ROWS read rather than the SQL asserted.

The point of this file is one comparison, and the fixture is built around it. A caller who wants the
pairs `(7, 3)` and `(9, 1)` and writes one `in_()` per column gets `carrier IN (7, 9) AND route IN
(3, 1)` — the CARTESIAN PRODUCT, which also answers `(7, 1)` and `(9, 3)`. With a fixture that holds
only the two wanted rows the two queries return the same thing and a test proves nothing, so the two
crossed pairs are SEEDED: they exist in the table, and only the wrong query brings them back.

Both queries are run side by side in the same test. Asserting that the composite `IN` returns two
rows says it is not obviously broken; asserting that the naive version returns FOUR is what says the
two are different questions, and it is the half that fails the day the builder quietly degrades into
a conjunction.

The fallback is checked here too. `SnakeTupleIn` has two branches — the row constructor, and the
OR-of-ANDs for a dialect that declares no `Cap.ROW_CONSTRUCTOR` — and all three engines declare
`Full()`, so nothing in this repository ever ran the second one against a real database. It is run
here, on a real engine, and required to answer the SAME rows.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SQLiteDialect,
    snake_int,
    snake_key,
    snake_keys,
    snake_model,
    snake_str,
)
from snakeorm.expressions.scalar import snake_upper
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="ci_cargo")
class CargoLeg(SnakeModel):
    """A three-column key, plus two columns outside it to filter on as well."""

    carrier_id: SnakeColumn[int] = snake_int(primary_key=True)
    route_id: SnakeColumn[int] = snake_int(primary_key=True)
    leg: SnakeColumn[int] = snake_int(primary_key=True)
    city: SnakeColumn[str] = snake_str(max_length=32)
    units: SnakeColumn[int] = snake_int()


# The two pairs anybody would ask for, and the two CROSSED ones that only a cartesian product
# returns. Without the crossed pair in the table, the right query and the wrong one agree.
_ROWS = [
    (7, 3, 1, "Vigo", 10),  # wanted
    (9, 1, 1, "Porto", 20),  # wanted
    (7, 1, 1, "Braga", 30),  # the trap: right carrier, wrong route
    (9, 3, 1, "Ourense", 40),  # the trap: the other way round
]


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines holding the same four rows."""
    with three_sessions([CargoLeg]) as sessions:
        for session in sessions.values():
            session.add_all(
                [
                    CargoLeg(
                        carrier_id=carrier,
                        route_id=route,
                        leg=leg,
                        city=city,
                        units=units,
                    )
                    for carrier, route, leg, city, units in _ROWS
                ]
            )
            session.commit()
        yield sessions


def _pairs(rows: list[CargoLeg]) -> list[tuple[int, int]]:
    """The carrier/route pairs of a result, sorted so the engines' orders do not matter."""
    return sorted((row.carrier_id, row.route_id) for row in rows)


@pytest.mark.parametrize("engine", _ENGINES)
def test_it_answers_the_pairs_asked_for_and_not_their_cartesian_product(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """THE test of this file: the two queries are run together and must disagree.

    The second assertion is the one that carries the weight. A composite IN that had silently become
    a conjunction would pass the first — the two wanted rows are in the four — and fail here.
    """
    session = engines[engine]

    composite = session.all(
        SnakeQuery(CargoLeg).filter(
            snake_keys(CargoLeg).in_(
                [
                    snake_key(CargoLeg)
                    .set(CargoLeg.carrier_id, 7)
                    .set(CargoLeg.route_id, 3),
                    snake_key(CargoLeg)
                    .set(CargoLeg.carrier_id, 9)
                    .set(CargoLeg.route_id, 1),
                ]
            )
        )
    )
    naive = session.all(
        SnakeQuery(CargoLeg).filter(
            CargoLeg.carrier_id.in_([7, 9]) & CargoLeg.route_id.in_([3, 1])
        )
    )

    assert _pairs(composite) == [(7, 3), (9, 1)]
    assert _pairs(naive) == [(7, 1), (7, 3), (9, 1), (9, 3)], (
        "the column-at-a-time version stopped returning the cartesian product, so this test is no "
        "longer comparing two different questions"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_three_column_key_narrows_further(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Width three, on the whole primary key: one row asked for, one row back."""
    session = engines[engine]

    rows = session.all(
        SnakeQuery(CargoLeg).filter(
            snake_keys(CargoLeg).in_(
                [
                    snake_key(CargoLeg)
                    .set(CargoLeg.carrier_id, 7)
                    .set(CargoLeg.route_id, 3)
                    .set(CargoLeg.leg, 1),
                    snake_key(CargoLeg)
                    .set(CargoLeg.carrier_id, 9)
                    .set(CargoLeg.route_id, 1)
                    .set(CargoLeg.leg, 99),  # no such leg
                ]
            )
        )
    )

    assert _pairs(rows) == [(7, 3)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_four_columns_mix_the_key_with_columns_outside_it(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Nothing here is about PRIMARY keys: a tuple of any four columns is a legal row constructor."""
    session = engines[engine]

    rows = session.all(
        SnakeQuery(CargoLeg).filter(
            snake_keys(CargoLeg).in_(
                [
                    snake_key(CargoLeg)
                    .set(CargoLeg.carrier_id, 7)
                    .set(CargoLeg.route_id, 3)
                    .set(CargoLeg.city, "Vigo")
                    .set(CargoLeg.units, 10)
                ]
            )
        )
    )

    assert _pairs(rows) == [(7, 3)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_columns_that_are_not_the_key_work_the_same(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`(city, units)` is not a key on any table here, and the engine does not care."""
    session = engines[engine]

    rows = session.all(
        SnakeQuery(CargoLeg).filter(
            snake_keys(CargoLeg).in_(
                [
                    snake_key(CargoLeg)
                    .set(CargoLeg.city, "Vigo")
                    .set(CargoLeg.units, 10),
                    snake_key(CargoLeg)
                    .set(CargoLeg.city, "Braga")
                    .set(CargoLeg.units, 99),
                ]
            )
        )
    )

    assert _pairs(rows) == [(7, 3)], (
        "the second pair matches no row: only the first comes back"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_scalar_expression_in_a_slot_reaches_the_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`UPPER(city)` on the left of a row constructor, run rather than asserted as a string.

    Every engine spells `UPPER` the same, which is why this one function is enough to prove that a
    slot is not restricted to a bare column.
    """
    session = engines[engine]
    upper = snake_upper(CargoLeg.city)

    rows = session.all(
        SnakeQuery(CargoLeg).filter(
            snake_keys(CargoLeg).in_(
                [
                    snake_key(CargoLeg).set(upper, "VIGO").set(CargoLeg.units, 10),
                    snake_key(CargoLeg).set(upper, "PORTO").set(CargoLeg.units, 20),
                ]
            )
        )
    )

    assert _pairs(rows) == [(7, 3), (9, 1)]


class _NoRowConstructor(SQLiteDialect):
    """SQLite with the capability switched off, to reach the branch no engine asks for.

    Not a mock of the engine: everything below the flag is the real dialect, and the SQL it emits
    runs against the real database. What is faked is the ANSWER TO ONE QUESTION, which is the only
    way to exercise a fallback that all three engines make unnecessary.
    """

    supports_row_constructor = False


@pytest.mark.parametrize("engine", ["sqlite"])
def test_the_fallback_answers_the_same_rows_as_the_row_constructor(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The OR-of-ANDs branch returns exactly what the row constructor returns, on a real engine.

    Both branches of `SnakeTupleIn` translate the SAME question, and until now only one of them had
    ever met a database: all three engines declare `Cap.ROW_CONSTRUCTOR: Full()`, so the fallback
    lived on a fake dialect and a string comparison. A translation whose two halves are only ever
    compared as strings is a translation nobody has checked the meaning of.
    """
    session = engines[engine]
    condition = snake_keys(CargoLeg).in_(
        [
            snake_key(CargoLeg).set(CargoLeg.carrier_id, 7).set(CargoLeg.route_id, 3),
            snake_key(CargoLeg).set(CargoLeg.carrier_id, 9).set(CargoLeg.route_id, 1),
        ]
    )
    query = SnakeQuery(CargoLeg).filter(condition)

    through_constructor = session.all(query)
    # The SAME connection, so the two branches are asked of the same rows and not of two databases
    # that merely agree. The session keeps its driver private, which is right; a test that needs the
    # connection itself is exactly the case that private is not protecting anyone from.
    fallback = SnakeSession(session._driver, _NoRowConstructor())
    through_fallback = fallback.all(query)

    assert "IN ((" in query.to_sql(session.dialect)[0]
    assert " OR " in query.to_sql(_NoRowConstructor())[0]
    assert _pairs(through_fallback) == _pairs(through_constructor) == [(7, 3), (9, 1)]
