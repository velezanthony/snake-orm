"""Tests for the STRUCTURAL ranges of the type parameters: what is absurd in any engine.

`snake_decimal(precision=-3)` emitted `NUMERIC(-3)` without blinking. The parameter was accepted,
travelled whole through the graph, got glued onto the DDL, and only Postgres denounced it when
applying the migration, in its own syntax and three steps beyond where the error was. It is the same
pattern this branch has been killing from the start: metadata that means nothing living in the graph
that is supposed to BE the truth.

Only what means nothing in ANY engine is cut off here, and that is why it can live in the metadata
without breaking the golden rule (the graph is agnostic):

    precision < 1        a NUMERIC of zero digits stores no number at all
    scale < 0            a negative scale is not a number of decimals
    scale > precision    more decimals than total digits: the integer part does not fit
    max_length < 1       a VARCHAR admitting only the empty string is not a column, it is a mistake

The CEILING of each one —1000 digits in Postgres, 65 in MySQL— is NOT here: it is engine knowledge
and lives in its dialect, like `max_bind_params`.

About `scale`: Postgres 15 admits negative scales and scales larger than the precision as an
EXTENSION of its own. It is not exposed on purpose. The SQL standard demands `0 <= scale <=
precision`, MySQL demands it, and Postgres demanded it until 15; opening it up here would make a
model stop being portable depending on the server version behind it, which is exactly what the
Dialect/Driver axis exists to avoid. If it is ever needed, it is a conscious decision and it goes in
the dialect, not here.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.metadata import SnakeDecimalParams, SnakeStrParams


@pytest.mark.parametrize("precision", [0, -1, -3])
def test_a_decimal_needs_at_least_one_digit(precision: int) -> None:
    """Checks that a precision lower than 1 dies at declaration time.

    `NUMERIC(0)` stores no number and `NUMERIC(-3)` is nothing at all: both are mistakes by whoever
    writes the model, and the place to say so is the model, not the migration log.
    """
    with pytest.raises(
        SnakeModelDefinitionError, match="NUMERIC has to have at least one digit"
    ):
        SnakeDecimalParams(precision=precision)


def test_a_negative_scale_is_refused() -> None:
    """Checks that a negative scale dies at declaration time.

    `scale` is the decimals; a negative number of decimals does not exist. Postgres 15 gives it
    another meaning as an extension of its own (rounding to the left of the point), and it is not
    exposed: it would tie the model to the server version.
    """
    with pytest.raises(
        SnakeModelDefinitionError, match="scale of a NUMERIC cannot be negative"
    ):
        SnakeDecimalParams(precision=10, scale=-2)


def test_the_scale_cannot_exceed_the_precision() -> None:
    """Checks that `scale > precision` dies at declaration time.

    It is the most misleading case because both numbers are valid on their own: `NUMERIC(5,9)` asks
    for nine decimals within five total digits, so there is no room left for the integer part.
    """
    with pytest.raises(
        SnakeModelDefinitionError, match="scale cannot exceed the precision"
    ):
        SnakeDecimalParams(precision=5, scale=9)


@pytest.mark.parametrize(
    ("precision", "scale"), [(12, 2), (5, 5), (10, 0), (1, 0), (1000, 1000)]
)
def test_the_legal_combinations_still_pass(precision: int, scale: int) -> None:
    """Checks that what is valid still passes, edges included.

    `scale == precision` is legal —`NUMERIC(5,5)` stores `0.12345`, with no integer part— and a
    guard written with `>=` instead of `>` would forbid it. The edge is exactly where one slips.
    """
    parametros = SnakeDecimalParams(precision=precision, scale=scale)

    assert (parametros.precision, parametros.scale) == (precision, scale)


def test_a_decimal_without_scale_is_still_valid() -> None:
    """Checks that not declaring a scale is still valid: it is `NUMERIC(p)`, with an implicit scale of 0."""
    assert SnakeDecimalParams(precision=12).scale is None


@pytest.mark.parametrize("max_length", [0, -1])
def test_a_varchar_needs_room_for_at_least_one_character(max_length: int) -> None:
    """Checks that a length lower than 1 dies at declaration time.

    `VARCHAR(0)` is legal in both engines and useful for nothing: it only admits the empty string.
    That the engine accepts it does not make it a reasonable declaration, and this ORM shouts
    instead of letting through a column nobody meant to write that way.
    """
    with pytest.raises(
        SnakeModelDefinitionError, match="VARCHAR has to fit at least one character"
    ):
        SnakeStrParams(max_length=max_length)


def test_a_str_without_max_length_is_still_valid() -> None:
    """Checks that not declaring a length is still valid: it is the unbounded `TEXT`, the normal case."""
    assert SnakeStrParams().max_length is None


def test_db_first_translates_the_guard_instead_of_crashing_with_it() -> None:
    """Checks that reading an out-of-range NUMERIC from the DB gives an INTROSPECTION error.

    It is the edge a new guard runs over without meaning to: these parameters are also built by the
    introspector, and there nobody writes the numbers — the database brings them. A `NUMERIC` with a
    negative scale (a Postgres 15 extension) would blow up the whole scaffold with a message talking
    to the user about what they "declared", when they declared nothing.

    That it keeps failing is correct: the mirror CANNOT reproduce that column, and keeping quiet
    would produce a model that lies. What changes is what is being blamed on whom.
    """
    from snakeorm.core.exceptions import SnakeMigrationError
    from snakeorm.introspection.postgres import _type_params

    with pytest.raises(SnakeMigrationError, match="NUMERIC"):
        _type_params("numeric", None, 5, -2)


def test_db_first_still_reads_a_normal_numeric() -> None:
    """Checks that the happy path of the introspector has not been touched."""
    from snakeorm.introspection.postgres import _type_params

    assert _type_params("numeric", None, 12, 2) == SnakeDecimalParams(12, 2)
