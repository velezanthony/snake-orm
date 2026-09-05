"""Tests for the CEILINGS of a declared parameter, which are the ENGINE's knowledge.

What means nothing on any engine already dies at declaration time (`test/metadata/test_type_param_ranges`).
What is left is different: `NUMERIC(500,2)` is perfectly valid on Postgres and impossible on MySQL,
which stops at 65 digits. There is no correct number — there is one per engine.

That is why they live where `max_bind_params` already lived: as dialect attributes, on the Protocol.
It is not a placement detail. A module-private constant (which is how the date ceiling came in) solves
today's case and forces nobody: the day someone writes a new dialect, the Protocol demands they
declare their ceilings and the checker reminds them, whereas a private constant stays quiet and the
new engine inherits the silence.

`None` is a legitimate answer, and it is SQLite's: it is not that it has no ceiling, it is that it
IGNORES the declared parameter —it has a per-column affinity and nothing else—, so no number would be
true.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SQLiteDialect,
    SnakeColumn,
    snake_auto,
    snake_decimal,
)
from snakeorm.compiler import compile_model
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects import SnakeDialect
from snakeorm.migration.ddl import sql_type_of

_DIALECTS = [PostgresDialect(), MySQLDialect(), SQLiteDialect()]


def _sql_type(dialect: SnakeDialect, precision: int, scale: int | None = None) -> str:
    """The SQL type emitted by a `Decimal` declared with that precision and scale."""
    model = type(
        "M",
        (),
        {
            "__annotations__": {"id": SnakeColumn[int], "c": SnakeColumn[Decimal]},
            "id": snake_auto(),
            "c": snake_decimal(precision=precision, scale=scale),
        },
    )
    column = compile_model(model).get_column("c")
    assert column is not None
    return sql_type_of(column, dialect)


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
@pytest.mark.parametrize(
    "flag", ["max_numeric_precision", "max_numeric_scale", "max_fractional_seconds"]
)
def test_every_dialect_declares_its_limits(dialect: SnakeDialect, flag: str) -> None:
    """Verifies that ALL THREE dialects declare the three ceilings.

    It is the half that makes the rest useful: without it, a dialect that forgets one does not fail,
    inherits nobody's behavior and lets DDL that is invalid on its engine through. It is tied to the
    three at once on purpose — a new engine joins this list and inherits the three demands at a stroke.
    """
    value = getattr(dialect, flag)

    assert value is None or (isinstance(value, int) and value > 0), (
        f"{type(dialect).__name__}.{flag} = {value!r}: either a positive ceiling, or None if the "
        f"engine ignores the parameter"
    )


def test_postgres_and_mysql_do_not_agree_on_the_numeric_ceiling() -> None:
    """Verifies that the ceilings DIFFER between engines, which is why they belong to the dialect.

    If they matched, the placement would not matter and a shared constant would do. They do not match:
    Postgres reaches 1000 digits and MySQL stops at 65.
    """
    assert PostgresDialect().max_numeric_precision == 1000
    assert MySQLDialect().max_numeric_precision == 65
    assert MySQLDialect().max_numeric_scale == 30


@pytest.mark.parametrize(
    ("dialect", "limit"), [(PostgresDialect(), 1000), (MySQLDialect(), 65)]
)
def test_the_ceiling_itself_is_allowed(dialect: SnakeDialect, limit: int) -> None:
    """Verifies that the EXACT ceiling passes: it is the edge where one gets it wrong with a `>=`."""
    assert str(limit) in _sql_type(dialect, limit)


@pytest.mark.parametrize(
    ("dialect", "over_limit", "engine"),
    [(PostgresDialect(), 1001, "Postgres"), (MySQLDialect(), 66, "MySQL")],
)
def test_going_over_the_ceiling_is_refused_by_name(
    dialect: SnakeDialect, over_limit: int, engine: str
) -> None:
    """Verifies that going over is denounced by the dialect, naming the engine.

    Naming it matters: the same model is correct on one engine and impossible on another, so a bare
    "invalid precision" would leave the user not knowing whether to fix the model or change database.
    """
    with pytest.raises(SnakeDialectError, match=engine):
        _sql_type(dialect, over_limit)


def test_mysql_caps_the_scale_lower_than_the_precision() -> None:
    """Verifies MySQL's SCALE ceiling, which is lower than the precision one (30 against 65).

    It is a separate ceiling, not the same number: `DECIMAL(40,35)` has a precision MySQL accepts and
    a scale it does not. With a single ceiling, that case would pass and blow up on the engine.
    """
    assert "DECIMAL(40,30)" == _sql_type(MySQLDialect(), 40, 30)
    with pytest.raises(SnakeDialectError, match="MySQL"):
        _sql_type(MySQLDialect(), 40, 35)


def test_sqlite_declares_no_ceiling_because_it_ignores_the_parameter() -> None:
    """Verifies that SQLite says `None` and refuses nothing.

    It is not laziness: SQLite does not store the declared precision, it has a per-column affinity.
    Putting a number —however large— would assert a limit that does not exist, and putting a small one
    would refuse perfectly valid models that engine stores just as well.
    """
    sqlite = SQLiteDialect()

    assert sqlite.max_numeric_precision is None
    assert _sql_type(sqlite, 5000, 4000) == "TEXT"
