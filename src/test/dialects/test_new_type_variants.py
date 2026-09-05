"""The type variants that were missing: `REAL`, `CHAR(n)` and `TIMETZ`.

They are standard SQL and all three engines have them (or know how to degrade them), so their absence
was not a decision: it was an unfinished list. Each one comes in through the door that already existed
—a family of parameters and its declarator— and not through a new knob on `snake_column()`, which is
the disease this branch already cured once.

What each one adds, and why it deserves to exist instead of leaving the default:

- **`REAL`** is 4 bytes instead of 8. On a table of millions of rows with several floating-point
  columns that is half the storage, and a `double`'s precision is not always needed.
- **`CHAR(n)`** is FIXED length. It is not a stricter `VARCHAR(n)`: it pads with spaces and compares
  differently, and whoever stores country codes or ISINs wants it for exactly that.
- **`TIMETZ`** is a time of day WITH a zone. A bare `TIME` loses it, and a shop's opening time in
  another zone stops meaning the same thing.
"""

from __future__ import annotations

from datetime import time

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeColumn,
    SQLiteDialect,
    snake_auto,
    snake_float,
    snake_str,
    snake_time,
    snake_timetz,
)
from snakeorm.compiler import compile_model
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.dialects import SnakeDialect
from snakeorm.migration.ddl import sql_type_of


def _sql_type(dialect: SnakeDialect, annotation: object, specifier: object) -> str:
    """The SQL type emitted by a column declared like this, compiling the model for real.

    It compiles instead of calling `map_type` by hand because the real path goes through the compiler,
    and a hand-written fixture drifts from the model it prepares: that was exactly the failure that
    let two scaffolder bugs through on this very branch.
    """
    model = type(
        "M",
        (),
        {
            "__annotations__": {"id": SnakeColumn[int], "c": annotation},
            "id": snake_auto(),
            "c": specifier,
        },
    )
    column = compile_model(model).get_column("c")
    assert column is not None
    return sql_type_of(column, dialect)


def test_a_four_byte_float_is_not_the_same_as_a_double() -> None:
    """Verifies that `snake_float(size=4)` emits the 4-byte type on every engine.

    And that the default does NOT change: without `size`, a `float` is still 8 bytes, which is what a
    Python `float` is. Changing the default would make existing models lose precision silently on
    upgrade.
    """
    assert (
        _sql_type(PostgresDialect(), SnakeColumn[float], snake_float(size=4)) == "REAL"
    )
    assert _sql_type(MySQLDialect(), SnakeColumn[float], snake_float(size=4)) == "FLOAT"
    assert (
        _sql_type(PostgresDialect(), SnakeColumn[float], snake_float())
        == "DOUBLE PRECISION"
    )
    assert _sql_type(MySQLDialect(), SnakeColumn[float], snake_float()) == "DOUBLE"


def test_sqlite_keeps_its_single_float_and_says_so() -> None:
    """Verifies that SQLite emits `REAL` for both widths: it only has one floating-point class.

    It is not a fallback failure: it is that the engine does not distinguish, and its degraded
    capability already tells that. Emitting something else would invent a precision the base does not
    give.
    """
    assert _sql_type(SQLiteDialect(), SnakeColumn[float], snake_float(size=4)) == "REAL"
    assert _sql_type(SQLiteDialect(), SnakeColumn[float], snake_float()) == "REAL"


def test_a_float_width_that_no_engine_has_dies_on_declaration() -> None:
    """Verifies that a made-up width fails AT DECLARATION time, not at migration time.

    It is the same structural guard the precision and the length already have: what means nothing on
    any engine does not reach the base.
    """
    with pytest.raises(
        SnakeModelDefinitionError, match="A float is either 4 or 8 bytes"
    ):
        snake_float(size=6)


def test_a_fixed_length_text_is_char_not_varchar() -> None:
    """Verifies that `fixed=True` emits `CHAR(n)` where the engine has it."""
    assert (
        _sql_type(
            PostgresDialect(), SnakeColumn[str], snake_str(max_length=2, fixed=True)
        )
        == "CHAR(2)"
    )
    assert (
        _sql_type(MySQLDialect(), SnakeColumn[str], snake_str(max_length=2, fixed=True))
        == "CHAR(2)"
    )
    # Without `fixed`, nothing changes: the one already written is still a VARCHAR.
    assert (
        _sql_type(PostgresDialect(), SnakeColumn[str], snake_str(max_length=2))
        == "VARCHAR(2)"
    )


def test_a_fixed_length_text_without_a_length_dies_on_declaration() -> None:
    """Verifies that `fixed=True` without `max_length` fails at declaration time.

    A bare `CHAR` is `CHAR(1)` in SQL, which is almost never what anyone wants and is certainly not
    what the model reads like. Guessing the 1 would be taking a decision for the user they did not take.
    """
    with pytest.raises(SnakeModelDefinitionError, match="max_length"):
        snake_str(fixed=True)


def test_a_time_of_day_can_carry_its_timezone() -> None:
    """Verifies that `snake_timetz()` emits `TIMETZ` on Postgres and `snake_time()` still gives `TIME`.

    Two declarators, as with the dates: the column SAYS which of the two types it creates, instead of
    it depending on whether the first value that arrived carried a zone.
    """
    assert _sql_type(PostgresDialect(), SnakeColumn[time], snake_timetz()) == "TIMETZ"
    assert _sql_type(PostgresDialect(), SnakeColumn[time], snake_time()) == "TIME"


@pytest.mark.parametrize(
    "dialect", [MySQLDialect(), SQLiteDialect()], ids=lambda d: type(d).__name__
)
def test_an_engine_without_timetz_falls_back_to_text(dialect: SnakeDialect) -> None:
    """Verifies that where there is no `TIMETZ` it falls back to TEXT instead of losing the zone silently.

    Emitting a plain `TIME` would have satisfied the signature and thrown the zone away: exactly the
    kind of silent failure that motivated splitting the two date declarators.
    """
    assert _sql_type(dialect, SnakeColumn[time], snake_timetz()) == "TEXT"
